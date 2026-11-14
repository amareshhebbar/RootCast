---
title: "Replay"
description: "Re run a recorded trace with one value changed and diff the outcome step by step."
---

`rootcast replay` proves a cause. It re runs a recorded trace with one value changed and reports, step by step, what changed and whether the run outcome flips.

```bash
rootcast replay <trace file or run id> --agent <agent.py> --set STEP.output[.path]=VALUE [--set ...] [--json]
```

## How a replay runs

Steps are walked in trace order. Each one ends up in one of three states:

| State | Meaning |
|---|---|
| `unchanged` | Its inputs are identical to the recording, so the recorded result is reused. Upstream steps always land here, and nothing is called. |
| `injected` | You set its output (or one of its inputs) with `--set`. |
| `recomputed` | A changed upstream output reached its inputs, so the agent's own function runs again with the rewritten inputs. |

Changed outputs flow downstream through the same data matching that dependency inference uses: anywhere a later step's input held the old value (or a part of it), it now holds the new one.

## External calls are never made

Steps of kind `tool`, `io` and `llm` are treated as external calls (an API, a database, a model). If one of them would need recomputing, replay stops with an error naming the step and asks for its result to be injected:

```
replay: step4 update_subscription is an external tool call and its inputs changed. Replay never calls out. Inject its result with --set step4.output=VALUE
```

An agent can declare a function safe to re run, a pure check or a sandboxed stand in, with `external=False`.

## The agent module

Traces hold data, not code, so recomputing needs the agent's functions. `--agent` points to a Python file that defines:

```python
from rootcast import Agent

def replay_agent(rec):
    # Build the same recorded functions, against the recorder replay passes in.
    read_order, lookup_policy, decide_refund, issue_refund = build(rec)
    agent = Agent()
    agent.add(read_order)
    agent.add(lookup_policy)
    agent.add(decide_refund)
    agent.add(issue_refund, external=False)  # only the policy check, no payment API
    return agent

# Optional named values usable as --set step2.output=policy_2026
REPLAY_VALUES = {"policy_2026": {...}}
```

The three sample scenarios in `examples/scenarios` each define both.

## Values for --set

`VALUE` is read as JSON when it parses (`30`, `true`, `{"a":1}`), else as a name from `REPLAY_VALUES`, else `@file.json` loads a file, else it is plain text. The step can be named by id (`step2`) or name (`lookup_policy`). `result` is accepted as an alias for `output`. A path after the target changes a single field: `--set step2.output.window_days=30`.

## The replay result

`replay()` returns a `ReplayResult`, and `--json` prints its `to_dict()`. This is the object the UI consumes:

```json
{
  "run_id": "refund-7af3",
  "injections": [{"step_id": "step2", "target": "output", "path": [], "value": {}, "spec": "step2.output=policy_2026"}],
  "status": {"before": "fail", "after": "pass", "flipped": true},
  "changed_steps": ["step2", "step3", "step4"],
  "steps": [
    {
      "step_id": "step4", "name": "issue_refund", "kind": "tool",
      "change": "recomputed", "changed": true,
      "status": {"before": "fail", "after": "pass"},
      "error": {"before": "refund issued outside the 30 day policy window", "after": null},
      "inputs": [{"path": "decision.allowed", "before": true, "after": false}],
      "output": [{"path": "status", "before": "issued", "after": "denied"}]
    }
  ],
  "replayed_trace": {"rootcast_version": "0.1", "...": "a schema valid trace of the replayed run"}
}
```

Replay never writes over the original trace. The replayed run is returned as a new trace whose `meta.replay_of` names the original run.
