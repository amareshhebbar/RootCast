"""Counterfactual replay: re run a trace with one value changed.

Replay never touches the live run. It walks the recorded steps in order:

  unchanged   inputs are identical to the recording, so the recorded result
              is served from the trace (the cache). Upstream steps always land here.
  injected    the user set this step's output (or an input) with --set.
  recomputed  an upstream change reached this step's inputs, so the agent's own
              function is called again with the rewritten inputs.

External calls (tool, io and llm steps by default) are never called out to.
When one of them would have to be recomputed, replay stops with
ExternalCallError and asks for the value to be injected explicitly. An agent
can mark a function as safe to re run (a sandboxed stand in) with
external=False when registering it.

The result is a ReplayResult: a step by step diff between the recorded run
and the replayed one plus the run status delta. It renders as text for the
CLI and serializes with to_dict() for the UI.
"""
from __future__ import annotations

import copy
import importlib.util
import json
import os
from dataclasses import dataclass, field
from typing import Any, Callable, Optional

from .infer import MIN_STRING_LEN, _is_scalar_trivial
from .recorder import Recorder
from .schema import Step, Trace, encode, ref_of, snapshot

EXTERNAL_KINDS = {"tool", "io", "llm"}

UNCHANGED, INJECTED, RECOMPUTED = "unchanged", "injected", "recomputed"


class ReplayError(Exception):
    """Replay cannot proceed. The message says what to pass to fix it."""


class ExternalCallError(ReplayError):
    def __init__(self, step: Step):
        self.step_id = step.id
        super().__init__(
            step.id + " " + step.name + " is an external " + step.kind + " call and its inputs changed. "
            "Replay never calls out. Inject its result with --set " + step.id + ".output=VALUE"
        )


# The agent side ----------------------------------------------------------


@dataclass
class _Entry:
    fn: Callable
    external: Optional[bool]


class Agent:
    """Functions replay may call, by step name.

    Register the same functions the agent records with, built against the
    Recorder replay hands you, so status and errors are captured the same way.
    """

    def __init__(self) -> None:
        self.entries: dict[str, _Entry] = {}

    def add(self, fn: Callable, name: Optional[str] = None, external: Optional[bool] = None) -> Callable:
        """external None means decided by the step kind; False marks a safe, sandboxed function."""
        self.entries[name or fn.__name__] = _Entry(fn, external)
        return fn


def load_agent_module(path: str):
    """Import an agent file. It must define replay_agent(rec) and may define REPLAY_VALUES."""
    spec = importlib.util.spec_from_file_location("rootcast_replay_agent", os.path.abspath(path))
    if spec is None or spec.loader is None:
        raise ReplayError("cannot load agent " + path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "replay_agent"):
        raise ReplayError(path + " does not define replay_agent(rec)")
    return module


# Injections --------------------------------------------------------------


@dataclass
class Injection:
    step_id: str
    target: str  # "output" or "inputs"
    path: list
    value: Any
    raw: str = ""

    @property
    def label(self) -> str:
        return self.raw or (self.step_id + "." + ".".join([self.target] + [str(p) for p in self.path]))


def parse_set(spec: str, trace: Trace, named: Optional[dict] = None) -> Injection:
    """Parse "step2.output=VALUE" or "step2.output.window_days=30" or "step2.inputs.query=x".

    The step may be named by id or by name. VALUE is JSON when it parses,
    else a name from the agent's REPLAY_VALUES, else @file.json, else a plain string.
    """
    if "=" not in spec:
        raise ReplayError("--set needs STEP.output=VALUE, got " + spec)
    lhs, raw_value = spec.split("=", 1)
    parts = lhs.strip().split(".")
    if len(parts) < 2:
        raise ReplayError("--set needs STEP.output=VALUE, got " + spec)
    ref, target, path = parts[0], parts[1], parts[2:]
    if target == "result":
        target = "output"
    if target not in ("output", "inputs"):
        raise ReplayError("--set target must be output or inputs, got " + target)
    if target == "inputs" and not path:
        raise ReplayError("--set on inputs needs a key, for example " + ref + ".inputs.query=VALUE")
    step = trace.get(ref) or next((s for s in trace.steps if s.name == ref), None)
    if step is None:
        raise ReplayError("no step " + ref + " in run " + trace.run_id)
    return Injection(step.id, target, [_index(p) for p in path], _value(raw_value, named or {}), spec)


