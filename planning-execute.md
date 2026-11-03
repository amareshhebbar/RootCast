# Rootcast planning and execution

The flight recorder for AI agents. This document is the build plan. It defines what Rootcast is, the phased roadmap from Phase 0 to public release, the task matrix per phase split between Amaresh and Ashutosh, branch names, required outputs, test gates, and the path to publishing on PyPI and npm.

Owners are a starting split, not a wall. Amaresh owns the AI and causal core. Ashutosh owns SDK transport, UI, and distribution. Swap any task by agreement.

## Project definition

Rootcast records why an AI agent made each decision during a run, then reconstructs the causal chain behind a failure, points to the earliest step that caused it, and proves the fix by replaying the run with one variable changed.

In scope:

* One portable trace format that any language or framework can emit.
* Python and Node recorders that capture steps with near zero change to agent behavior.
* A causal engine that builds a decision graph and finds the earliest divergence.
* A replay engine that flips one input and reports whether the outcome changes.
* A web UI that draws the decision map and runs replay on click.
* Public release on PyPI and npm.

Out of scope for v1:

* Live production streaming at scale (v0.1 works on saved trace files).
* Training a model. Rootcast is deterministic graph analysis, not a learned judge.
* Replacing observability dashboards. Rootcast consumes traces, it does not host them.

Boundaries: Rootcast never mutates the agent under record. The recorder only watches. Replay runs in a sandboxed re executor, never against the live run.

## Architecture overview

```
agent run
   |
   v
[ Layer 1 Capture ]  recorder (py + node)  ->  trace.rootcast.json
   |
   v
[ Layer 2 Causal engine ]  decision graph  ->  divergence + PASS WARN FAIL + CAUSE
   |
   v
[ Layer 3 Replay ]  one variable counterfactual  ->  FAIL flips to PASS = proof
   |
   v
[ Layer 4 UI ]  decision map, click to replay
```

The trace file is the contract between every layer. Lock the schema early and nothing downstream churns.

## Repository layout

```
rootcast/
  README.md
  LICENSE
  planning-execute.md
  docs/
    trace-schema.md
  packages/
    python/
      pyproject.toml
      src/rootcast/        schema, recorder, cli, causal, replay, adapters
      tests/
    node/
      package.json
      tsconfig.json
      src/                 schema, recorder, adapters
  ui/                      web decision map (added Phase 4)
  examples/
    failing_agent.py
  .github/workflows/ci.yml
```

## Branch and PR rules

* main is protected. Nothing commits straight to main.
* One branch per task block below. Branch name is given in each task.
* Every branch opens a PR into main. CI must pass. One review from the other person.
* Commit style: type scope summary, for example feat causal add divergence walk. No co author trailers.

---

## Phase 0  Base scaffold

Status: done. This repository is the Phase 0 output. It establishes the trace schema, both recorders, the CLI shell, CI, the example, and these docs. Everything below builds on it.

Output already present:

* Trace schema v0.1 and validator in both languages.
* Python recorder with context manager and large payload referencing.
* Node recorder with async step wrapper.
* rootcast CLI with view, validate, audit, replay subcommands (audit and replay are stubs until Phase 2 and 3).
* Passing Python smoke tests and green CI config.

---

## Phase 1  Capture layer and schema lock

Goal: finalize the trace schema and make capture effortless from any agent, so real traces exist to build the engine on.

### Amaresh

* Branch: feat/capture-python
* Tasks:
  * Freeze schema v0.1. Add a dependency inference pass that fills depends_on by matching a step output hash to later step inputs when the framework does not declare it.
  * Add a decorator form of the recorder alongside the context manager.
  * Write three real traces using the example scenario and two new ones (a RAG lookup failure, a tool argument error).
* Required output: rootcast records any Python agent with two lines of change, and produces schema valid traces with inferred dependencies. Three committed sample traces under examples/traces.
* Test gate: pytest covers dependency inference and decorator path. Validator passes on all three samples.

### Ashutosh

* Branch: feat/capture-node
* Tasks:
  * Bring the Node recorder to parity: dependency inference, decorator or wrapper helper, large payload referencing already present.
  * Define the on disk trace file conventions (naming, where blobs live, how a run folder is structured when there are many runs).
  * Add a tiny trace loader and validator entry usable from Node.
* Required output: Node and Python write byte compatible traces for the same scenario. A documented trace file convention in docs.
* Test gate: a Node test writes a trace, a Python test loads it and validates it clean. Cross language roundtrip proven.

Phase 1 done when: the same agent scenario recorded in both languages produces traces that both validators accept and that carry correct dependencies.

---

## Phase 2  Causal engine

Goal: turn a trace into an answer. Build the decision graph, find the earliest divergence, score each step, tag the cause.

### Amaresh

* Branch: feat/causal-engine
* Tasks:
  * Build the decision graph from steps and depends_on.
  * Implement the backward divergence walk from the failing step to the earliest step whose output, if corrected, breaks the failure chain.
  * Tag that step CAUSE. Produce a one line human summary of the cause.
* Required output: rootcast audit trace.json prints the decision chain with the CAUSE step marked and a plain summary. Replaces the Phase 0 audit stub.
* Test gate: on each of the three sample traces the engine names the known injected cause. Regression test asserts the expected CAUSE id per sample.

### Ashutosh

