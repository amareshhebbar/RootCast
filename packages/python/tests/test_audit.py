"""Causal audit on the samples and the Phase 2 gate on the README."""
import json
import os
import re

import pytest

from rootcast import DecisionGraph, Trace, audit
from rootcast.cli import main, render_audit

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TRACES = os.path.join(ROOT, "examples", "traces")

with open(os.path.join(TRACES, "expected.json"), "r", encoding="utf-8") as fh:
    EXPECTED = json.load(fh)


def _load(name):
    return Trace.load(os.path.join(TRACES, name + ".rootcast.json"))


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_audit_names_the_known_cause(name):
    result = audit(_load(name))
    assert result.failure == EXPECTED[name]["fail"]
    assert result.cause == EXPECTED[name]["cause"]
    assert result.chain[0] == result.cause and result.chain[-1] == result.failure


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_only_cause_and_failure_are_flagged_on_samples(name):
    result = audit(_load(name))
    tags = {s.id: result.tag(s.id) for s in result.trace.steps}
    want = {sid: "pass" for sid in tags}
    want[EXPECTED[name]["cause"]] = "cause"
    want[EXPECTED[name]["fail"]] = "fail"
    assert tags == want


def test_graph_ancestors_and_path():
    graph = DecisionGraph.build(_load("stale_policy"))
    assert graph.ancestors("step4") == ["step1", "step2", "step3"]
    assert graph.path("step2", "step4") == ["step2", "step3", "step4"]
    assert graph.path("step4", "step1") == []


def test_passing_run_has_no_failure_or_cause():
    trace = Trace.from_dict({
        "rootcast_version": "0.1",
        "run_id": "ok",
        "status": "pass",
        "steps": [{"id": "a", "name": "a", "kind": "tool", "output": 1, "status": "pass"}],
    })
    result = audit(trace)
    assert result.failure is None and result.cause is None
    assert render_audit(result) == "run ok  PASS\n\n  a  a  ok\n\n  flags: none"


def test_failure_with_nothing_upstream_blames_itself():
    trace = Trace.from_dict({
        "rootcast_version": "0.1",
        "run_id": "solo",
        "status": "fail",
        "steps": [
            {"id": "a", "name": "fetch", "kind": "tool", "output": {"k": "value-123"}, "status": "pass"},
            {"id": "b", "name": "use", "kind": "tool", "depends_on": ["a"], "status": "fail", "error": "boom"},
        ],
    })
    result = audit(trace)
    assert result.cause == "b" and result.tag("b") == "fail"
    assert result.summary == "use failed and nothing upstream looks wrong"


def test_failed_run_without_a_fail_step_uses_the_last_step():
    trace = Trace.from_dict({
        "rootcast_version": "0.1",
        "run_id": "quiet",
        "status": "fail",
        "steps": [
            {"id": "a", "name": "search", "kind": "tool", "status": "pass"},
            {"id": "b", "name": "answer", "kind": "llm", "depends_on": ["a"], "output": "x", "status": "pass"},
        ],
    })
    result = audit(trace)
    assert result.failure == "b" and result.cause == "a"


def test_audit_json_output(capsys):
    assert main(["audit", os.path.join(TRACES, "tool_args.rootcast.json"), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["cause"] == "step3" and data["chain"] == ["step3", "step4"]
    assert [s["tag"] for s in data["steps"]] == ["pass", "pass", "cause", "fail"]


def test_audit_baseline_flags_anomalies(tmp_path, capsys):
    for i in range(3):
        Trace.from_dict({
            "rootcast_version": "0.1",
            "run_id": "old-" + str(i),
            "status": "pass",
            "steps": [{"id": "step2", "name": "lookup_policy", "kind": "tool", "output": "x" * 2000,
                       "status": "pass", "started_at": 0, "ended_at": 0.2}],
        }).save(str(tmp_path / ("old-" + str(i) + ".rootcast.json")))
    trace = _load("stale_policy")
    trace.get("step2").ended_at = trace.get("step2").started_at + 3
    path = str(tmp_path / "now.rootcast.json")
    trace.save(path)
    assert main(["audit", path, "--baseline", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "step2  info  slow" in out and "took 3s, usual for lookup_policy is 0.2s" in out
    assert "step2  info  small_result" in out
    # The audited run itself is excluded from its own baseline, and anomalies do not change tags.
    assert "step2  lookup_policy  CAUSE" in out


def test_readme_shows_the_real_stale_policy_audit(capsys):
    """Phase 2 gate: the README block is exactly what rootcast audit prints."""
    with open(os.path.join(ROOT, "README.md"), "r", encoding="utf-8") as fh:
        readme = fh.read()
    match = re.search(r"With Rootcast, you read this:\s*```\n(.*?)\n```", readme, re.S)
    assert match, "README audit block not found"
    main(["audit", os.path.join(TRACES, "stale_policy.rootcast.json")])
    assert capsys.readouterr().out.rstrip("\n") == match.group(1).replace("\r\n", "\n")
