# Releasing the Python package

The rootcast Python package is published from `packages/python` by the `release` workflow. Nothing is uploaded from a laptop.

## One time setup

1. On PyPI and on TestPyPI, add a trusted publisher for project `rootcast`: owner `amareshhebbar`, repository `RootCast`, workflow `release.yml`, environment `pypi` on PyPI and `testpypi` on TestPyPI.
2. In the GitHub repo settings, create the environments `pypi` and `testpypi`. Add a required reviewer on `pypi` so a real upload always waits for a click.

## Version rules

1. The version lives in one place: `__version__` in `packages/python/src/rootcast/__init__.py`. `pyproject.toml` reads it.
2. PyPI never accepts the same version twice, even after a delete. `0.1.0` is already published, so the next release must be higher.
3. The git tag must be `v` plus that version, for example `v0.2.0`. The workflow refuses a mismatch.

## Local dry run

```bash
cd packages/python
pip install build twine
python scripts/release_check.py
```

The check fails if the version already exists on PyPI. It then builds the wheel and sdist, runs `twine check --strict`, inspects both archives, installs the wheel into a fresh virtualenv with no network, and runs `rootcast --version`, `view`, `validate`, `audit` and `replay` on a generated trace plus every committed sample in `examples/traces`. Use `--offline` to skip the registry lookup and `--index testpypi` to check TestPyPI instead.

## TestPyPI dry run

Actions, release, Run workflow, target `testpypi`. This uploads to TestPyPI only and then installs it back from TestPyPI to confirm the command works.

## Real release

1. Bump `__version__` and move the Unreleased notes in `packages/python/CHANGELOG.md` under the new version.
2. Merge to main through a PR with CI green.
3. On release day, run `python scripts/release_check.py` once more. This is the final confirmation that the name and version are free.
4. Tag and push:

```bash
git checkout main && git pull
git tag v0.2.0
git push origin v0.2.0
```

The workflow runs tests and the release check, uploads to TestPyPI, installs it back from TestPyPI, then waits for approval on the `pypi` environment and uploads to PyPI.

5. Confirm from a clean machine:

```bash
python -m venv /tmp/rc && . /tmp/rc/bin/activate
pip install rootcast==0.2.0
rootcast --version
```
