"""Replay executor, outcome diff, external call handling and the replay result."""
import json
import os
import re

import pytest

from rootcast import Agent, ExternalCallError, Recorder, ReplayError, Trace, parse_set, replay
from rootcast.cli import main
from rootcast.replay import diff_values, load_agent_module

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EXAMPLES = os.path.join(ROOT, "examples")
TRACES = os.path.join(EXAMPLES, "traces")
SCENARIOS = os.path.join(EXAMPLES, "scenarios")


def _sample(name):
    trace = Trace.load(os.path.join(TRACES, name + ".rootcast.json"))
    module = load_agent_module(os.path.join(SCENARIOS, name + ".py"))
    return trace, module


def _replay(name, *specs):
    trace, module = _sample(name)
    injections = [parse_set(s, trace, module.REPLAY_VALUES) for s in specs]
    return replay(trace, injections, module.replay_agent)


# Phase 3 gate ---------------------------------------------------------------


def test_stale_policy_fix_changes_only_downstream_and_flips_to_pass():
    result = _replay("stale_policy", "step2.output=policy_2026")
    changes = {d.step_id: d.change for d in result.steps}
    assert changes == {"step1": "unchanged", "step2": "injected", "step3": "recomputed", "step4": "recomputed"}

    # Upstream untouched.
    step1 = result.get("step1")
    assert not step1.changed and step1.inputs == [] and step1.output == []

    # The injected cause changed its output, not its inputs.
    step2 = result.get("step2")
    assert step2.inputs == []
    assert {c.path for c in step2.output} == {"source", "window_days", "year"}

    # The decision fed by the cause sees new inputs and decides differently.
    step3 = result.get("step3")
    assert {c.path for c in step3.inputs} == {"policy.source", "policy.window_days", "policy.year"}
    assert [(c.before, c.after) for c in step3.output if c.path == "allowed"] == [(True, False)]

    step4 = result.get("step4")
    assert (step4.status_before, step4.status_after) == ("fail", "pass")
    assert step4.error_after is None

    assert result.changed_steps == ["step2", "step3", "step4"]
    assert (result.status_before, result.status_after, result.flipped) == ("fail", "pass", True)


def test_unrelated_change_does_not_flip_the_outcome():
    result = _replay("stale_policy", "step1.output.amount=130")
    assert result.flipped is False and result.status_after == "fail"
    assert not result.get("step2").changed
    assert result.get("step4").status_after == "fail"


def test_rag_fix_flips_to_pass():
    result = _replay("rag_lookup", "step2.output=pediatric_docs")
    assert result.flipped and result.changed_steps == ["step2", "step3", "step4"]
    answer = [c for c in result.get("step3").output if c.path == "answer"][0]
    assert answer.after == "The maximum single dose is 200 mg."


# External calls ---------------------------------------------------------------


def test_external_call_requires_an_injected_value():
    with pytest.raises(ExternalCallError) as err:
        _replay("tool_args", "step3.output=fixed_plan")
    assert err.value.step_id == "step4"
    assert "--set step4.output=VALUE" in str(err.value)


def test_external_call_with_injected_value_replays():
    result = _replay("tool_args", "step3.output=fixed_plan", "step4.output=updated")
    assert [d.change for d in result.steps] == ["unchanged", "unchanged", "injected", "injected"]
    assert result.get("step4").error_before == "TypeError: seats must be an integer, got str"
    assert result.get("step4").error_after is None
    assert result.flipped


def test_external_step_with_unchanged_inputs_is_served_from_the_recording():
    calls = []

    def factory(rec):
        agent = Agent()
        agent.add(rec.record(lambda **kw: calls.append(kw)), name="read_order")
        return agent

    trace, _ = _sample("stale_policy")
    replay(trace, [parse_set("step4.output={}", trace)], factory)
    assert calls == []


def test_llm_steps_are_external_by_default():
    trace = Trace.from_dict({
        "rootcast_version": "0.1",
        "run_id": "llm",
        "status": "fail",
        "steps": [
            {"id": "s1", "name": "fetch", "kind": "tool", "output": {"doc": "the-old-document"}, "status": "pass"},
            {"id": "s2", "name": "summarize", "kind": "llm", "inputs": {"doc": "the-old-document"},
             "depends_on": ["s1"], "output": "x", "status": "fail", "error": "bad"},
        ],
    })

    def factory(rec):
        return {"summarize": rec.record(lambda doc: "y", name="summarize", kind="llm")}

    with pytest.raises(ExternalCallError):
        replay(trace, [parse_set('s1.output={"doc":"the-new-document"}', trace)], factory)