* Branch: feat/scoring
* Tasks:
  * Implement per step PASS WARN FAIL scoring from signals: step error, status set by the agent, stale or mismatched inputs, empty or malformed tool results.
  * Implement anomaly flags (a tool that returned far more or less than usual, a step that took far longer).
  * Feed scores into the audit output so WARN steps are visible even when they did not directly cause the failure.
* Required output: audit output shows a status tag on every step and a flags list. Scoring is a separate module the causal engine imports.
* Test gate: unit tests per scoring rule. The stale policy sample shows step 2 as WARN and step 4 as FAIL.

Phase 2 done when: rootcast audit on the stale policy sample prints exactly the four line chain in the README with CAUSE on the policy lookup.

---

## Phase 3  Replay engine

Goal: prove the cause. Re run a trace with one value changed and report whether the outcome flips.

### Amaresh

* Branch: feat/replay-core
* Tasks:
  * Build the replay executor that reconstructs the run from the trace and re executes from a chosen step forward.
  * Implement single variable injection: rootcast replay RUN --set stepN.result=VALUE.
  * Serve unchanged deterministic steps from the recorded cache so only the affected branch recomputes.
* Required output: rootcast replay flips the stale policy sample from FAIL to PASS when step 2 result is corrected, and prints the before and after status.
* Test gate: replay test asserts FAIL to PASS on the known fix, and asserts no change when an unrelated step is altered.

### Ashutosh

* Branch: feat/replay-diff
* Tasks:
  * Implement the outcome diff: what changed between the original run and the replayed run, step by step.
  * Handle the case where a step is an external call by requiring an explicit injected value rather than calling out.
  * Add a replay result object that the UI will consume in Phase 4.
* Required output: a structured replay result (changed steps, final status delta) printed as text now and ready for the UI.
* Test gate: diff test on the sample shows only the downstream steps changed, cause step input changed, upstream untouched.

Phase 3 done when: the README replay line is real and reproducible from the committed sample.

---

## Phase 4  Web UI

Goal: the thing judges and users look at. A decision map that makes the cause obvious, with click to replay.

### Ashutosh

* Branch: feat/ui-map
* Tasks:
  * Build the UI under ui/ as one self contained web app. Load a trace file, draw the decision graph, color nodes by PASS WARN FAIL, highlight CAUSE.
  * Click a node to see its inputs, output, and why it was scored that way.
  * Wire a replay panel: pick a step, set a value, run replay, show the FAIL to PASS flip visually.
* Required output: open the UI, drop in a trace, see the map and run a replay without touching a terminal.
* Test gate: the stale policy sample renders with the cause highlighted and replay flips the banner to PASS in the UI.

### Amaresh

* Branch: feat/ui-bridge
* Tasks:
  * Expose a thin local command rootcast serve that runs audit and replay behind a local endpoint the UI calls.
  * Make sure the UI runs the real engine, not a reimplementation, so there is one source of truth.
* Required output: rootcast serve starts the backend the UI talks to. One engine, two front doors (CLI and UI).
* Test gate: UI replay and CLI replay on the same trace return identical results.

Phase 4 done when: a person who has never seen Rootcast can load a failed run and find the cause in under a minute.

---

## Phase 5  Package and release

Goal: ship. Publish both packages, document, and record the demo.

### Amaresh

* Branch: release/python
* Tasks:
  * Finalize pyproject metadata, long description, classifiers, entry point.
  * Build and check the wheel and sdist. Dry run upload to TestPyPI, then real upload to PyPI.
  * Confirm the final name is free on PyPI on release day before upload.
* Required output: pip install rootcast works and the rootcast command is on PATH.
* Test gate: fresh virtualenv installs from the built wheel and runs view, audit, replay on a sample.

### Ashutosh

* Branch: release/node
* Tasks:
  * Finalize package.json, build to dist, verify types ship.
  * npm pack and inspect the tarball, then npm publish.
  * Confirm the final name is free on npm on release day before publish.
  * Set up the docs site (Mintlify, served on Netlify) from docs and the README.
* Required output: npm install rootcast works and imports clean in a fresh project. Docs site live.
* Test gate: fresh project installs from the published tarball and records a trace.

### Both

* Branch: chore/launch
* Tasks:
  * Record the demo: take the stale policy failure, show the wall of logs, then Rootcast finding the cause and proving the fix.
  * Final README polish. Tag v0.1.0 on main.
* Required output: tagged release, demo recorded, both packages live, docs up.

Phase 5 done when: both packages are installable from their public registries and the demo reproduces end to end.

---

## Path to completion

How to start: each person checks out their Phase 1 branch today. Schema lock first, because every later phase depends on it. Do not start Phase 2 until both recorders write validating, dependency carrying traces.

How to test as you go: every phase ships with a test gate above. The three sample traces are the spine. Each engine feature is correct when it produces the known answer on the known sample. Never merge a phase branch with a red gate.

How to bridge milestones: Phase N output is Phase N plus one input. Capture feeds the engine. The engine feeds replay. Replay feeds the UI. Keep the trace schema the single contract so the two of you can work in parallel without blocking.

How to conclude: when Phase 5 gates pass, tag v0.1.0, publish both packages, and the four line audit in the README is a real command anyone can run. After release, the roadmap continues with more framework adapters and live streaming capture, opened to outside contributors.
