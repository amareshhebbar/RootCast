"""Phase 1 gate, Python half: a Node recorder writes traces, Python loads them,
validates them clean, checks the dependencies, and finds them byte identical
to what the Python recorder writes for the same scenario.

Needs node and a built Node SDK (npm --prefix packages/node run build).
Skips when either is missing, unless ROOTCAST_REQUIRE_NODE=1 (set in CI),
in which case it fails instead.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile

import pytest

from rootcast import Trace, validate

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
EXAMPLES = os.path.join(ROOT, "examples")
TRACES = os.path.join(EXAMPLES, "traces")
NODE_DIST = os.path.join(ROOT, "packages", "node", "dist", "index.js")
NODE_GENERATE = os.path.join(EXAMPLES, "node", "generate_traces.mjs")

with open(os.path.join(TRACES, "expected.json"), "r", encoding="utf-8") as fh:
    EXPECTED = json.load(fh)


def _node_or_skip():
    node = shutil.which("node")
    missing = None
    if node is None:
        missing = "node is not installed"
    elif not os.path.exists(NODE_DIST):
        missing = "Node SDK is not built, run npm --prefix packages/node run build"
    if missing:
        if os.environ.get("ROOTCAST_REQUIRE_NODE") == "1":
            pytest.fail(missing)
        pytest.skip(missing)
    return node


@pytest.fixture(scope="module")
def node_traces():
    node = _node_or_skip()
    out = tempfile.mkdtemp(prefix="rootcast-node-")
    subprocess.run([node, NODE_GENERATE, "--out", out], check=True, capture_output=True)
    return out


@pytest.fixture(scope="module")
def python_traces():
    sys.path.insert(0, EXAMPLES)
    try:
        import generate_traces
    finally:
        sys.path.remove(EXAMPLES)
    out = tempfile.mkdtemp(prefix="rootcast-py-")
    generate_traces.generate(out)
    return out


def _read_bytes(path):
    with open(path, "rb") as fh:
        return fh.read()


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_node_trace_loads_and_validates_in_python(node_traces, name):
    path = os.path.join(node_traces, name + ".rootcast.json")
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    assert validate(data) == []
    trace = Trace.load(path)
    want = EXPECTED[name]
    assert trace.run_id == want["run_id"]
    assert trace.status == "fail"
    assert {s.id: s.depends_on for s in trace.steps} == want["depends_on"]
    assert trace.get(want["fail"]).status == "fail"


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_node_and_python_traces_are_byte_identical(node_traces, python_traces, name):
    from_node = _read_bytes(os.path.join(node_traces, name + ".rootcast.json"))
    from_python = _read_bytes(os.path.join(python_traces, name + ".rootcast.json"))
    assert from_node == from_python


@pytest.mark.parametrize("name", sorted(EXPECTED))
def test_python_resave_of_node_trace_is_identity(node_traces, name):
    path = os.path.join(node_traces, name + ".rootcast.json")
    assert Trace.load(path).to_json().encode("utf-8") == _read_bytes(path)
