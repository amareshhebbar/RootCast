from __future__ import annotations

import os
import shutil
from typing import Optional

from ..recorder import Recorder
from ..replay import Agent, load_agent_module
from ..schema import Trace

TRACE_SUFFIX = ".rootcast.json"
BUNDLE_DIR = os.path.dirname(os.path.abspath(__file__))
UI_PATH = os.path.join(BUNDLE_DIR, "ui", "index.html")
TRACES_DIR = os.path.join(BUNDLE_DIR, "traces")
AGENTS_DIR = os.path.join(BUNDLE_DIR, "agents")


def ui_path() -> Optional[str]:
    return UI_PATH if os.path.exists(UI_PATH) else None


def trace_paths() -> list[str]:
    if not os.path.isdir(TRACES_DIR):
        return []
    return [os.path.join(TRACES_DIR, n) for n in sorted(os.listdir(TRACES_DIR)) if n.endswith(TRACE_SUFFIX)]


def agent_paths() -> list[str]:
    if not os.path.isdir(AGENTS_DIR):
        return []
    return [
        os.path.join(AGENTS_DIR, n)
        for n in sorted(os.listdir(AGENTS_DIR))
        if n.endswith(".py") and not n.startswith("_")
    ]


def _step_names(module) -> set[str]:
    built = module.replay_agent(Recorder(run_id="probe", infer=False))
    return set(built.entries if isinstance(built, Agent) else built)


def match_agent(trace: Trace) -> Optional[str]:
    names = {s.name for s in trace.steps}
    for path in agent_paths():
        module = load_agent_module(path)
        if getattr(module, "RUN_ID", None) == trace.run_id and names <= _step_names(module):
            return path
    return None


def write_demo(out_dir: str) -> list[str]:
    os.makedirs(out_dir, exist_ok=True)
    written = []
    for src in trace_paths():
        dst = os.path.join(out_dir, os.path.basename(src))
        shutil.copyfile(src, dst)
        written.append(dst)
    return written
