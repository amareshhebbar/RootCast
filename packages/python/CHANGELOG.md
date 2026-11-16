# Changelog

All notable changes to the rootcast Python package.

## 0.2.0

* `pip install rootcast` is self contained: the web UI, the three sample failed runs and their replay agents ship inside the package. `rootcast serve` works from any folder.
* `rootcast demo [DIR]` writes the sample runs so `audit` and `replay` can be tried right after install. `replay` picks the bundled agent for a bundled sample, no `--agent` needed.
* The release check installs the wheel into a fresh virtualenv and proves `demo`, bundled replay and `serve` with a FAIL to PASS replay through the UI endpoint.
* `rootcast serve`: a local engine (stdlib only, 127.0.0.1) that serves the web UI in `ui/index.html` and runs the real audit and replay behind `/api/audit` and `/api/replay`. The UI draws the decision map, highlights the root cause, explains every score and runs click to replay with a FAIL to PASS banner flip. See docs/ui.md.
* `rootcast replay` is real: re runs a trace with `--set STEP.output[.path]=VALUE`, serves unchanged steps from the recording, recomputes downstream steps through the agent's own functions (`--agent`, `replay_agent(rec)`), refuses to call external tool, io and llm steps without an injected value, and prints a step by step outcome diff with the run status delta. `ReplayResult.to_dict()` (and `--json`) is the object the UI consumes. See docs/replay.md.
* `rootcast audit` is real: per step PASS / WARN / FAIL scoring (`rootcast.scoring`), anomaly flags against a `--baseline` of earlier runs, the decision graph and a baseline divergence walk (`rootcast.causal`) that tags the CAUSE step, a chain and a one line summary. `--json` prints the audit as data.
* Cross language encoding: numbers are written in the ECMAScript format shared with the Node SDK (`129.0` is now `129`, `1e-05` is now `0.00001`), NaN and infinities become `null`. This changes `output_ref` hashes of payloads that contain such floats.
* Step error text is now `Name: message` (was `repr(exc)`), the same in every SDK.
* Trace files are always written with LF line endings, also on Windows.
* `Recorder.save()` and `Trace.save()` with no path write to the trace store, `<ROOTCAST_DIR or .rootcast>/runs/<run_id>.rootcast.json`. New `trace_path`, `encode` and `format_number` helpers.
* Release tooling: single sourced version, `rootcast --version`, `python -m rootcast`, typed package marker, release check script, TestPyPI then PyPI workflow.

## 0.1.0

* Trace schema v0.1 and validator.
* Recorder with context manager and large payload referencing.
* CLI with view, validate, audit and replay (audit and replay are stubs).
