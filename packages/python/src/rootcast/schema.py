from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field
from typing import Any, Optional

ROOTCAST_VERSION = "0.1"

STEP_KINDS = {"tool", "llm", "decision", "io", "custom"}
STEP_STATUS = {"pass", "warn", "fail", "unknown"}
RUN_STATUS = {"pass", "fail", "unknown"}

INLINE_LIMIT_BYTES = 2048

STEP_FIELD_ORDER = (
    "id",
    "name",
    "kind",
    "inputs",
    "output",
    "output_ref",
    "depends_on",
    "status",
    "error",
    "started_at",
    "ended_at",
)


TRACE_SUFFIX = ".rootcast.json"
DEFAULT_STORE = ".rootcast"
STORE_ENV = "ROOTCAST_DIR"


def format_number(value: float) -> str:
    """Format a number exactly like ECMAScript Number.prototype.toString.

    This is the cross language number format (RFC 8785 style). It is what
    makes a Python float like 129.0 and a JS number 129 encode to the same
    bytes. Non finite numbers have no JSON form and encode as null.
    """
    if isinstance(value, int):
        return str(value)
    if math.isnan(value) or math.isinf(value):
        return "null"
    if value == 0:
        return "0"
    sign = "-" if value < 0 else ""
    mantissa, _, exp = repr(abs(value)).partition("e")
    whole, _, frac = mantissa.partition(".")
    digits = whole + frac
    point = len(whole) + (int(exp) if exp else 0)
    stripped = digits.lstrip("0")
    point -= len(digits) - len(stripped)
    digits = stripped.rstrip("0")
    k, n = len(digits), point
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * (-n) + digits
    else:
        e = n - 1
        esign = "+" if e >= 0 else "-"
        head = digits[0] + ("." + digits[1:] if k > 1 else "")
        body = head + "e" + esign + str(abs(e))
    return sign + body


def _key(key: Any) -> str:
    if isinstance(key, str):
        return key
    if key is None:
        return "null"
    if isinstance(key, bool):
        return "true" if key else "false"
    if isinstance(key, (int, float)):
        return format_number(key)
    return str(key)


def encode(value: Any, indent: Optional[int] = None, sort_keys: bool = False, _depth: int = 0) -> str:
    """Encode JSON with the cross language rules shared by every SDK.

    indent None gives the compact form, an int gives the pretty file form
    with ": " and one entry per line.
    """
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return format_number(value)
    if isinstance(value, str):
        return json.dumps(value, ensure_ascii=False)
    if isinstance(value, dict):
        items = [(_key(k), v) for k, v in value.items()]
        if sort_keys:
            items.sort(key=lambda kv: kv[0])
        parts = [json.dumps(k, ensure_ascii=False) + (":" if indent is None else ": ")
                 + encode(v, indent, sort_keys, _depth + 1) for k, v in items]
        return _wrap("{", "}", parts, indent, _depth)
    if isinstance(value, (list, tuple)):
        parts = [encode(v, indent, sort_keys, _depth + 1) for v in value]
        return _wrap("[", "]", parts, indent, _depth)
    return encode(str(value), indent, sort_keys, _depth)


def _wrap(open_: str, close: str, parts: list, indent: Optional[int], depth: int) -> str:
    if not parts:
        return open_ + close
    if indent is None:
        return open_ + ",".join(parts) + close
    inner = "\n" + " " * (indent * (depth + 1))
    return open_ + inner + ("," + inner).join(parts) + "\n" + " " * (indent * depth) + close


def canonical_bytes(payload: Any) -> bytes:
    return encode(payload, sort_keys=True).encode("utf-8")


def format_error(exc: BaseException) -> str:
    """Error text shared by every SDK: "Name: message", or "Name" alone."""
    message = str(exc)
    name = type(exc).__name__
    return name + ": " + message if message else name


