from __future__ import annotations

from typing import Any, Iterator, Optional

from .schema import Step, Trace, ref_of

MIN_STRING_LEN = 8
META_KEY = "inferred_depends_on"


def _is_scalar_trivial(value: Any, min_string_len: int) -> bool:
    if value is None or isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return True
    if isinstance(value, str):
        return len(value) < min_string_len
    if isinstance(value, (dict, list)):
        return len(value) == 0
    return False


def _walk(value: Any) -> Iterator[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from _walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk(child)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_empty(value: Any) -> bool:
    return value is None or isinstance(value, bool) or value == {} or value == []


def _nested_hashes(value: Any, min_string_len: int) -> set[str]:
    hashes: set[str] = set()
    for node in _walk(value):
        if node is value:
            continue
        if not _is_scalar_trivial(node, min_string_len):
            hashes.add(ref_of(node))
    return hashes


def _output_hashes(step: Step, blobs: dict[str, Any], min_string_len: int) -> set[str]:
    hashes: set[str] = set()
    if step.output_ref is not None:
        hashes.add(ref_of(step.output_ref))
    value = step.resolved_output(blobs)
    if _is_empty(value):
        return hashes
    hashes.add(ref_of(value))
    hashes |= _nested_hashes(value, min_string_len)
    return hashes


def _finished_before(producer: Step, consumer: Step) -> bool:
    if producer.ended_at is None or consumer.started_at is None:
        return True
    return producer.ended_at <= consumer.started_at


def _children(value: Any) -> list[Any]:
    if isinstance(value, dict):
        return list(value.values())
    if isinstance(value, list):
        return list(value)
    return []


def _match(
    value: Any,
    top: bool,
    produced: list[tuple[Step, set[str]]],
    consumer: Step,
    min_string_len: int,
    found: list[str],
) -> None:
    eligible = not _is_scalar_trivial(value, min_string_len) or (top and _is_number(value))
    if eligible:
        producer = _latest_producer(produced, ref_of(value), consumer)
        if producer is not None:
            if producer.id not in found:
                found.append(producer.id)
            return
    for child in _children(value):
        _match(child, False, produced, consumer, min_string_len, found)


def infer_dependencies(
    trace: Trace,
    only_undeclared: bool = True,
    min_string_len: int = MIN_STRING_LEN,
) -> dict[str, list[str]]:
    produced: list[tuple[Step, set[str]]] = []
    inferred: dict[str, list[str]] = {}
    order = {s.id: i for i, s in enumerate(trace.steps)}
    for step in trace.steps:
        if (not only_undeclared) or not step.depends_on:
            found: list[str] = []
            for value in (step.inputs or {}).values():
                _match(value, True, produced, step, min_string_len, found)
            new_ids = [sid for sid in sorted(found, key=order.__getitem__) if sid not in step.depends_on]
            if new_ids:
                step.depends_on.extend(new_ids)
                step.depends_on.sort(key=lambda sid: order.get(sid, 0))
                inferred[step.id] = new_ids
        produced.append((step, _output_hashes(step, trace.blobs, min_string_len)))
    if inferred:
        existing = trace.meta.get(META_KEY, {})
        if not isinstance(existing, dict):
            existing = {}
        for sid, ids in inferred.items():
            merged = list(existing.get(sid, []))
            for dep in ids:
                if dep not in merged:
                    merged.append(dep)
            existing[sid] = merged
        trace.meta[META_KEY] = existing
    return inferred


def _latest_producer(
    produced: list[tuple[Step, set[str]]], h: str, consumer: Step
) -> Optional[Step]:
    for producer, hashes in reversed(produced):
        if h in hashes and _finished_before(producer, consumer):
            return producer
    return None
