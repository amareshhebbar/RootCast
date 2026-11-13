from rootcast import Recorder, Trace, infer_dependencies, validate


def _trace(steps):
    return Trace.from_dict({"rootcast_version": "0.1", "run_id": "t", "status": "fail", "steps": steps})


def test_whole_output_feeds_input():
    t = _trace([
        {"id": "a", "name": "a", "kind": "tool", "output": {"order": 4417, "year": 2026}},
        {"id": "b", "name": "b", "kind": "decision", "inputs": {"order": {"order": 4417, "year": 2026}}},
    ])
    assert infer_dependencies(t) == {"b": ["a"]}
    assert t.get("b").depends_on == ["a"]
    assert t.meta["inferred_depends_on"] == {"b": ["a"]}


def test_nested_output_value_feeds_input():
    t = _trace([
        {"id": "a", "name": "a", "kind": "tool", "output": {"docs": [{"id": "doc_pediatric"}], "n": 1}},
        {"id": "b", "name": "b", "kind": "llm", "inputs": {"docs": [{"id": "doc_pediatric"}]}},
    ])
    infer_dependencies(t)
    assert t.get("b").depends_on == ["a"]


def test_value_nested_inside_input_matches():
    t = _trace([
        {"id": "a", "name": "a", "kind": "tool", "output": {"customer": "acme-corp-eu"}},
        {"id": "b", "name": "b", "kind": "tool", "inputs": {"payload": {"who": "acme-corp-eu", "x": 1}}},
    ])
    infer_dependencies(t)
    assert t.get("b").depends_on == ["a"]


def test_trivial_values_do_not_link():
    t = _trace([
        {"id": "a", "name": "a", "kind": "tool", "output": {"ok": True, "n": 3, "tag": "pro"}},
        {"id": "b", "name": "b", "kind": "tool", "inputs": {"ok": True, "n": 3, "tag": "pro"}},
    ])
    assert infer_dependencies(t) == {}
    assert t.get("b").depends_on == []


def test_whole_number_output_links_top_level_number():
    t = _trace([
        {"id": "a", "name": "count", "kind": "tool", "output": 42},
        {"id": "b", "name": "use", "kind": "tool", "inputs": {"n": 42}},
    ])
    infer_dependencies(t)
    assert t.get("b").depends_on == ["a"]


def test_container_consumed_whole_does_not_descend():
    t = _trace([
        {"id": "a", "name": "intent", "kind": "llm", "output": {"topic": "drug_x_max_dose", "aud": "kids"}},
        {"id": "b", "name": "retrieve", "kind": "tool", "output": {"topic": "drug_x_max_dose"}},
        {"id": "c", "name": "check", "kind": "decision", "inputs": {"intent": {"topic": "drug_x_max_dose", "aud": "kids"}}},
    ])
    infer_dependencies(t)
    assert t.get("c").depends_on == ["a"]


def test_latest_producer_wins():
    t = _trace([
        {"id": "a", "name": "a", "kind": "tool", "output": "same-long-value"},
        {"id": "b", "name": "b", "kind": "tool", "output": "same-long-value"},
        {"id": "c", "name": "c", "kind": "tool", "inputs": {"v": "same-long-value"}},
    ])
    infer_dependencies(t)
    assert t.get("c").depends_on == ["b"]


def test_declared_dependencies_are_kept():
    t = _trace([
        {"id": "a", "name": "a", "kind": "tool", "output": {"k": "value-from-a"}},
        {"id": "b", "name": "b", "kind": "tool", "output": {"k": "value-from-b"}},
        {"id": "c", "name": "c", "kind": "tool", "inputs": {"v": "value-from-a"}, "depends_on": ["b"]},
    ])
    assert infer_dependencies(t) == {}
    assert t.get("c").depends_on == ["b"]
    infer_dependencies(t, only_undeclared=False)
    assert t.get("c").depends_on == ["a", "b"]


def test_producer_must_finish_before_consumer_starts():
    t = _trace([
        {"id": "a", "name": "outer", "kind": "tool", "output": {"k": "shared-value"}, "started_at": 0.0, "ended_at": 5.0},
        {"id": "b", "name": "inner", "kind": "tool", "inputs": {"k": "shared-value"}, "started_at": 1.0, "ended_at": 2.0},
    ])
    assert infer_dependencies(t) == {}


def test_referenced_blob_output_links():
    rec = Recorder(run_id="big")
    with rec.step("fetch", kind="tool") as s:
        s.output({"blob": "x" * 5000})
    big = {"blob": "x" * 5000}
    with rec.step("summarize", kind="llm", inputs={"doc": big}) as s:
        s.output("short")
    rec.finalize()
    assert rec.trace.steps[1].depends_on == ["step1"]
    assert validate(rec.trace.to_dict()) == []


def test_output_ref_string_links():
    rec = Recorder(run_id="refs")
    with rec.step("fetch", kind="tool") as s:
        s.output({"blob": "y" * 5000})
    ref = rec.trace.steps[0].output_ref
    with rec.step("use", kind="tool", inputs={"ref": ref}):
        pass
    rec.finalize()
    assert rec.trace.steps[1].depends_on == ["step1"]


def test_inference_is_idempotent():
    t = _trace([
        {"id": "a", "name": "a", "kind": "tool", "output": {"k": "value-long"}},
        {"id": "b", "name": "b", "kind": "tool", "inputs": {"v": "value-long"}},
    ])
    infer_dependencies(t)
    assert infer_dependencies(t) == {}
    assert t.get("b").depends_on == ["a"]
    assert t.meta["inferred_depends_on"] == {"b": ["a"]}
