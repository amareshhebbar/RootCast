import json
import os
import subprocess
import sys

from rootcast import Trace, bundle
from rootcast.cli import main

PKG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_bundle_matches_repo_sources():
    proc = subprocess.run(
        [sys.executable, os.path.join(PKG_DIR, "scripts", "sync_bundle.py"), "--check"],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stdout + " run python packages/python/scripts/sync_bundle.py"


def test_bundle_has_ui_samples_and_agents():
    assert bundle.ui_path() is not None
    names = sorted(os.path.basename(p) for p in bundle.trace_paths())
    assert names == ["rag_lookup.rootcast.json", "stale_policy.rootcast.json", "tool_args.rootcast.json"]
    assert sorted(os.path.basename(p) for p in bundle.agent_paths()) == ["rag_lookup.py", "stale_policy.py", "tool_args.py"]


def test_match_agent_by_run_and_steps():
    for path in bundle.trace_paths():
        trace = Trace.load(path)
        agent = bundle.match_agent(trace)
        assert agent is not None
        assert os.path.basename(agent).split(".")[0] == os.path.basename(path).split(".")[0]


def test_match_agent_rejects_unknown_run():
    trace = Trace.from_dict({"rootcast_version": "0.1", "run_id": "other", "status": "fail",
                             "steps": [{"id": "step1", "name": "read_order", "kind": "tool"}]})
    assert bundle.match_agent(trace) is None


def test_demo_then_replay_without_agent_flag(tmp_path, capsys):
    out = tmp_path / "demo"
    assert main(["demo", str(out)]) == 0
    sample = out / "stale_policy.rootcast.json"
    assert sample.exists()
    capsys.readouterr()
    assert main(["replay", str(sample), "--set", "step2.output=policy_2026", "--json"]) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["status"]["before"] == "fail"
    assert result["status"]["after"] == "pass"
