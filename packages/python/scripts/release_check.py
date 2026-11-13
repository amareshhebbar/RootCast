from __future__ import annotations

import argparse
import filecmp
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import venv
import zipfile

PKG_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
REPO_DIR = os.path.abspath(os.path.join(PKG_DIR, "..", ".."))
DIST_DIR = os.path.join(PKG_DIR, "dist")
NAME = "rootcast"
INDEXES = {
    "pypi": "https://pypi.org/pypi/{name}/json",
    "testpypi": "https://test.pypi.org/pypi/{name}/json",
}

SAMPLE_SCRIPT = """
import sys
from rootcast import Recorder
rec = Recorder(run_id="release-check", meta={"source": "release_check"})
with rec.step("read_order", kind="tool") as s:
    s.output({"id": 4417, "year": 2026})
with rec.step("lookup_policy", kind="tool", depends_on=["step1"]) as s:
    s.input({"query": "refund window"})
    s.output({"source": "policy_2024", "window_days": 90})
with rec.step("issue_refund", kind="tool", depends_on=["step2"]) as s:
    s.output({"status": "issued"})
    s.status("fail")
rec.mark("fail")
rec.save(sys.argv[1])
"""


class CheckFailed(Exception):
    pass


def log(msg: str) -> None:
    print("[release-check] " + msg, flush=True)


def run(cmd: list[str], cwd: str | None = None, env: dict | None = None) -> str:
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        raise CheckFailed(
            "command failed: " + " ".join(cmd) + "\n" + proc.stdout + proc.stderr
        )
    return proc.stdout


def package_version() -> str:
    with open(os.path.join(PKG_DIR, "src", NAME, "__init__.py"), "r", encoding="utf-8") as fh:
        match = re.search(r'^__version__\s*=\s*"([^"]+)"', fh.read(), re.M)
    if not match:
        raise CheckFailed("__version__ not found in src/rootcast/__init__.py")
    return match.group(1)


def check_tag(version: str, tag: str | None) -> None:
    if tag is None:
        return
    expected = "v" + version
    if tag != expected:
        raise CheckFailed("tag " + tag + " does not match package version, expected " + expected)
    log("tag matches version " + expected)


def published_versions(index: str) -> set[str] | None:
    url = INDEXES[index].format(name=NAME)
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.load(resp)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        raise CheckFailed(index + " lookup failed: HTTP " + str(exc.code))
    except urllib.error.URLError as exc:
        raise CheckFailed(index + " lookup failed: " + str(exc.reason))
    return set(data.get("releases", {}).keys())


def check_index(version: str, index: str) -> None:
    versions = published_versions(index)
    if versions is None:
        log(index + ": name " + NAME + " is free")
        return
    if version in versions:
        raise CheckFailed(
            index + " already has " + NAME + " " + version + ", bump __version__ before releasing"
        )
    log(index + ": " + NAME + " exists, " + version + " not yet published (have " + ", ".join(sorted(versions)) + ")")


def check_license() -> None:
    pkg = os.path.join(PKG_DIR, "LICENSE")
    root = os.path.join(REPO_DIR, "LICENSE")
    if not os.path.exists(pkg):
        raise CheckFailed("packages/python/LICENSE is missing")
    if os.path.exists(root) and not filecmp.cmp(pkg, root, shallow=False):
        raise CheckFailed("packages/python/LICENSE differs from the repo LICENSE")
    log("license present and in sync")


