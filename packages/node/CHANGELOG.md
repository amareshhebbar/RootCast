# Changelog

All notable changes to the rootcast Node package.

## 0.1.0

* Recorder with `step()` and the `record()` function wrapper, `currentStep()` across async code, injectable clock.
* Large outputs stored once in the trace's `blobs` by sha256, measured in UTF-8 bytes.
* Dependency inference from data flow, identical to the Python SDK.
* Canonical encoding shared with Python: Node and Python write byte identical trace files for the same run.
* `loadTrace`, `validateFile`, `listTraces`, `tracePath` and the trace store (`.rootcast/runs`, `ROOTCAST_DIR`).
* `rootcast validate` and `rootcast list` CLI.
* ESM only, Node 18 or newer, no runtime dependencies, types included.