def test_recompute_without_an_agent_is_an_error():
    trace, _ = _sample("stale_policy")
    with pytest.raises(ReplayError, match="--agent"):
        replay(trace, [parse_set("step2.output=1", trace)])


# Injection parsing ------------------------------------------------------------


def test_parse_set_forms(tmp_path):
    trace, module = _sample("stale_policy")
    named = module.REPLAY_VALUES
    assert parse_set("step2.output=policy_2026", trace, named).value["year"] == 2026
    assert parse_set("lookup_policy.result=7", trace).step_id == "step2"
    inj = parse_set("step2.output.window_days=30", trace)
    assert (inj.target, inj.path, inj.value) == ("output", ["window_days"], 30)
    assert parse_set("step2.inputs.query=plain text", trace).value == "plain text"
    f = tmp_path / "v.json"
    f.write_text('{"a": 1}', encoding="utf-8")
    assert parse_set("step2.output=@" + str(f), trace).value == {"a": 1}
    for bad in ("step2.output", "step2=1", "step9.output=1", "step2.status=1", "step2.inputs=1"):
        with pytest.raises(ReplayError):
            parse_set(bad, trace)


def test_bad_output_path_is_an_error():
    trace, module = _sample("stale_policy")
    with pytest.raises(ReplayError, match="does not exist"):
        replay(trace, [parse_set("step2.output.missing.deep=1", trace)], module.replay_agent)


# Diff -------------------------------------------------------------------------


def test_diff_values_reports_leaves_added_and_removed_keys():
    before = {"a": 1, "b": {"c": [1, 2]}, "gone": True}
    after = {"a": 1, "b": {"c": [1, 3]}, "new": "x"}
    got = [(c.path, c.before, c.after) for c in diff_values(before, after)]
    assert got == [("b.c[1]", 2, 3), ("gone", True, None), ("new", None, "x")]
    assert diff_values([1], [1, 2]) [0].path == ""
    assert diff_values({"n": 1}, {"n": 1.0}) == []


# Replay result object -----------------------------------------------------------


def test_result_to_dict_is_json_ready_for_the_ui():
    data = _replay("stale_policy", "step2.output=policy_2026").to_dict()
    json.dumps(data)
    assert data["status"] == {"before": "fail", "after": "pass", "flipped": True}
    assert data["changed_steps"] == ["step2", "step3", "step4"]
    assert data["steps"][3]["status"] == {"before": "fail", "after": "pass"}
    assert data["injections"][0]["spec"] == "step2.output=policy_2026"
    assert data["replayed_trace"]["status"] == "pass"
    assert data["replayed_trace"]["meta"]["replay_of"] == "refund-7af3"


def test_replayed_trace_is_schema_valid():
    from rootcast import validate

    result = _replay("stale_policy", "step2.output=policy_2026")
    assert validate(result.replayed.to_dict()) == []


# CLI ----------------------------------------------------------------------------


def test_cli_json_and_error_exit(capsys):
    path = os.path.join(TRACES, "tool_args.rootcast.json")
    agent = os.path.join(SCENARIOS, "tool_args.py")
    assert main(["replay", path, "--agent", agent, "--set", "step3.output=fixed_plan"]) == 2
    assert "external tool call" in capsys.readouterr().err
    assert main(["replay", path, "--agent", agent, "--set", "step3.output=fixed_plan",
                 "--set", "step4.output=updated", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["status"]["flipped"] is True


def test_cli_resolves_a_run_id_from_the_store(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("ROOTCAST_DIR", str(tmp_path))
    Trace.load(os.path.join(TRACES, "stale_policy.rootcast.json")).save()
    agent = os.path.join(SCENARIOS, "stale_policy.py")
    assert main(["replay", "refund-7af3", "--agent", agent, "--set", "step2.output=policy_2026"]) == 0
    assert "run: FAIL -> PASS  (flipped)" in capsys.readouterr().out


def test_readme_replay_block_is_real(capsys, monkeypatch):
    """Phase 3 gate: the README replay block reproduces from the committed sample."""
    with open(os.path.join(ROOT, "README.md"), "r", encoding="utf-8") as fh:
        readme = fh.read()
    match = re.search(r"Then prove it:\s*```\n\$ (rootcast replay [^\n]+)\n(.*?)\n```", readme, re.S)
    assert match, "README replay block not found"
    command, expected = match.group(1), match.group(2).replace("\r\n", "\n")
    monkeypatch.chdir(ROOT)
    main(command.split()[1:])
    assert capsys.readouterr().out.rstrip("\n") == expected
