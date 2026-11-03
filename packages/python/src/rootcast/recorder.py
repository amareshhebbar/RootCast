from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any, Optional

from .schema import Trace, Step, ref_of, INLINE_LIMIT_BYTES


class StepHandle:
    def __init__(self, step: Step, trace: Trace):
        self._step = step
        self._trace = trace

    def input(self, data: dict) -> None:
        self._step.inputs = data

    def depends_on(self, *ids: str) -> None:
        for sid in ids:
            if sid not in self._step.depends_on:
                self._step.depends_on.append(sid)

    def output(self, value: Any) -> None:
        raw = json.dumps(value, sort_keys=True, default=str).encode("utf-8")
        if len(raw) > INLINE_LIMIT_BYTES:
            ref = ref_of(value)
            self._step.output_ref = ref
            self._trace.blobs[ref] = value
        else:
            self._step.output = value

    def status(self, value: str) -> None:
        self._step.status = value


class Recorder:
    def __init__(self, run_id: str, meta: Optional[dict] = None):
        self.trace = Trace(run_id=run_id, meta=meta or {})
        self._counter = 0

    def _next_id(self) -> str:
        self._counter += 1
        return "step" + str(self._counter)

    @contextmanager
    def step(self, name: str, kind: str = "custom", depends_on: Optional[list[str]] = None):
        step = Step(
            id=self._next_id(),
            name=name,
            kind=kind,
            depends_on=list(depends_on or []),
            started_at=time.time(),
        )
        handle = StepHandle(step, self.trace)
        self.trace.steps.append(step)
        try:
            yield handle
            if step.status == "unknown":
                step.status = "pass"
        except Exception as exc:
            step.status = "fail"
            step.error = repr(exc)
            raise
        finally:
            step.ended_at = time.time()

    def mark(self, status: str) -> None:
        self.trace.status = status

    def save(self, path: str) -> str:
        if self.trace.status == "unknown":
            self.trace.status = "fail" if any(
                s.status == "fail" for s in self.trace.steps
            ) else "pass"
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(self.trace.to_json())
        return path
