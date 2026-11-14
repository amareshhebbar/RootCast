from __future__ import annotations

import functools
import inspect
import time
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Any, Callable, Iterable, Optional

from .infer import infer_dependencies
from .schema import INLINE_LIMIT_BYTES, Step, Trace, canonical_bytes, format_error, ref_of, snapshot

_CURRENT: ContextVar[Optional["StepHandle"]] = ContextVar("rootcast_current_step", default=None)

DEFAULT_EXCLUDE = ("self", "cls")


def current_step() -> Optional["StepHandle"]:
    return _CURRENT.get()


class StepHandle:
    def __init__(self, step: Step, trace: Trace):
        self._step = step
        self._trace = trace

    @property
    def id(self) -> str:
        return self._step.id

    def input(self, data: dict) -> None:
        self._step.inputs = snapshot(data)

    def depends_on(self, *ids: str) -> None:
        for sid in ids:
            if sid not in self._step.depends_on:
                self._step.depends_on.append(sid)

    def output(self, value: Any) -> None:
        if len(canonical_bytes(value)) > INLINE_LIMIT_BYTES:
            ref = ref_of(value)
            self._step.output = None
            self._step.output_ref = ref
            self._trace.blobs[ref] = snapshot(value)
        else:
            self._step.output_ref = None
            self._step.output = snapshot(value)

    def status(self, value: str) -> None:
        self._step.status = value

    def error(self, message: str) -> None:
        self._step.error = message


class Recorder:
    def __init__(
        self,
        run_id: str,
        meta: Optional[dict] = None,
        clock: Optional[Callable[[], float]] = None,
        infer: bool = True,
    ):
        self.trace = Trace(run_id=run_id, meta=dict(meta or {}))
        self._counter = 0
        self._clock = clock or time.time
        self._infer = infer

    def _next_id(self) -> str:
        self._counter += 1
        return "step" + str(self._counter)

    def _open(self, name: str, kind: str, depends_on: Optional[Iterable[str]]) -> StepHandle:
        step = Step(
            id=self._next_id(),
            name=name,
            kind=kind,
            depends_on=list(depends_on or []),
            started_at=self._clock(),
        )
        self.trace.steps.append(step)
        return StepHandle(step, self.trace)

    @staticmethod
    def _close_ok(handle: StepHandle) -> None:
        if handle._step.status == "unknown":
            handle._step.status = "pass"

    @staticmethod
    def _close_err(handle: StepHandle, exc: BaseException) -> None:
        handle._step.status = "fail"
        handle._step.error = format_error(exc)

    @contextmanager
    def step(
        self,
        name: str,
        kind: str = "custom",
        depends_on: Optional[Iterable[str]] = None,
        inputs: Optional[dict] = None,
    ):
        handle = self._open(name, kind, depends_on)
        if inputs is not None:
            handle.input(inputs)
        token = _CURRENT.set(handle)
        try:
            yield handle
            self._close_ok(handle)
        except BaseException as exc:
            self._close_err(handle, exc)
            raise
        finally:
            handle._step.ended_at = self._clock()
            _CURRENT.reset(token)

    def record(
        self,
        fn: Optional[Callable] = None,
        *,
        name: Optional[str] = None,
        kind: str = "custom",
        depends_on: Optional[Iterable[str]] = None,
        capture_inputs: bool = True,
        exclude: Iterable[str] = DEFAULT_EXCLUDE,
    ):
        excluded = set(exclude)

        def decorate(func: Callable) -> Callable:
            label = name or func.__name__
            signature = inspect.signature(func)

            def bind(args: tuple, kwargs: dict) -> Optional[dict]:
                if not capture_inputs:
                    return None
                try:
                    bound = signature.bind_partial(*args, **kwargs)
                    bound.apply_defaults()
                except TypeError:
                    return {"args": list(args), "kwargs": dict(kwargs)}
                out: dict[str, Any] = {}
                for key, value in bound.arguments.items():
                    if key in excluded:
                        continue
                    param = signature.parameters[key]
                    if param.kind is inspect.Parameter.VAR_KEYWORD:
                        out.update(value)
                    else:
                        out[key] = value
                return out

            if inspect.iscoroutinefunction(func):

                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    with self.step(label, kind=kind, depends_on=depends_on, inputs=bind(args, kwargs)) as s:
                        result = await func(*args, **kwargs)
                        s.output(result)
                        return result

                return async_wrapper

            @functools.wraps(func)
            def wrapper(*args, **kwargs):
                with self.step(label, kind=kind, depends_on=depends_on, inputs=bind(args, kwargs)) as s:
                    result = func(*args, **kwargs)
                    s.output(result)
                    return result

            return wrapper

        if fn is not None:
            return decorate(fn)
        return decorate

    def mark(self, status: str) -> None:
        self.trace.status = status

    def infer(self) -> dict[str, list[str]]:
        return infer_dependencies(self.trace)

    def finalize(self) -> Trace:
        if self._infer:
            self.infer()
        if self.trace.status == "unknown":
            self.trace.status = "fail" if any(s.status == "fail" for s in self.trace.steps) else "pass"
        return self.trace

    def save(self, path: Optional[str] = None) -> str:
        self.finalize()
        return self.trace.save(path)
