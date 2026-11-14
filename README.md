<div align="center">

# Rootcast

Your AI agent failed in production but did not crash. Rootcast shows you which step went wrong and why. *A developer tool for agents running in production*

[![PyPI](https://img.shields.io/badge/pypi-rootcast-3775A9)](https://pypi.org/project/rootcast/)
[![npm](https://img.shields.io/badge/npm-rootcast-CB3837)](https://www.npmjs.com/package/rootcast)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue)](./LICENSE)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776AB)](https://www.python.org/)

</div>

<br/>

## The problem

When you run an AI agent that does many steps (search, read a file, call a tool, decide, act), sometimes it quietly does the wrong thing. It does not crash. It just produces an answer that looks fine but is actually wrong. You only find out later, when it is already a problem.

Right now, when that happens, all you get is a long boring log of what the agent did. You stare at it and try to guess where it went wrong. It is like a crime scene with no detective.

## The idea

Build a black box recorder for AI agents, like the flight recorder in planes.

While the agent works, Rootcast quietly records why it made each choice, not just what it did. Then when something goes wrong, Rootcast:

1. Shows the chain of decisions as a simple map, not a wall of text.
2. Points to the exact step where things first went off the rails (maybe step 7 failed, but the real mistake was back at step 3 when a tool gave bad info).
3. Lets you hit replay and change one thing, like "what if that bad info was not there?", and see if the agent would have gotten it right.

So instead of guessing, you get a clear answer: here is where it broke, and here is what caused it.

<br/>

## See it in thirty seconds

Today, when an agent fails, you read this:

```
[12:04:01] tool_call search(query="refund policy 2024")
[12:04:02] tool_result "... 847 tokens of text ..."
[12:04:03] llm_call messages=[...]
[12:04:05] llm_result "Based on the policy the refund window is 90 days"
[12:04:06] tool_call issue_refund(order=4417, reason="within window")
[12:04:07] tool_result {"status":"ok"}
... 40 more lines ...
```

With Rootcast, you read this:

```
run refund-7af3  FAIL  refund issued outside the 30 day policy window

  step1  read_order     ok
  step2  lookup_policy  CAUSE  returned 2024 data, read_order is 2026
  step3  decide_refund  ok
  step4  issue_refund   FAIL   refund issued outside the 30 day policy window

  earliest divergence: step2
  chain: step2 -> step3 -> step4
  cause: lookup_policy: returned 2024 data, read_order is 2026, and that fed issue_refund

  flags:
    step2  WARN  stale       returned 2024 data, read_order is 2026
    step4  FAIL  step_error  refund issued outside the 30 day policy window
```

That is the real output of `rootcast audit examples/traces/stale_policy.rootcast.json`. Then prove it:

```
$ rootcast replay examples/traces/stale_policy.rootcast.json --agent examples/scenarios/stale_policy.py --set step2.output=policy_2026
replay refund-7af3  --set step2.output=policy_2026

  step1  read_order     unchanged   ok
  step2  lookup_policy  injected    ok
           output.source       "policy_2024" -> "policy_2026"
           output.window_days  90 -> 30
           output.year         2024 -> 2026
  step3  decide_refund  recomputed  ok
           inputs.policy.source       "policy_2024" -> "policy_2026"
           inputs.policy.window_days  90 -> 30
           inputs.policy.year         2024 -> 2026
           output.allowed             true -> false
           output.policy_source       "policy_2024" -> "policy_2026"
           output.window_days         90 -> 30
  step4  issue_refund   recomputed  FAIL -> ok
           inputs.decision.allowed        true -> false
           inputs.decision.policy_source  "policy_2024" -> "policy_2026"
           inputs.decision.window_days    90 -> 30
           output.status                  "issued" -> "denied"
           output.violation               "outside_window" -> null

  changed: step2, step3, step4
  untouched: step1
  run: FAIL -> PASS  (flipped)
```

Same run. One tells you what happened. The other tells you what to fix, and proves it: the agent decided correctly, but the policy lookup handed it the 2024 policy for a 2026 order. Swap in the 2026 policy and only the steps downstream of the lookup change, the order read stays untouched, and the run flips from FAIL to PASS. Both commands run as is from a clone of this repo.

<br/>

## Quickstart

Python:

```bash
pip install rootcast
```

```python
from rootcast import Recorder

rec = Recorder(run_id="refund-7af3")

with rec.step("read_order", kind="tool") as s:
    order = get_order(4417)
    s.output(order)

with rec.step("lookup_policy", kind="tool") as s:
    policy = search_policy("refund window")
    s.input({"query": "refund window"})
    s.output(policy)

rec.save("refund-7af3.rootcast.json")
```

Then, from the terminal:

```bash
rootcast view refund-7af3.rootcast.json
rootcast audit refund-7af3.rootcast.json
```

Node:

```bash
npm install rootcast
```

```js
import { Recorder } from "rootcast";

const rec = new Recorder({ runId: "refund-7af3" });

// Wrap a function: arguments become inputs, the return value the output.
const lookupPolicy = rec.record(searchPolicy, { kind: "tool" });
const policy = await lookupPolicy("refund window");

// Or record a block by hand.
await rec.step("decide_refund", { kind: "decision" }, (s) => {
  s.output(decide(order, policy));
});

rec.save("refund-7af3.rootcast.json");
```

Both SDKs write the same trace file, byte for byte, with the same inferred dependencies. One recorder format, any language, any framework. File naming and the multi run store are in [docs/trace-files.md](./docs/trace-files.md).

<br/>

## How it works

Rootcast has three layers. Each one is useful on its own, and they stack.

### Layer 1: Capture

A thin recorder wraps each step your agent takes. It records the inputs, the outputs, the model messages, the tool results, and the timing, into one portable trace file. The recorder never changes what your agent does. It only watches. Overhead is kept low by storing references and hashes for large payloads instead of copying them inline.

Supported out of the box: a generic context manager and decorator that fit any Python or Node agent, plus adapters for common frameworks (LangGraph, CrewAI, and the generic OpenAI and Anthropic tool loops). The trace schema is public and versioned, so you can emit it from anywhere.

### Layer 2: Causal engine

This is the detective. Given a trace, Rootcast builds a decision graph: every step becomes a node, and an edge means one step's output fed another step's decision. It then walks the graph backward from the failure to find the earliest divergence point, the first step whose output, had it been correct, would have changed everything downstream.

Each step is scored PASS, WARN, or FAIL, and the one step that most likely caused the failure is tagged CAUSE. This is not a keyword match on the logs. It is a dependency walk over what actually fed what.

### Layer 3: Replay

Finding the suspect is good. Proving it is better. Replay re-runs a trace with exactly one variable changed, for example the result of step 3, and reports whether the outcome flips from FAIL to PASS. Deterministic steps are served from the recorded cache so the replay is fast and cheap, and only the changed branch is recomputed. This turns "I think step 3 caused it" into "step 3 caused it, here is the proof."

<br/>

## The trace format

Everything in Rootcast is built on one small, stable JSON schema. If you can write this file, every Rootcast feature works on your agent, whatever stack you built it on.

```json
{
  "rootcast_version": "0.1",
  "run_id": "refund-7af3",
  "status": "fail",
  "steps": [
    {
      "id": "step3",
      "name": "lookup_policy",
      "kind": "tool",
      "inputs": { "query": "refund window" },
      "output_ref": "sha256:9f2c...",
      "depends_on": ["step1"],
      "started_at": 1730650800.21,
      "ended_at": 1730650800.63
    }
  ]
}
```

`depends_on` is the heart of the system. It is what lets the causal engine tell a step that merely ran before the failure from a step that actually fed the failure. When your framework does not declare dependencies, Rootcast infers them from data flow between inputs and outputs.

<br/>

## Why this is different

There are three kinds of tools in this space, and they do not overlap with Rootcast.

* Observability dashboards show you traces. They tell you what happened. They do not tell you which step caused the failure.
* Evaluation and benchmark tools score many runs against fixed tasks. They tell you a pass rate. They do not explain a single failed run.
* Guardrails block bad actions before they happen. They do not help once a quiet failure already slipped through.

Rootcast is the missing middle: it takes one real run that went wrong and gives you the cause and the fix, with proof.

<br/>

## Roadmap

* v0.1  Trace schema, Python and Node recorders, CLI viewer
* v0.2  Causal engine (decision graph, divergence detection, PASS WARN FAIL scoring)
* v0.3  Replay engine (single variable counterfactual, cached deterministic steps)
* v0.4  Web UI (interactive decision map, click to replay)
* v0.5  Framework adapters (LangGraph, CrewAI, OpenAI, Anthropic), published to PyPI and npm

See [planning-execute.md](./planning-execute.md) for the full phased build with task owners.

<br/>

## Contributing

Rootcast is Apache 2.0 and open to contributors. The trace schema in [docs/trace-schema.md](./docs/trace-schema.md) is the contract: anything that reads or writes it is a valid Rootcast tool. Start there.

<br/>

<div align="center">

Built by Amaresh Hebbar and Ashutosh.

</div>
