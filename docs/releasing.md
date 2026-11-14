---
title: "Releasing"
description: "How the Python and Node packages and the docs site are published."
---

## Python package

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

## Node package

The `rootcast` npm package is published from `packages/node` by the `release-node` workflow. Nothing is published from a laptop.

### One time setup

1. Create an npm automation token for the account that will own `rootcast`, and add it to the GitHub repo as the secret `NPM_TOKEN`.
2. In the GitHub repo settings, create the environment `npm` and add a required reviewer, so a publish always waits for a click.
3. After the first publish, optionally switch to npm trusted publishing for this repository and workflow and delete the token.

### Version rules

1. The version lives in `packages/node/package.json`. The Node and Python packages are versioned independently.
2. The git tag must be `node-v` plus that version, for example `node-v0.1.0`. The workflow refuses a mismatch. Plain `v*` tags release Python only.
3. npm never accepts the same version twice, even after an unpublish.

### Local dry run

```bash
cd packages/node
npm install
npm run release:check
```

The check confirms the name and version are free on npm, runs the tests, packs the tarball and inspects it (only `dist`, README, LICENSE, CHANGELOG and `package.json`, a `.d.ts` for every module, the CLI shebang), then creates a fresh project that installs the tarball, records a trace, loads and validates it, runs `npx rootcast validate`, validates it with the Python CLI when available, and type checks a TypeScript consumer under `nodenext` and `bundler` resolution without `@types/node`. Use `--offline` to skip the registry lookup and `--keep` to keep the temp project.

Running the `release-node` workflow by hand runs the same check in CI and stops before publishing.

### Real release

1. Bump `version` in `packages/node/package.json` and add the notes to `packages/node/CHANGELOG.md`.
2. Merge to main through a PR with CI green.
3. On release day, run `npm run release:check` once more. This is the final confirmation that the name and version are free.
4. Tag and push:

```bash
git checkout main && git pull
git tag node-v0.1.0
git push origin node-v0.1.0
```

The workflow checks, waits for approval on `npm`, publishes with provenance, then installs `rootcast@<version>` from the registry into a fresh project and records a trace (`release_check.mjs --from-registry`).

## Docs site

The docs site is built by Mintlify from this `docs` folder (`docs/docs.json` is the config) and served through Netlify.

### One time setup

1. Create a Mintlify project, install the Mintlify GitHub app on the repository, and in Git Settings enable **docs.json is in a subdirectory** with the path `/docs`. Every push to `main` deploys to `https://<subdomain>.mintlify.site`.
2. Create a Netlify site from the repository. `netlify.toml` at the repo root proxies every path to the Mintlify site. If the Mintlify subdomain is not `rootcast`, change the target in `netlify.toml`.
3. Optional: give the Netlify site a custom domain, and set `seo.metatags.canonical` in `docs/docs.json` to it.

If nothing else needs to run on the docs domain, pointing a custom domain straight at Mintlify (`mint add-domain`) is simpler than the Netlify proxy.

### Checking locally

```bash
cd docs
npx mint validate
npx mint broken-links
npx mint dev
```
