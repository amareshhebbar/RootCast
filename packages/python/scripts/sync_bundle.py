from __future__ import annotations

import argparse
import filecmp
import os
import shutil
import sys

PKG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO_DIR = os.path.abspath(os.path.join(PKG_DIR, "..", ".."))
BUNDLE = os.path.join(PKG_DIR, "src", "rootcast", "bundle")
TRACE_SUFFIX = ".rootcast.json"


def pairs() -> list[tuple[str, str]]:
    out = [(os.path.join(REPO_DIR, "ui", "index.html"), os.path.join(BUNDLE, "ui", "index.html"))]
    traces = os.path.join(REPO_DIR, "examples", "traces")
    for name in sorted(os.listdir(traces)):
        if name.endswith(TRACE_SUFFIX):
            out.append((os.path.join(traces, name), os.path.join(BUNDLE, "traces", name)))
    scenarios = os.path.join(REPO_DIR, "examples", "scenarios")
    for name in sorted(os.listdir(scenarios)):
        if name.endswith(".py") and not name.startswith("_"):
            out.append((os.path.join(scenarios, name), os.path.join(BUNDLE, "agents", name)))
    return out


def stale() -> list[str]:
    bad = []
    expected = {dst for _, dst in pairs()}
    for src, dst in pairs():
        if not os.path.exists(dst) or not filecmp.cmp(src, dst, shallow=False):
            bad.append(os.path.relpath(dst, PKG_DIR))
    for sub in ("ui", "traces", "agents"):
        folder = os.path.join(BUNDLE, sub)
        if os.path.isdir(folder):
            for name in os.listdir(folder):
                path = os.path.join(folder, name)
                if os.path.isfile(path) and path not in expected:
                    bad.append(os.path.relpath(path, PKG_DIR) + " (not in the repo)")
    return bad


def sync() -> None:
    for sub in ("ui", "traces", "agents"):
        shutil.rmtree(os.path.join(BUNDLE, sub), ignore_errors=True)
    for src, dst in pairs():
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copyfile(src, dst)
        print("synced " + os.path.relpath(dst, PKG_DIR))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="sync_bundle")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        bad = stale()
        for path in bad:
            print("out of sync: " + path)
        return 1 if bad else 0
    sync()
    return 0


if __name__ == "__main__":
    sys.exit(main())
