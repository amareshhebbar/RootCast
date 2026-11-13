import os
import re
import subprocess
import sys

import pytest

import rootcast
from rootcast.cli import build_parser, main

PKG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def test_version_is_single_sourced():
    with open(os.path.join(PKG_DIR, "pyproject.toml"), "r", encoding="utf-8") as fh:
        pyproject = fh.read()
    assert 'dynamic = ["version"]' in pyproject
    assert re.search(r'^version\s*=', pyproject, re.M) is None
    assert re.fullmatch(r"\d+\.\d+\.\d+((a|b|rc)\d+|\.dev\d+|\.post\d+)?", rootcast.__version__)


def test_version_flag(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert capsys.readouterr().out.strip() == "rootcast " + rootcast.__version__


def test_python_dash_m_entry():
    out = subprocess.run(
        [sys.executable, "-m", "rootcast", "--version"], capture_output=True, text=True, check=True
    ).stdout.strip()
    assert out == "rootcast " + rootcast.__version__


def test_typed_marker_ships():
    assert os.path.exists(os.path.join(os.path.dirname(rootcast.__file__), "py.typed"))


def test_subcommands_registered():
    parser = build_parser()
    choices = parser._subparsers._group_actions[0].choices
    for name in ("view", "validate", "audit", "replay"):
        assert name in choices


def test_package_license_matches_repo():
    root = os.path.abspath(os.path.join(PKG_DIR, "..", "..", "LICENSE"))
    local = os.path.join(PKG_DIR, "LICENSE")
    with open(local, "rb") as a, open(root, "rb") as b:
        assert a.read() == b.read()
