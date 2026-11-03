from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, asdict
from typing import Any, Optional

ROOTCAST_VERSION = "0.1"

STEP_KINDS = {"tool", "llm", "decision", "io", "custom"}
STEP_STATUS = {"pass", "warn", "fail", "unknown"}
RUN_STATUS = {"pass", "fail", "unknown"}

INLINE_LIMIT_BYTES = 2048


def ref_of(payload: Any) -> str:
    raw = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return "sha256:" + hashlib.sha256(raw).hexdigest()


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
        data = asdict(self)
        return {k: v for k, v in data.items() if v is not None and v != []}


@dataclass
class Trace:
    run_id: str
    status: str = "unknown"
    meta: dict = field(default_factory=dict)
    steps: list[Step] = field(default_factory=list)
    blobs: dict[str, Any] = field(default_factory=dict)

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
        return json.dumps(self.to_dict(), indent=indent, default=str)

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
                depends_on=s.get("depends_on", []),
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
            meta=data.get("meta", {}),
            steps=steps,
            blobs=data.get("blobs", {}),
        )

    @classmethod
    def load(cls, path: str) -> "Trace":
        with open(path, "r", encoding="utf-8") as fh:
            return cls.from_dict(json.load(fh))


def validate(data: dict) -> list[str]:
    errors: list[str] = []
    if data.get("rootcast_version") != ROOTCAST_VERSION:
        errors.append("rootcast_version must be " + ROOTCAST_VERSION)
    if not data.get("run_id"):
        errors.append("run_id is required")
    if data.get("status") not in RUN_STATUS:
        errors.append("status must be one of " + ", ".join(sorted(RUN_STATUS)))
    seen: set[str] = set()
    for i, step in enumerate(data.get("steps", [])):
        where = "steps[" + str(i) + "]"
        sid = step.get("id")
        if not sid:
            errors.append(where + ".id is required")
        elif sid in seen:
            errors.append(where + ".id is duplicated: " + sid)
        else:
            seen.add(sid)
        if step.get("kind") not in STEP_KINDS:
            errors.append(where + ".kind invalid")
    for i, step in enumerate(data.get("steps", [])):
        for dep in step.get("depends_on", []):
            if dep not in seen:
                errors.append("steps[" + str(i) + "].depends_on unknown id: " + dep)
    return errors
