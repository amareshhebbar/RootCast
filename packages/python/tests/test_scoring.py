"""Unit tests, one block per scoring rule."""
import os

import pytest

from rootcast import Baseline, Trace, score_step, score_trace
from rootcast.scoring import rule_stale

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
TRACES = os.path.join(ROOT, "examples", "traces")


def _trace(*steps, status="fail", blobs=None):
    return Trace.from_dict({
        "rootcast_version": "0.1",
        "run_id": "t",
        "status": status,
        "steps": list(steps),
        "blobs": blobs or {},
    })


def _step(sid, **fields):
    base = {"id": sid, "name": fields.pop("name", sid), "kind": fields.pop("kind", "tool"), "status": "pass"}
    base.update(fields)
    return base


def _rules(score):
    return [(f.rule, f.level) for f in score.flags]


def _score(step, trace=None):
    trace = trace or _trace(step)
    return score_step(trace.steps[-1], trace)


# Clean steps ---------------------------------------------------------------


def test_clean_step_passes_with_no_flags():
    s = _score(_step("a", inputs={"q": "refund window"}, output={"q": "refund window", "days": 30}))
    assert s.status == "pass" and s.flags == []


# step_error -----------------------------------------------------------------


def test_step_error_fails():
    s = _score(_step("a", status="fail", error="TypeError: boom"))
    assert s.status == "fail"
    assert _rules(s) == [("step_error", "fail")]
    assert s.flags[0].message == "TypeError: boom"


def test_error_text_fails_even_if_status_was_left_pass():
    assert _score(_step("a", error="bad value")).status == "fail"


# agent_status ---------------------------------------------------------------


def test_agent_marked_fail_without_error():
    s = _score(_step("a", status="fail", output={"grounded": False}))
    assert _rules(s) == [("agent_status", "fail")]


def test_agent_marked_warn():
    s = _score(_step("a", status="warn", output=1))
    assert s.status == "warn" and _rules(s) == [("agent_status", "warn")]


# empty_result ---------------------------------------------------------------


@pytest.mark.parametrize("output", [None, "", {}, []])
def test_empty_tool_result_warns(output):
    step = _step("a", kind="tool")
    if output is not None:
        step["output"] = output
    assert _rules(_score(step)) == [("empty_result", "warn")]


def test_empty_result_ignores_non_tool_steps_and_blob_outputs():
    assert _score(_step("a", kind="decision")).flags == []
    ref = "sha256:" + "0" * 64
    assert _score(_step("a", output_ref=ref), _trace(_step("a", output_ref=ref), blobs={ref: [1]})).flags == []


# error_result ---------------------------------------------------------------


def test_tool_result_carrying_an_error_warns():
    s = _score(_step("a", output={"error": "rate limited", "items": []}))
    assert _rules(s) == [("error_result", "warn")]
    assert s.flags[0].message == 'result carries an error: "rate limited"'


def test_falsy_error_field_is_fine():
    assert _score(_step("a", output={"error": None, "items": [1]})).flags == []


# type_drift -----------------------------------------------------------------


def test_number_becoming_string_warns():
    s = _score(_step("a", kind="llm", inputs={"account": {"seats": 10}}, output={"args": {"seats": "25 seats"}}))
    assert _rules(s) == [("type_drift", "warn")]
    assert s.flags[0].message == 'seats changed from number to string ("25 seats")'


def test_int_and_float_are_the_same_type():
    assert _score(_step("a", kind="llm", inputs={"amount": 129}, output={"amount": 129.5})).flags == []


def test_type_drift_reads_blob_outputs():
    ref = "sha256:" + "1" * 64
    step = _step("a", kind="llm", inputs={"n": 1}, output_ref=ref)
    assert _rules(_score(step, _trace(step, blobs={ref: {"n": "one"}}))) == [("type_drift", "warn")]


# mismatch -------------------------------------------------------------------


def test_tool_answering_a_different_value_warns():
    s = _score(_step(
        "a",
        inputs={"intent": {"audience": "pediatric"}},
        output={"docs": [{"audience": "adult", "text": "x"}]},
    ))
    assert _rules(s) == [("mismatch", "warn")]
    assert s.flags[0].message == "asked audience=pediatric, got audience=adult"


def test_mismatch_passes_when_any_answer_matches():
    out = {"docs": [{"audience": "adult"}, {"audience": "pediatric"}]}
    assert _score(_step("a", inputs={"audience": "pediatric"}, output=out)).flags == []