def _index(part: str):
    return int(part) if part.isdigit() else part


def _value(raw: str, named: dict) -> Any:
    try:
        return json.loads(raw)
    except ValueError:
        pass
    if raw in named:
        return copy.deepcopy(named[raw])
    if raw.startswith("@"):
        with open(raw[1:], "r", encoding="utf-8") as fh:
            return json.load(fh)
    return raw


def _set_path(value: Any, path: list, new: Any) -> Any:
    if not path:
        return copy.deepcopy(new)
    out = copy.deepcopy(value)
    node = out
    for key in path[:-1]:
        try:
            node = node[key]
        except (KeyError, IndexError, TypeError):
            raise ReplayError("path " + ".".join(map(str, path)) + " does not exist")
    try:
        node[path[-1]] = copy.deepcopy(new)
    except (IndexError, TypeError):
        raise ReplayError("path " + ".".join(map(str, path)) + " does not exist")
    return out


# Data flow rewriting -----------------------------------------------------


def _paths(value: Any, prefix: tuple = ()):
    yield prefix, value
    if isinstance(value, dict):
        for k, v in value.items():
            yield from _paths(v, prefix + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from _paths(v, prefix + (i,))


def _get(value: Any, path: tuple):
    for key in path:
        value = value[key]
    return value


def _substitutions(old: Any, new: Any) -> dict[str, Any]:
    """Map the hash of every non trivial part of an old output to the matching part of the new one."""
    subs: dict[str, Any] = {}
    for path, part in _paths(old):
        if path and _is_scalar_trivial(part, MIN_STRING_LEN):
            continue
        if not path and part is None:
            continue
        try:
            subs[ref_of(part)] = _get(new, path)
        except (KeyError, IndexError, TypeError):
            continue
    return subs


def _rewrite(value: Any, subs: dict[str, Any], top: bool = True) -> Any:
    eligible = not _is_scalar_trivial(value, MIN_STRING_LEN) or (
        top and isinstance(value, (int, float)) and not isinstance(value, bool)
    )
    if eligible:
        h = ref_of(value)
        if h in subs:
            return copy.deepcopy(subs[h])
    if isinstance(value, dict):
        return {k: _rewrite(v, subs, False) for k, v in value.items()}
    if isinstance(value, list):
        return [_rewrite(v, subs, False) for v in value]
    return value


# Diff --------------------------------------------------------------------


@dataclass
class FieldChange:
    path: str
    before: Any
    after: Any

    def to_dict(self) -> dict:
        return {"path": self.path, "before": self.before, "after": self.after}


_MISSING = object()


def diff_values(before: Any, after: Any, path: str = "") -> list[FieldChange]:
    """Leaf level differences between two JSON values."""
    if ref_of(before) == ref_of(after):
        return []
    if isinstance(before, dict) and isinstance(after, dict):
        out: list[FieldChange] = []
        for key in sorted(set(before) | set(after)):
            sub = path + "." + key if path else key
            b, a = before.get(key, _MISSING), after.get(key, _MISSING)
            if b is _MISSING or a is _MISSING:
                out.append(FieldChange(sub, None if b is _MISSING else b, None if a is _MISSING else a))
            else:
                out.extend(diff_values(b, a, sub))
        return out
    if isinstance(before, list) and isinstance(after, list) and len(before) == len(after):
        out = []
        for i, (b, a) in enumerate(zip(before, after)):
            out.extend(diff_values(b, a, path + "[" + str(i) + "]"))
        return out
    return [FieldChange(path, before, after)]


@dataclass
class StepDiff:
    step_id: str
    name: str
    kind: str
    change: str
    status_before: str
    status_after: str
    error_before: Optional[str] = None
    error_after: Optional[str] = None
    inputs: list[FieldChange] = field(default_factory=list)
    output: list[FieldChange] = field(default_factory=list)

    @property
    def status_changed(self) -> bool:
        return self.status_before != self.status_after

    @property
    def changed(self) -> bool:
        return bool(self.inputs or self.output or self.status_changed or self.error_before != self.error_after)

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "kind": self.kind,
            "change": self.change,
            "changed": self.changed,
            "status": {"before": self.status_before, "after": self.status_after},
            "error": {"before": self.error_before, "after": self.error_after},
            "inputs": [c.to_dict() for c in self.inputs],
            "output": [c.to_dict() for c in self.output],
        }


