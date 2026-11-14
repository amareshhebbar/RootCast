from __future__ import annotations

import argparse
import json
import os
import sys

from .causal import CAUSE, AuditResult, audit
from .replay import ReplayError, load_agent_module, parse_set, render_replay, replay
from .schema import TRACE_SUFFIX, Trace, trace_path, validate
from .scoring import Baseline

STATUS_TAG = {"pass": "ok", "warn": "WARN", "fail": "FAIL", "unknown": "..", "cause": "CAUSE"}


def _render(trace: Trace) -> str:
    lines = []
    header = "run " + trace.run_id + "  " + trace.status.upper()
    lines.append(header)
    lines.append("")
    for step in trace.steps:
        tag = STATUS_TAG.get(step.status, step.status)
        label = "  " + step.id.ljust(8) + step.name.ljust(22) + tag
        lines.append(label)
        if step.error:
            lines.append("           error: " + step.error)
    return "\n".join(lines)


def cmd_view(args) -> int:
    trace = Trace.load(args.path)
    print(_render(trace))
    return 0


def cmd_validate(args) -> int:
    with open(args.path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    errors = validate(data)
    if errors:
        for e in errors:
            print("invalid: " + e)
        return 1
    print("valid")
    return 0


TAGS = {"pass": "ok", "warn": "WARN", "fail": "FAIL", CAUSE: "CAUSE"}
LEVELS = {"info": "info", "warn": "WARN", "fail": "FAIL"}


def render_audit(result: AuditResult) -> str:
    trace = result.trace
    header = "run " + trace.run_id + "  " + trace.status.upper()
    if result.failure is not None:
        problems = result.scores[result.failure].problems
        if problems:
            header += "  " + problems[0].message
    lines = [header, ""]

    id_w = max(len(s.id) for s in trace.steps) + 2 if trace.steps else 0
    name_w = max(len(s.name) for s in trace.steps) + 2 if trace.steps else 0
    tag_w = max(len(TAGS[result.tag(s.id)]) for s in trace.steps) + 2 if trace.steps else 0
    for step in trace.steps:
        tag = TAGS[result.tag(step.id)]
        row = "  " + step.id.ljust(id_w) + step.name.ljust(name_w)
        problems = result.scores[step.id].problems
        if problems:
            row += tag.ljust(tag_w) + problems[0].message
        else:
            row += tag
        lines.append(row)

    if result.failure is not None:
        lines.append("")
        lines.append("  earliest divergence: " + result.cause)
        lines.append("  chain: " + " -> ".join(result.chain))
        lines.append("  cause: " + result.summary)

    flags = [(s, f) for s in trace.steps for f in result.scores[s.id].flags]
    lines.append("")
    if not flags:
        lines.append("  flags: none")
    else:
        lines.append("  flags:")
        rule_w = max(len(f.rule) for _, f in flags) + 2
        for step, flag in flags:
            lines.append(
                "    " + step.id.ljust(id_w) + LEVELS[flag.level].ljust(6) + flag.rule.ljust(rule_w) + flag.message
            )
    return "\n".join(lines)


def _baseline_traces(paths, exclude_run_id):
    files = []
    for path in paths:
        if os.path.isdir(path):
            files.extend(
                os.path.join(path, name) for name in sorted(os.listdir(path)) if name.endswith(TRACE_SUFFIX)
            )
        else:
            files.append(path)
    traces = []
    for f in files:
        trace = Trace.load(f)
        if trace.run_id != exclude_run_id:
            traces.append(trace)
    return traces


def cmd_audit(args) -> int:
    trace = Trace.load(args.path)
    baseline = None
    if args.baseline:
        baseline = Baseline.from_traces(_baseline_traces(args.baseline, trace.run_id))
    result = audit(trace, baseline)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_audit(result))
    return 0


def _resolve_trace(ref: str) -> str:
    """A trace file path, or a run id looked up in the trace store."""
    if os.path.exists(ref):
        return ref
    path = trace_path(ref)
    if os.path.exists(path):
        return path
    raise ReplayError("no trace file or stored run named " + ref)


def cmd_replay(args) -> int:
    try:
        trace = Trace.load(_resolve_trace(args.run))
        factory, named = None, {}
        if args.agent:
            module = load_agent_module(args.agent)
            factory = module.replay_agent
            named = getattr(module, "REPLAY_VALUES", {})
        injections = [parse_set(spec, trace, named) for spec in args.set]
        result = replay(trace, injections, factory)
    except ReplayError as exc:
        print("replay: " + str(exc), file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        print(render_replay(result))
    return 0


def build_parser() -> argparse.ArgumentParser:
    from . import __version__

    parser = argparse.ArgumentParser(prog="rootcast")
    parser.add_argument("--version", action="version", version="rootcast " + __version__)
    sub = parser.add_subparsers(dest="command", required=True)

    p_view = sub.add_parser("view")
    p_view.add_argument("path")
    p_view.set_defaults(func=cmd_view)

    p_val = sub.add_parser("validate")
    p_val.add_argument("path")
    p_val.set_defaults(func=cmd_validate)

    p_audit = sub.add_parser("audit")
    p_audit.add_argument("path")
    p_audit.add_argument(
        "--baseline",
        action="append",
        default=[],
        metavar="PATH",
        help="earlier traces (files or folders) that define usual durations and sizes",
    )
    p_audit.add_argument("--json", action="store_true", help="print the audit as JSON")
    p_audit.set_defaults(func=cmd_audit)

    p_replay = sub.add_parser("replay")
    p_replay.add_argument("run", help="trace file, or a run id in the trace store")
    p_replay.add_argument(
        "--set",
        action="append",
        default=[],
        metavar="STEP.output[.path]=VALUE",
        help="value to inject; repeat for several. VALUE is JSON, a REPLAY_VALUES name, @file.json or text",
    )
    p_replay.add_argument("--agent", metavar="FILE.py", help="agent module defining replay_agent(rec)")
    p_replay.add_argument("--json", action="store_true", help="print the replay result as JSON")
    p_replay.set_defaults(func=cmd_replay)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
