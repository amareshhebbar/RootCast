import asyncio

import pytest

from rootcast import Recorder, current_step, validate


def _clock():
    t = [0.0]

    def tick():
        t[0] += 1.0
        return t[0]

    return tick


def test_decorator_records_inputs_output_and_status():
    rec = Recorder(run_id="d", clock=_clock())

    @rec.record(kind="tool")
    def get_order(order_id, region="eu"):
        return {"id": order_id, "region": region}

    assert get_order(7) == {"id": 7, "region": "eu"}
    step = rec.trace.steps[0]
    assert step.name == "get_order"
    assert step.kind == "tool"
    assert step.inputs == {"order_id": 7, "region": "eu"}
    assert step.output == {"id": 7, "region": "eu"}
    assert step.status == "pass"
    assert step.started_at == 1.0 and step.ended_at == 2.0


def test_bare_decorator_and_custom_name():
    rec = Recorder(run_id="d")

    @rec.record
    def plain(x):
        return x * 2

    @rec.record(name="renamed", kind="llm")
    def other(y):
        return y

    plain(2)
    other(3)
    assert [s.name for s in rec.trace.steps] == ["plain", "renamed"]
    assert rec.trace.steps[0].kind == "custom"
    assert rec.trace.steps[1].kind == "llm"


def test_decorator_preserves_function_metadata():
    rec = Recorder(run_id="d")

    @rec.record(kind="tool")
    def documented(a):
        return a

    assert documented.__name__ == "documented"


def test_decorator_exception_marks_fail_and_reraises():
    rec = Recorder(run_id="d")

    @rec.record(kind="tool")
    def boom(seats):
        raise TypeError("seats must be int")

    with pytest.raises(TypeError):
        boom("25 seats")
    step = rec.trace.steps[0]
    assert step.status == "fail"
    assert "seats must be int" in step.error
    assert step.ended_at is not None
    assert rec.finalize().status == "fail"


def test_methods_skip_self_and_kwargs_flatten():
    rec = Recorder(run_id="d")

    class Agent:
        @rec.record(kind="decision")
        def act(self, goal, **opts):
            return goal

    Agent().act("ship", retries=2)
    assert rec.trace.steps[0].inputs == {"goal": "ship", "retries": 2}


def test_capture_inputs_off_and_exclude():
    rec = Recorder(run_id="d")

    @rec.record(capture_inputs=False)
    def secret(token):
        return 1

    @rec.record(exclude=("api_key",))
    def call(query, api_key):
        return query

    secret("abc")
    call("q", "k")
    assert rec.trace.steps[0].inputs is None
    assert rec.trace.steps[1].inputs == {"query": "q"}


def test_async_decorator():
    rec = Recorder(run_id="a")

    @rec.record(kind="llm")
    async def complete(prompt):
        await asyncio.sleep(0)
        return {"text": prompt.upper()}

    assert asyncio.run(complete("hi")) == {"text": "HI"}
    step = rec.trace.steps[0]
    assert step.inputs == {"prompt": "hi"}
    assert step.output == {"text": "HI"}
    assert step.status == "pass"


def test_current_step_inside_decorator_and_context_manager():
    rec = Recorder(run_id="c")

    @rec.record(kind="tool")
    def check(v):
        current_step().status("fail")
        current_step().error("bad value")
        return v

    check(1)
    with rec.step("manual") as s:
        assert current_step() is s
    assert current_step() is None
    assert rec.trace.steps[0].status == "fail"
    assert rec.trace.steps[0].error == "bad value"
    assert rec.trace.steps[1].status == "pass"


def test_recorded_values_are_snapshots():
    rec = Recorder(run_id="s")

    @rec.record(kind="tool")
    def produce(seed):
        return {"items": [seed]}

    data = {"k": [1]}
    out = produce(data)
    out["items"].append("mutated")
    data["k"].append(2)
    assert rec.trace.steps[0].inputs == {"seed": {"k": [1]}}
    assert rec.trace.steps[0].output == {"items": [{"k": [1]}]}


def test_two_line_change_infers_dependencies():
    rec = Recorder(run_id="two")

    @rec.record(kind="tool")
    def read_order(order_id):
        return {"id": order_id, "year": 2026}

    @rec.record(kind="decision")
    def decide(order):
        return {"ok": order["year"] == 2026}

    decide(read_order(4417))
    data = rec.finalize().to_dict()
    assert data["steps"][1]["depends_on"] == ["step1"]
    assert validate(data) == []
