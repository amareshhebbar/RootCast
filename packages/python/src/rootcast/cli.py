from __future__ import annotations

import argparse
import json
import sys

from .schema import Trace, validate

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


def cmd_audit(args) -> int:
    trace = Trace.load(args.path)
    print(_render(trace))
    print("")
    print("audit: causal engine arrives in v0.2")
    return 0


def cmd_replay(args) -> int:
    print("replay: counterfactual engine arrives in v0.3")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="rootcast")
    sub = parser.add_subparsers(dest="command", required=True)

    p_view = sub.add_parser("view")
    p_view.add_argument("path")
    p_view.set_defaults(func=cmd_view)

    p_val = sub.add_parser("validate")
    p_val.add_argument("path")
    p_val.set_defaults(func=cmd_validate)

    p_audit = sub.add_parser("audit")
    p_audit.add_argument("path")
    p_audit.set_defaults(func=cmd_audit)

    p_replay = sub.add_parser("replay")
    p_replay.add_argument("run_id")
    p_replay.add_argument("--set", action="append", default=[])
    p_replay.set_defaults(func=cmd_replay)

    return parser


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
