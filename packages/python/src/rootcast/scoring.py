"""Per step PASS / WARN / FAIL scoring and anomaly flags.

Scoring looks at each step in isolation (plus the steps that fed it) and
asks "does this step look wrong?". It never decides the cause of a failure,
that is the causal engine's job, which imports this module.

Rules, each producing Flag objects:

  step_error    FAIL  the step raised or carries an error text
  agent_status  FAIL / WARN  the agent set the step status itself
  empty_result  WARN  a tool or io step returned nothing
  error_result  WARN  a tool or io step returned an object carrying an error
  type_drift    WARN  a value came out as a string where the inputs had a number, or the reverse
  mismatch      WARN  a tool or io step answered with a different value for a key it was asked about
  stale         WARN  a step fed data from an older year than its siblings into the same consumer

Anomaly flags (level "info") never change a step's status:

  slow          the step took far longer than the rest of the run, or than usual
  large_result  the step returned far more bytes than usual
  small_result  the step returned far fewer bytes than usual

"Usual" comes from a Baseline built from earlier traces of the same agent.
"""
from __future__ import annotations

import re
import statistics
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .schema import Step, Trace, canonical_bytes, encode

PASS, WARN, FAIL = "pass", "warn", "fail"
INFO = "info"
_RANK = {PASS: 0, INFO: 0, WARN: 1, FAIL: 2}

RESULT_KINDS = {"tool", "io"}

SLOW_FACTOR = 5.0
SLOW_MIN_SECONDS = 1.0
SIZE_FACTOR = 10.0
MIN_SAMPLES = 3
MAX_CATEGORICAL_LEN = 64
YEAR_RANGE = (1900, 2100)

_DATE = re.compile(r"^(\d{4})-\d{2}-\d{2}")


@dataclass
class Flag:
    rule: str
    level: str
    message: str

    def to_dict(self) -> dict:
        return {"rule": self.rule, "level": self.level, "message": self.message}


@dataclass
class Score:
    step_id: str
    name: str
    status: str = PASS
    flags: list[Flag] = field(default_factory=list)

    def add(self, flag: Flag) -> None:
        self.flags.append(flag)
        if _RANK[flag.level] > _RANK[self.status]:
            self.status = flag.level

    @property
    def problems(self) -> list[Flag]:
        """Flags that set the status, most severe first. Anomalies excluded."""
        found = [f for f in self.flags if f.level in (WARN, FAIL)]
        return sorted(found, key=lambda f: -_RANK[f.level])

    def to_dict(self) -> dict:
        return {
            "step_id": self.step_id,
            "name": self.name,
            "status": self.status,
            "flags": [f.to_dict() for f in self.flags],
        }


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _scalar_type(value: Any) -> Optional[str]:
    if _is_number(value):
        return "number"
    if isinstance(value, str):
        return "string"
    return None


def _keyed_scalars(value: Any, out: Optional[dict] = None, key: Optional[str] = None) -> dict[str, list]:
    """Every scalar inside value, grouped by the object key it sits under."""
    if out is None:
        out = {}
    if isinstance(value, dict):
        for k, v in value.items():
            _keyed_scalars(v, out, str(k))
    elif isinstance(value, list):
        for item in value:
            _keyed_scalars(item, out, key)
    elif key is not None:
        out.setdefault(key, []).append(value)
    return out


def _output(step: Step, trace: Trace) -> Any:
    return step.resolved_output(trace.blobs)


def _short(value: Any) -> str:
    return encode(value)


# Single step rules -------------------------------------------------------


def rule_step_error(step: Step, trace: Trace) -> list[Flag]:
    if step.error:
        return [Flag("step_error", FAIL, step.error)]
    return []


def rule_agent_status(step: Step, trace: Trace) -> list[Flag]:
    if step.error:
        return []
    if step.status == FAIL:
        return [Flag("agent_status", FAIL, "marked fail by the agent")]
    if step.status == WARN:
        return [Flag("agent_status", WARN, "marked warn by the agent")]
    return []


def rule_empty_result(step: Step, trace: Trace) -> list[Flag]:
    if step.kind not in RESULT_KINDS or step.error or step.output_ref is not None:
        return []
    value = step.output
    if value is None or value == "" or value == {} or value == []:
        return [Flag("empty_result", WARN, "returned an empty result")]
    return []


def rule_error_result(step: Step, trace: Trace) -> list[Flag]:
    if step.kind not in RESULT_KINDS or step.error:
        return []
    value = _output(step, trace)
    if isinstance(value, dict):
        for key in ("error", "errors"):
            if value.get(key):
                return [Flag("error_result", WARN, "result carries an error: " + _short(value[key]))]
    return []


def rule_type_drift(step: Step, trace: Trace) -> list[Flag]:
    if not step.inputs:
        return []
    ins = _keyed_scalars(step.inputs)
    outs = _keyed_scalars(_output(step, trace))
    flags = []
    for key, out_values in outs.items():
        in_types = {_scalar_type(v) for v in ins.get(key, [])} - {None}
        if len(in_types) != 1:
            continue
        in_type = in_types.pop()
        for value in out_values:
            out_type = _scalar_type(value)
            if out_type is not None and out_type != in_type:
                flags.append(Flag(
                    "type_drift",
                    WARN,
                    key + " changed from " + in_type + " to " + out_type + " (" + _short(value) + ")",
                ))
                break
    return flags


