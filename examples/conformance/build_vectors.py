"""Regenerate the cross language conformance vectors from the Python SDK.

    python examples/conformance/build_vectors.py

Every SDK test suite loads these files and must reproduce them exactly.
"""
import json
import os

from rootcast import validate
from rootcast.schema import canonical_bytes, ref_of

HERE = os.path.dirname(os.path.abspath(__file__))

VALUES = [
    None,
    True,
    0,
    -0.0,
    129.0,
    0.1,
    1767225600.25,
    1e-07,
    1.5e-05,
    1e21,
    1.2345678901234567e20,
    -3.5e-10,
    "plain",
    "quote \" backslash \\ newline \n tab \t bell \u0007",
    "café 日本 \U0001F600",
    {"b": 1, "a": [1, 2, {"z": None, "y": 2.0}], "c": {}},
    {"\U0001F600": 1, "ﬁ": 2, "Z": 3, "a": 4, "10": 5, "2": 6},
    [[], {}, "", 0, False],
    {"amount": 129.0, "id": 4417, "nested": {"deep": [1.0, 2.5, "x" * 3000]}},
]

TRACE_OK = {
    "rootcast_version": "0.1",
    "run_id": "ok",
    "status": "fail",
    "steps": [
        {"id": "s1", "name": "a", "kind": "tool", "output_ref": "sha256:abc"},
        {"id": "s2", "name": "b", "kind": "llm", "depends_on": ["s1"], "started_at": 1, "ended_at": 2},
    ],
    "blobs": {"sha256:abc": {"big": True}},
}

TRACES = [
    ("valid", TRACE_OK),
    ("not an object", [1, 2]),
    ("bad top level", {"rootcast_version": "0.2", "run_id": "", "status": "maybe", "meta": [], "steps": {}}),
    ("bad blobs", {"rootcast_version": "0.1", "run_id": "r", "status": "pass", "blobs": [], "steps": []}),
    ("bad steps", {
        "rootcast_version": "0.1",
        "run_id": "r",
        "status": "pass",
        "blobs": {"sha256:known": 1},
        "steps": [
            "nope",
            {"id": "s1", "name": "", "kind": "robot", "status": "great", "inputs": [1]},
            {"id": "s1", "name": "dup", "kind": "tool", "output": 1, "output_ref": "sha256:known"},
            {"id": "s3", "name": "c", "kind": "tool", "output_ref": "md5:x"},
            {"id": "s4", "name": "d", "kind": "tool", "output_ref": "sha256:missing", "error": 5},
            {"id": "s5", "name": "e", "kind": "io", "started_at": "now", "ended_at": 1},
            {"id": "s6", "name": "f", "kind": "io", "started_at": 5, "ended_at": 4},
            {"id": "s7", "name": "g", "kind": "decision", "depends_on": "s1"},
            {"id": "s8", "name": "h", "kind": "custom", "depends_on": ["s8", "s99", "s1"]},
            {"name": "no id", "kind": "tool"},
        ],
    }),
]


def main():
    canonical = [
        {"value": v, "canonical": canonical_bytes(v).decode("utf-8"), "ref": ref_of(v)} for v in VALUES
    ]
    validation = [{"name": n, "trace": t, "errors": validate(t)} for n, t in TRACES]
    for name, data in (("canonical.json", canonical), ("validation.json", validation)):
        with open(os.path.join(HERE, name), "w", encoding="utf-8", newline="") as fh:
            fh.write(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
        print("wrote examples/conformance/" + name)


if __name__ == "__main__":
    main()