def safe_run_id(run_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", run_id) or "_"


def store_root(root: Optional[str] = None) -> str:
    return root or os.environ.get(STORE_ENV) or DEFAULT_STORE


def trace_path(run_id: str, root: Optional[str] = None) -> str:
    """Conventional path of a run inside a trace store: <root>/runs/<run_id>.rootcast.json."""
    return os.path.join(store_root(root), "runs", safe_run_id(run_id) + TRACE_SUFFIX)


def ref_of(payload: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(payload)).hexdigest()


def snapshot(value: Any) -> Any:
    return json.loads(canonical_bytes(value).decode("utf-8"))


@dataclass
class Step:
    id: str
    name: str
    kind: str
    inputs: Optional[dict] = None
    output: Any = None
    output_ref: Optional[str] = None
    depends_on: list[str] = field(default_factory=list)
    status: str = "unknown"
    error: Optional[str] = None
    started_at: Optional[float] = None
    ended_at: Optional[float] = None

    def to_dict(self) -> dict:
        out: dict[str, Any] = {}
        for key in STEP_FIELD_ORDER:
            value = getattr(self, key)
            if value is None or value == []:
                continue
            out[key] = value
        return out

    def resolved_output(self, blobs: dict[str, Any]) -> Any:
        if self.output_ref is not None and self.output_ref in blobs:
            return blobs[self.output_ref]
        return self.output


@dataclass
class Trace:
    run_id: str
    status: str = "unknown"
    meta: dict = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    blobs: dict[str, Any] = field(default_factory=dict)

    def get(self, step_id: str) -> Optional[Step]:
        for step in self.steps:
            if step.id == step_id:
                return step
        return None

    def to_dict(self) -> dict:
        out: dict[str, Any] = {
            "rootcast_version": ROOTCAST_VERSION,
            "run_id": self.run_id,
            "status": self.status,
            "steps": [s.to_dict() for s in self.steps],
        }
        if self.meta:
            out["meta"] = self.meta
        if self.blobs:
            out["blobs"] = self.blobs
        return out

    def to_json(self, indent: int = 2) -> str:
        return encode(self.to_dict(), indent=indent) + "\n"

    @classmethod
    def from_dict(cls, data: dict) -> "Trace":
        steps = [
            Step(
                id=s["id"],
                name=s["name"],
                kind=s.get("kind", "custom"),
                inputs=s.get("inputs"),
                output=s.get("output"),
                output_ref=s.get("output_ref"),
                depends_on=list(s.get("depends_on", [])),
                status=s.get("status", "unknown"),
                error=s.get("error"),
                started_at=s.get("started_at"),
                ended_at=s.get("ended_at"),
            )
            for s in data.get("steps", [])
        ]
        return cls(
            run_id=data["run_id"],
            status=data.get("status", "unknown"),
            meta=dict(data.get("meta", {})),
            steps=steps,
            blobs=dict(data.get("blobs", {})),
        )

    @classmethod
    def load(cls, path: str) -> "Trace":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))

    def save(self, path: Optional[str] = None) -> str:
        path = path or trace_path(self.run_id)
        parent = os.path.dirname(path)
        if parent:
            os.makedirs(parent, exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as fh:
            fh.write(self.to_json())
        return path


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def validate(data: Any) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["trace must be a JSON object"]
    if data.get("rootcast_version") != ROOTCAST_VERSION:
        errors.append("rootcast_version must be " + ROOTCAST_VERSION)
    if not isinstance(data.get("run_id"), str) or not data.get("run_id"):
        errors.append("run_id is required")
    if data.get("status") not in RUN_STATUS:
        errors.append("status must be one of " + ", ".join(sorted(RUN_STATUS)))
    if "meta" in data and not isinstance(data["meta"], dict):
        errors.append("meta must be an object")
    blobs = data.get("blobs", {})
    if not isinstance(blobs, dict):
        errors.append("blobs must be an object")
        blobs = {}
    steps = data.get("steps")
    if not isinstance(steps, list):
        errors.append("steps must be an array")
        return errors

    seen: set[str] = set()
    for i, step in enumerate(steps):
        where = "steps[" + str(i) + "]"
        if not isinstance(step, dict):
            errors.append(where + " must be an object")
            continue
        sid = step.get("id")
        if not isinstance(sid, str) or not sid:
            errors.append(where + ".id is required")
        elif sid in seen:
            errors.append(where + ".id is duplicated: " + sid)
        if not isinstance(step.get("name"), str) or not step.get("name"):
            errors.append(where + ".name is required")
        if step.get("kind") not in STEP_KINDS:
            errors.append(where + ".kind invalid")
        if "status" in step and step["status"] not in STEP_STATUS:
            errors.append(where + ".status invalid")
        if "inputs" in step and not isinstance(step["inputs"], dict):
            errors.append(where + ".inputs must be an object")
        if "output" in step and "output_ref" in step:
            errors.append(where + " has both output and output_ref")
        ref = step.get("output_ref")
        if ref is not None:
            if not isinstance(ref, str) or not ref.startswith("sha256:"):
                errors.append(where + ".output_ref must start with sha256:")
            elif blobs and ref not in blobs:
                errors.append(where + ".output_ref missing from blobs: " + ref)
        if "error" in step and not isinstance(step["error"], str):
            errors.append(where + ".error must be a string")
        for key in ("started_at", "ended_at"):
            if key in step and not _is_number(step[key]):
                errors.append(where + "." + key + " must be a number")
        if _is_number(step.get("started_at")) and _is_number(step.get("ended_at")):
            if step["ended_at"] < step["started_at"]:
                errors.append(where + ".ended_at is before started_at")
        deps = step.get("depends_on", [])
        if not isinstance(deps, list):
            errors.append(where + ".depends_on must be an array")
            deps = []
        for dep in deps:
            if dep == sid:
                errors.append(where + ".depends_on references itself")
            elif dep not in seen:
                errors.append(where + ".depends_on unknown or later id: " + str(dep))
        if isinstance(sid, str) and sid:
            seen.add(sid)
    return errors