@dataclass
class ReplayResult:
    """What the UI consumes: the injections, the per step diff and the status delta."""

    original: Trace
    replayed: Trace
    injections: list[Injection]
    steps: list[StepDiff]

    @property
    def status_before(self) -> str:
        return self.original.status

    @property
    def status_after(self) -> str:
        return self.replayed.status

    @property
    def flipped(self) -> bool:
        return self.status_before != self.status_after

    @property
    def changed_steps(self) -> list[str]:
        return [d.step_id for d in self.steps if d.changed]

    def get(self, step_id: str) -> Optional[StepDiff]:
        return next((d for d in self.steps if d.step_id == step_id), None)

    def to_dict(self) -> dict:
        return {
            "run_id": self.original.run_id,
            "injections": [
                {"step_id": i.step_id, "target": i.target, "path": i.path, "value": i.value, "spec": i.label}
                for i in self.injections
            ],
            "status": {"before": self.status_before, "after": self.status_after, "flipped": self.flipped},
            "changed_steps": self.changed_steps,
            "steps": [d.to_dict() for d in self.steps],
            "replayed_trace": self.replayed.to_dict(),
        }


# Executor ----------------------------------------------------------------


def _run_status(original: Trace, steps: list[Step]) -> str:
    if any(s.status == "fail" for s in steps):
        return "fail"
    if original.status == "fail" and not any(s.status == "fail" for s in original.steps):
        return "unknown"
    return "pass"


