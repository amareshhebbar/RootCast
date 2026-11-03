import json
import os
import tempfile

from rootcast import Recorder, Trace, validate


def test_recorder_builds_valid_trace():
    rec = Recorder(run_id="demo", meta={"framework": "generic"})
    with rec.step("read_order", kind="tool") as s:
        s.output({"order": 4417})
    with rec.step("lookup_policy", kind="tool", depends_on=["step1"]) as s:
        s.input({"query": "refund window"})
        s.output({"window_days": 90})
    rec.mark("fail")

    data = rec.trace.to_dict()
    assert data["rootcast_version"] == "0.1"
    assert data["run_id"] == "demo"
    assert len(data["steps"]) == 2
    assert data["steps"][1]["depends_on"] == ["step1"]
    assert validate(data) == []


def test_large_output_is_referenced():
    rec = Recorder(run_id="big")
    with rec.step("fetch", kind="tool") as s:
        s.output({"blob": "x" * 5000})
    step = rec.trace.steps[0]
    assert step.output is None
    assert step.output_ref is not None
    assert step.output_ref in rec.trace.blobs


def test_save_and_load_roundtrip():
    rec = Recorder(run_id="rt")
    with rec.step("a", kind="io") as s:
        s.output(1)
    path = os.path.join(tempfile.mkdtemp(), "rt.rootcast.json")
    rec.save(path)
    loaded = Trace.load(path)
    assert loaded.run_id == "rt"
    assert loaded.status == "pass"
    assert validate(json.loads(open(path).read())) == []


def test_exception_marks_step_fail():
    rec = Recorder(run_id="err")
    try:
        with rec.step("boom", kind="tool"):
            raise ValueError("bad tool")
    except ValueError:
        pass
    assert rec.trace.steps[0].status == "fail"
    assert "bad tool" in rec.trace.steps[0].error
