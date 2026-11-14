"""Shared cross language vectors. The Node suite runs the same files."""
import json
import os

import pytest

from rootcast import Recorder, Trace, canonical_bytes, format_number, ref_of, trace_path, validate

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
CONFORMANCE = os.path.join(ROOT, "examples", "conformance")


def _load(name):
    with open(os.path.join(CONFORMANCE, name), "r", encoding="utf-8") as fh:
        return json.load(fh)


@pytest.mark.parametrize("vector", _load("canonical.json"))
def test_canonical_vector(vector):
    assert canonical_bytes(vector["value"]).decode("utf-8") == vector["canonical"]
    assert ref_of(vector["value"]) == vector["ref"]


@pytest.mark.parametrize("vector", _load("validation.json"), ids=lambda v: v["name"])
def test_validation_vector(vector):
    assert validate(vector["trace"]) == vector["errors"]


@pytest.mark.parametrize(
    "value, text",
    [
        (129.0, "129"),
        (0.1, "0.1"),
        (1e-7, "1e-7"),
        (1e-6, "0.000001"),
        (1.5e-5, "0.000015"),
        (1e21, "1e+21"),
        (2.0 ** 60, "1152921504606847000"),
        (-0.0, "0"),
        (-3.5e-10, "-3.5e-10"),
        (5e-324, "5e-324"),
        (float("nan"), "null"),
        (float("inf"), "null"),
        (12, "12"),
    ],
)
def test_format_number_matches_ecmascript(value, text):
    assert format_number(value) == text


def test_keys_sort_by_code_point_not_utf16():
    # U+1F600 is above U+FB01 by code point, below it in UTF-16 units.
    assert canonical_bytes({"\U0001F600": 1, "ﬁ": 2}).decode("utf-8") == '{"ﬁ":2,"\U0001F600":1}'


def test_error_text_is_name_colon_message():
    rec = Recorder(run_id="e")
    with pytest.raises(ValueError):
        with rec.step("boom"):
            raise ValueError("bad seats")
    with pytest.raises(KeyError):
        with rec.step("bare"):
            raise KeyError()
    assert rec.trace.steps[0].error == "ValueError: bad seats"
    assert rec.trace.steps[1].error == "KeyError"


def test_save_defaults_to_store_with_lf(tmp_path, monkeypatch):
    monkeypatch.setenv("ROOTCAST_DIR", str(tmp_path))
    rec = Recorder(run_id="team/run 1")
    with rec.step("s") as s:
        s.output(1.0)
    path = rec.save()
    assert path == trace_path("team/run 1") == os.path.join(str(tmp_path), "runs", "team_run_1.rootcast.json")
    raw = open(path, "rb").read()
    assert raw.endswith(b"}\n") and b"\r" not in raw
    assert Trace.load(path).steps[0].output == 1