def replay(trace: Trace, injections: list[Injection], agent_factory: Optional[Callable] = None) -> ReplayResult:
    """Re run trace with injections applied and diff it against the recording.

    agent_factory(rec) returns an Agent (or a dict of name to function) built
    against the Recorder it is given. It is only needed when a step has to be
    recomputed.
    """
    if not injections:
        raise ReplayError("nothing to replay: pass at least one --set")
    by_step: dict[str, list[Injection]] = {}
    for inj in injections:
        by_step.setdefault(inj.step_id, []).append(inj)

    rec = Recorder(run_id=trace.run_id, clock=lambda: 0.0, infer=False)
    agent: Optional[Agent] = None

    def get_agent() -> Agent:
        nonlocal agent
        if agent is None:
            if agent_factory is None:
                raise ReplayError("a step must be recomputed, pass --agent with a replay_agent(rec) function")
            built = agent_factory(rec)
            if isinstance(built, dict):
                built_agent = Agent()
                for name, fn in built.items():
                    built_agent.add(fn, name=name)
                built = built_agent
            agent = built
        return agent

    subs: dict[str, Any] = {}
    new_steps: list[Step] = []
    diffs: list[StepDiff] = []

    for step in trace.steps:
        old_output = step.resolved_output(trace.blobs)
        new_inputs = (
            {k: _rewrite(v, subs) for k, v in step.inputs.items()} if step.inputs is not None else None
        )
        out_inj = [i for i in by_step.get(step.id, []) if i.target == "output"]
        in_inj = [i for i in by_step.get(step.id, []) if i.target == "inputs"]
        for inj in in_inj:
            new_inputs = snapshot(_set_path(new_inputs or {}, inj.path, inj.value))

        new = copy.deepcopy(step)
        new.inputs = new_inputs
        new.output_ref = None

        if out_inj:
            change = INJECTED
            value = old_output
            for inj in out_inj:
                value = _set_path(value, inj.path, inj.value)
            new.output, new.status, new.error = snapshot(value), "pass", None
        elif ref_of(new_inputs) == ref_of(step.inputs):
            change = UNCHANGED
            new.output = old_output
        else:
            change = RECOMPUTED
            entries = get_agent().entries
            entry = entries.get(step.name)
            if entry is None:
                raise ReplayError(
                    step.id + " " + step.name + " must be recomputed but the agent does not register it"
                )
            external = entry.external if entry.external is not None else step.kind in EXTERNAL_KINDS
            if external:
                raise ExternalCallError(step)
            mark = len(rec.trace.steps)
            try:
                entry.fn(**(new_inputs or {}))
            except Exception:
                pass
            if len(rec.trace.steps) <= mark:
                raise ReplayError(step.name + " ran but recorded no step; register the recorded function")
            ran = rec.trace.steps[mark]
            new.output = ran.resolved_output(rec.trace.blobs)
            new.status, new.error = ran.status, ran.error

        new_steps.append(new)
        if ref_of(new.output) != ref_of(old_output):
            subs.update(_substitutions(old_output, new.output))
        diffs.append(StepDiff(
            step_id=step.id,
            name=step.name,
            kind=step.kind,
            change=change,
            status_before=step.status,
            status_after=new.status,
            error_before=step.error,
            error_after=new.error,
            inputs=diff_values(step.inputs, new.inputs),
            output=diff_values(old_output, new.output),
        ))

    replayed = Trace(
        run_id=trace.run_id,
        status=_run_status(trace, new_steps),
        meta=dict(trace.meta, replay_of=trace.run_id, replay_set=[i.label for i in injections]),
        steps=new_steps,
    )
    return ReplayResult(original=trace, replayed=replayed, injections=list(injections), steps=diffs)


# Text --------------------------------------------------------------------

TAG = {"pass": "ok", "warn": "WARN", "fail": "FAIL", "unknown": ".."}
MAX_VALUE = 48


def _short(value: Any) -> str:
    text = encode(value)
    return text if len(text) <= MAX_VALUE else text[: MAX_VALUE - 3] + "..."


def _label(prefix: str, path: str) -> str:
    if not path:
        return prefix
    return prefix + path if path.startswith("[") else prefix + "." + path


def render_replay(result: ReplayResult) -> str:
    steps = result.original.steps
    id_w = max(len(s.id) for s in steps) + 2
    name_w = max(len(s.name) for s in steps) + 2
    lines = ["replay " + result.original.run_id + "  " + "  ".join("--set " + i.label for i in result.injections), ""]
    for d in result.steps:
        status = TAG.get(d.status_after, d.status_after)
        if d.status_changed:
            status = TAG.get(d.status_before, d.status_before) + " -> " + status
        lines.append("  " + d.step_id.ljust(id_w) + d.name.ljust(name_w) + d.change.ljust(12) + status)
        changes = [(_label("inputs", c.path), c) for c in d.inputs] + [(_label("output", c.path), c) for c in d.output]
        if changes:
            path_w = max(len(p) for p, _ in changes) + 2
            for path, c in changes:
                lines.append(
                    " " * (4 + id_w) + path.ljust(path_w) + _short(c.before) + " -> " + _short(c.after)
                )
    lines.append("")
    upstream = [d.step_id for d in result.steps if not d.changed]
    lines.append("  changed: " + (", ".join(result.changed_steps) or "none"))
    lines.append("  untouched: " + (", ".join(upstream) or "none"))
    verdict = "flipped" if result.flipped else "no change"
    lines.append(
        "  run: " + result.status_before.upper() + " -> " + result.status_after.upper() + "  (" + verdict + ")"
    )
    return "\n".join(lines)