def test_mismatch_skips_llm_and_decision_steps_which_may_change_values():
    for kind in ("llm", "decision"):
        assert _score(_step("a", kind=kind, inputs={"plan": "basic"}, output={"plan": "pro"})).flags == []


def test_mismatch_skips_long_free_text():
    long_a, long_b = "a" * 100, "b" * 100
    assert _score(_step("a", inputs={"text": long_a}, output={"text": long_b})).flags == []


# stale ----------------------------------------------------------------------


def test_older_year_fed_next_to_newer_year_is_stale():
    trace = _trace(
        _step("s1", name="read_order", output={"year": 2026}),
        _step("s2", name="lookup_policy", output={"policy": {"effective_date": "2024-01-01"}}),
        _step("s3", kind="decision", depends_on=["s1", "s2"], output=True),
    )
    flags = rule_stale(trace)
    assert list(flags) == ["s2"]
    assert flags["s2"][0].message == "returned 2024 data, read_order is 2026"


def test_same_year_or_single_dated_producer_is_not_stale():
    same = _trace(
        _step("s1", output={"year": 2026}),
        _step("s2", output={"fiscal_year": 2026}),
        _step("s3", depends_on=["s1", "s2"]),
    )
    single = _trace(_step("s1", output={"year": 2024}), _step("s2", depends_on=["s1"]))
    assert rule_stale(same) == {} and rule_stale(single) == {}


def test_numbers_outside_the_year_range_are_ignored():
    trace = _trace(
        _step("s1", output={"year": 26}),
        _step("s2", output={"year": 2026}),
        _step("s3", depends_on=["s1", "s2"]),
    )
    assert rule_stale(trace) == {}


# anomalies ------------------------------------------------------------------


def _timed(sid, start, end, **fields):
    return _step(sid, started_at=start, ended_at=end, **fields)


def test_step_far_slower_than_the_run_is_flagged_but_still_passes():
    trace = _trace(
        _timed("a", 0, 1, output=1),
        _timed("b", 1, 2, output=1),
        _timed("c", 2, 3, output=1),
        _timed("d", 3, 15, output=1),
        status="pass",
    )
    scores = score_trace(trace)
    assert _rules(scores["d"]) == [("slow", "info")]
    assert scores["d"].status == "pass"
    assert scores["d"].flags[0].message == "took 12s, the run median is 1s"


def test_short_steps_are_never_slow():
    trace = _trace(*[_timed(c, 0, 0.01, output=1) for c in "abc"], _timed("d", 0, 0.5, output=1), status="pass")
    assert all(s.flags == [] for s in score_trace(trace).values())


def _history(n, name="search", seconds=1.0, size_items=10):
    runs = []
    for i in range(n):
        runs.append(_trace(_timed("s1", 0, seconds, name=name, output=list(range(size_items)))))
    return Baseline.from_traces(runs)


def test_slower_than_usual_uses_the_baseline():
    base = _history(3, seconds=1.0)
    trace = _trace(_timed("s1", 0, 8, name="search", output=list(range(10))), status="pass")
    assert score_trace(trace, base)["s1"].flags[0].message == "took 8s, usual for search is 1s"


def test_result_far_larger_or_smaller_than_usual():
    base = _history(3, size_items=100)
    big = _trace(_timed("s1", 0, 1, name="search", output=list(range(5000))), status="pass")
    small = _trace(_timed("s1", 0, 1, name="search", output=[1]), status="pass")
    assert _rules(score_trace(big, base)["s1"]) == [("large_result", "info")]
    assert _rules(score_trace(small, base)["s1"]) == [("small_result", "info")]


def test_baseline_needs_enough_samples():
    base = _history(2, size_items=100)
    small = _trace(_timed("s1", 0, 1, name="search", output=[1]), status="pass")
    assert score_trace(small, base)["s1"].flags == []


# Samples --------------------------------------------------------------------


def test_stale_policy_sample_step2_warn_step4_fail():
    trace = Trace.load(os.path.join(TRACES, "stale_policy.rootcast.json"))
    scores = score_trace(trace)
    assert {sid: s.status for sid, s in scores.items()} == {
        "step1": "pass",
        "step2": "warn",
        "step3": "pass",
        "step4": "fail",
    }
    assert _rules(scores["step2"]) == [("stale", "warn")]