def build() -> tuple[str, str]:
    shutil.rmtree(DIST_DIR, ignore_errors=True)
    run([sys.executable, "-m", "build", "--outdir", DIST_DIR, PKG_DIR])
    wheels = glob.glob(os.path.join(DIST_DIR, "*.whl"))
    sdists = glob.glob(os.path.join(DIST_DIR, "*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise CheckFailed("expected one wheel and one sdist in dist")
    log("built " + os.path.basename(wheels[0]) + " and " + os.path.basename(sdists[0]))
    return wheels[0], sdists[0]


def check_twine(wheel: str, sdist: str) -> None:
    run([sys.executable, "-m", "twine", "check", "--strict", wheel, sdist])
    log("twine check passed")


def check_wheel_contents(wheel: str, version: str) -> None:
    with zipfile.ZipFile(wheel) as zf:
        names = set(zf.namelist())
        dist_info = NAME + "-" + version + ".dist-info/"
        required = [
            NAME + "/__init__.py",
            NAME + "/__main__.py",
            NAME + "/cli.py",
            NAME + "/py.typed",
            dist_info + "METADATA",
            dist_info + "entry_points.txt",
        ]
        missing = [n for n in required if n not in names]
        if missing:
            raise CheckFailed("wheel is missing: " + ", ".join(missing))
        if not any(n.startswith(dist_info) and n.endswith("LICENSE") for n in names):
            raise CheckFailed("wheel is missing the LICENSE file")
        stray = [n for n in names if n.startswith("tests/") or "/tests/" in n or "__pycache__" in n]
        if stray:
            raise CheckFailed("wheel contains stray files: " + ", ".join(sorted(stray)))
        entry = zf.read(dist_info + "entry_points.txt").decode("utf-8")
        if "rootcast = rootcast.cli:main" not in entry:
            raise CheckFailed("console entry point rootcast is missing")
        meta = zf.read(dist_info + "METADATA").decode("utf-8")
        for needle in ("Name: rootcast", "Version: " + version, "Requires-Python: >=3.9", "Description-Content-Type: text/markdown"):
            if needle not in meta:
                raise CheckFailed("wheel METADATA is missing: " + needle)
    log("wheel contents ok")


def check_sdist_contents(sdist: str, version: str) -> None:
    root = NAME + "-" + version + "/"
    with tarfile.open(sdist) as tf:
        names = set(tf.getnames())
    for need in ("pyproject.toml", "README.md", "LICENSE", "src/rootcast/__init__.py", "src/rootcast/py.typed"):
        if root + need not in names:
            raise CheckFailed("sdist is missing " + need)
    log("sdist contents ok")


def _venv_bin(env_dir: str, exe: str) -> str:
    sub = "Scripts" if os.name == "nt" else "bin"
    suffix = ".exe" if os.name == "nt" else ""
    return os.path.join(env_dir, sub, exe + suffix)


def sample_traces() -> list[str]:
    return sorted(glob.glob(os.path.join(REPO_DIR, "examples", "traces", "*.rootcast.json")))


def check_fresh_install(wheel: str, version: str) -> None:
    work = tempfile.mkdtemp(prefix="rootcast-release-")
    try:
        env_dir = os.path.join(work, "venv")
        venv.EnvBuilder(with_pip=True, clear=True).create(env_dir)
        py = _venv_bin(env_dir, "python")
        cli = _venv_bin(env_dir, "rootcast")
        run([py, "-m", "pip", "install", "--no-index", "--no-deps", "--quiet", wheel], cwd=work)
        log("installed wheel into a fresh virtualenv")

        out = run([cli, "--version"], cwd=work).strip()
        if out != "rootcast " + version:
            raise CheckFailed("rootcast --version printed " + repr(out))
        out = run([py, "-m", "rootcast", "--version"], cwd=work).strip()
        if out != "rootcast " + version:
            raise CheckFailed("python -m rootcast --version printed " + repr(out))
        log("rootcast command is on PATH and reports " + version)

        imported = run([py, "-c", "import rootcast, os; print(os.path.dirname(rootcast.__file__))"], cwd=work).strip()
        if not os.path.abspath(imported).startswith(os.path.abspath(env_dir)):
            raise CheckFailed("rootcast imported from outside the virtualenv: " + imported)

        generated = os.path.join(work, "release-check.rootcast.json")
        script = os.path.join(work, "make_sample.py")
        with open(script, "w", encoding="utf-8") as fh:
            fh.write(SAMPLE_SCRIPT)
        run([py, script, generated], cwd=work)

        traces = [generated] + sample_traces()
        for trace in traces:
            label = os.path.basename(trace)
            run([cli, "validate", trace], cwd=work)
            view = run([cli, "view", trace], cwd=work)
            if "FAIL" not in view:
                raise CheckFailed("view on " + label + " did not show the failing run")
            run([cli, "audit", trace], cwd=work)
            with open(trace, "r", encoding="utf-8") as fh:
                run_id = json.load(fh)["run_id"]
            run([cli, "replay", run_id, "--set", "step2.result=fixed"], cwd=work)
            log("view, validate, audit, replay ran on " + label)
    finally:
        shutil.rmtree(work, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="release_check")
    parser.add_argument("--tag", help="git tag being released, must equal v plus the package version")
    parser.add_argument("--index", action="append", choices=sorted(INDEXES), help="index to check the version against, repeatable")
    parser.add_argument("--offline", action="store_true", help="skip registry lookups")
    parser.add_argument("--keep-dist", action="store_true", help="leave the built files in dist")
    args = parser.parse_args(argv)

    try:
        version = package_version()
        log("package version " + version)
        check_tag(version, args.tag)
        if not args.offline:
            for index in args.index or ["pypi"]:
                check_index(version, index)
        check_license()
        wheel, sdist = build()
        check_twine(wheel, sdist)
        check_wheel_contents(wheel, version)
        check_sdist_contents(sdist, version)
        check_fresh_install(wheel, version)
        if not args.keep_dist:
            shutil.rmtree(DIST_DIR, ignore_errors=True)
    except CheckFailed as exc:
        log("FAIL " + str(exc))
        return 1
    log("PASS " + NAME + " " + version + " is ready to upload")
    return 0


if __name__ == "__main__":
    sys.exit(main())
