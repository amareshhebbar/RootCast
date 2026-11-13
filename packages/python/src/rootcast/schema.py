from __future__ import annotations

import hashlib
import json
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


def canonical_bytes(payload: Any) -> bytes:
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    ).encode("utf-8")


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
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False, default=str) + "\n"

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

    def save(self, path: str) -> str:
        with open(path, "w", encoding="utf-8") as fh:
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