def rule_mismatch(step: Step, trace: Trace) -> list[Flag]:
    if step.kind not in RESULT_KINDS or not step.inputs or step.error:
        return []
    ins = _keyed_scalars(step.inputs)
    outs = _keyed_scalars(_output(step, trace))
    flags = []
    for key, out_values in outs.items():
        asked = {v for v in ins.get(key, []) if isinstance(v, str) and len(v) <= MAX_CATEGORICAL_LEN}
        got = {v for v in out_values if isinstance(v, str) and len(v) <= MAX_CATEGORICAL_LEN}
        if asked and got and not (asked & got):
            flags.append(Flag(
                "mismatch",
                WARN,
                "asked " + key + "=" + "|".join(sorted(asked)) + ", got " + key + "=" + "|".join(sorted(got)),
            ))
    return flags


STEP_RULES = (
    rule_step_error,
    rule_agent_status,
    rule_empty_result,
    rule_error_result,
    rule_type_drift,
    rule_mismatch,
)


# Cross step rules --------------------------------------------------------


def _years(value: Any) -> list[int]:
    found = []
    for key, values in _keyed_scalars(value).items():
        lowered = key.lower()
        for v in values:
            if (lowered == "year" or lowered.endswith("_year")) and isinstance(v, int) and not isinstance(v, bool):
                if YEAR_RANGE[0] <= v <= YEAR_RANGE[1]:
                    found.append(v)
            elif "date" in lowered and isinstance(v, str):
                m = _DATE.match(v)
                if m:
                    found.append(int(m.group(1)))
    return found


def rule_stale(trace: Trace) -> dict[str, list[Flag]]:
    """Producers that fed one consumer data from different years: the older ones are stale."""
    by_id = {s.id: s for s in trace.steps}
    flagged: dict[str, list[Flag]] = {}
    for consumer in trace.steps:
        dated = []
        for dep in consumer.depends_on:
            producer = by_id.get(dep)
            if producer is None:
                continue
            years = _years(_output(producer, trace))
            if years:
                dated.append((producer, max(years)))
        if len(dated) < 2:
            continue
        newest_step, newest = max(dated, key=lambda pair: pair[1])
        for producer, year in dated:
            if year < newest and producer.id not in flagged:
                flagged[producer.id] = [Flag(
                    "stale",
                    WARN,
                    "returned " + str(year) + " data, " + newest_step.name + " is " + str(newest),
                )]
    return flagged


# Anomalies ---------------------------------------------------------------


def _duration(step: Step) -> Optional[float]:
    if _is_number(step.started_at) and _is_number(step.ended_at):
        return float(step.ended_at) - float(step.started_at)
    return None


def _size(step: Step, trace: Trace) -> int:
    value = _output(step, trace)
    return 0 if value is None else len(canonical_bytes(value))


def _num(x: float) -> str:
    return ("%.2f" % x).rstrip("0").rstrip(".")


@dataclass
class Baseline:
    """Usual duration and output size per step name, from earlier runs."""

    durations: dict[str, list[float]] = field(default_factory=dict)
    sizes: dict[str, list[int]] = field(default_factory=dict)

    @classmethod
    def from_traces(cls, traces: Iterable[Trace]) -> "Baseline":
        base = cls()
        for trace in traces:
            for step in trace.steps:
                d = _duration(step)
                if d is not None:
                    base.durations.setdefault(step.name, []).append(d)
                if not step.error:
                    base.sizes.setdefault(step.name, []).append(_size(step, trace))
        return base

    def usual_duration(self, name: str) -> Optional[float]:
        values = self.durations.get(name, [])
        return statistics.median(values) if len(values) >= MIN_SAMPLES else None

    def usual_size(self, name: str) -> Optional[float]:
        values = self.sizes.get(name, [])
        return statistics.median(values) if len(values) >= MIN_SAMPLES else None


def anomaly_flags(trace: Trace, baseline: Optional[Baseline] = None) -> dict[str, list[Flag]]:
    flags: dict[str, list[Flag]] = {}
    timed = [(s, _duration(s)) for s in trace.steps]
    timed = [(s, d) for s, d in timed if d is not None]

    for step, d in timed:
        others = [x for s, x in timed if s is not step]
        usual = baseline.usual_duration(step.name) if baseline else None
        if usual is not None:
            reference, label = usual, "usual for " + step.name
        elif len(others) >= MIN_SAMPLES:
            reference, label = statistics.median(others), "the run median"
        else:
            continue
        if d >= SLOW_MIN_SECONDS and d > SLOW_FACTOR * max(reference, 1e-9):
            flags.setdefault(step.id, []).append(Flag(
                "slow",
                INFO,
                "took " + _num(d) + "s, " + label + " is " + _num(reference) + "s",
            ))

    if baseline is not None:
        for step in trace.steps:
            usual = baseline.usual_size(step.name)
            if usual is None or step.error:
                continue
            size = _size(step, trace)
            if size > SIZE_FACTOR * max(usual, 1):
                rule, word = "large_result", "more"
            elif usual >= SIZE_FACTOR and size * SIZE_FACTOR < usual:
                rule, word = "small_result", "less"
            else:
                continue
            flags.setdefault(step.id, []).append(Flag(
                rule,
                INFO,
                "returned " + str(size) + " bytes, far " + word + " than the usual " + _num(usual),
            ))
    return flags


# Entry point -------------------------------------------------------------


def score_step(step: Step, trace: Trace) -> Score:
    """Score one step with the single step rules only."""
    score = Score(step.id, step.name)
    for rule in STEP_RULES:
        for flag in rule(step, trace):
            score.add(flag)
    return score


def score_trace(trace: Trace, baseline: Optional[Baseline] = None) -> dict[str, Score]:
    """Score every step. Returns step id to Score, in trace order."""
    scores = {step.id: score_step(step, trace) for step in trace.steps}
    for extra in (rule_stale(trace), anomaly_flags(trace, baseline)):
        for sid, flags in extra.items():
            for flag in flags:
                scores[sid].add(flag)
    return scores
