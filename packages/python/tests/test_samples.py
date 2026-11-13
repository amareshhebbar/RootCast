import json
import os
import sys
import tempfile

import pytest

from rootcast import Trace, validate

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EXAMPLES = os.path.join(ROOT, "examples")
TRACES = os.path.join(EXAMPLES, "traces")

with open(os.path.join(TRACES, "expected.json"), "r", encoding="utf-8") as fh:
    EXPECTED = json.load(fh)


def _load(name):
    with open(os.path.join(TRACES, name + ".rootcast.json"), "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_sample_is_valid(name):
    assert validate(_load(name)) == []


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_sample_has_expected_dependencies_and_failure(name):
    trace = Trace.from_dict(_load(name))
    want = EXPECTED[name]
    assert trace.run_id == want["run_id"]
    assert trace.status == "fail"
    assert {s.id: s.depends_on for s in trace.steps} == want["depends_on"]
    assert trace.get(want["fail"]).status == "fail"
    assert trace.get(want["cause"]) is not None


def test_committed_samples_match_regeneration():
    sys.path.insert(0, EXAMPLES)
    try:
        import generate_traces
    finally:
        sys.path.remove(EXAMPLES)
    out = tempfile.mkdtemp()
    generate_traces.generate(out)
    for name in EXPECTED:
        with open(os.path.join(out, name + ".rootcast.json"), "r", encoding="utf-8") as fh:
            fresh = fh.read()
        with open(os.path.join(TRACES, name + ".rootcast.json"), "r", encoding="utf-8") as fh:
            committed = fh.read()
        assert fresh == committed, name + " sample is stale, run python examples/generate_traces.py"
