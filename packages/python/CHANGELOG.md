# Changelog

All notable changes to the rootcast Python package.

## Unreleased

* Cross language encoding: numbers are written in the ECMAScript format shared with the Node SDK (`129.0` is now `129`, `1e-05` is now `0.00001`), NaN and infinities become `null`. This changes `output_ref` hashes of payloads that contain such floats.
* Step error text is now `Name: message` (was `repr(exc)`), the same in every SDK.
* Trace files are always written with LF line endings, also on Windows.
* `Recorder.save()` and `Trace.save()` with no path write to the trace store, `<ROOTCAST_DIR or .rootcast>/runs/<run_id>.rootcast.json`. New `trace_path`, `encode` and `format_number` helpers.
* Release tooling: single sourced version, `rootcast --version`, `python -m rootcast`, typed package marker, release check script, TestPyPI then PyPI workflow.

## 0.1.0

* Trace schema v0.1 and validator.
* Recorder with context manager and large payload referencing.
* CLI with view, validate, audit and replay (audit and replay are stubs).
