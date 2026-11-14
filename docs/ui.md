---
title: "Web UI"
description: "The decision map: load a trace, see the cause highlighted, click to replay."
---

A decision map of one run: every step a node, every edge "this output fed that step", colored by score, with the root cause highlighted and replay one click away.

```bash
rootcast serve --open
```

That starts the local engine on `http://127.0.0.1:8765/` and opens the UI. Everything after that happens in the browser.

## Using it

1. Drop a `*.rootcast.json` file anywhere on the page, use **Open trace**, or pick a sample.
2. The banner says whether the run failed, what the symptom was, the cause and the chain from cause to failure.
3. The map colors each step ok, WARN or FAIL. The root cause has a purple pulsing outline and a **ROOT CAUSE** label, and the chain edges are drawn in purple. Dashed edges were inferred from data flow, solid ones were declared.
4. Click a step (or Tab to it and press Enter) to see why it was scored that way, its error, inputs, output and what fed it.
5. In **Replay with a different output**, pick a named value or edit the JSON, then **Run replay**. The banner flips to PASS when the change fixes the run, and the map switches to **After replay**: injected steps are dashed blue, recomputed steps show their new status, unchanged steps fade. Click any step to see the before and after diff. **Original run** switches back.

When a replay would have to call an external tool, io or llm step, the panel shows the error and a button to set a result for that step instead. Replay never calls out.

## One engine, two front doors

The page never reimplements anything. It posts the trace to the local engine, which runs the same `audit()` and `replay()` as the CLI, so `rootcast replay` and the UI always agree (a test asserts it).

| Endpoint | Does |
|---|---|
| `GET /api/info` | version, sample traces, loaded replay agents |
| `GET /api/sample?name=` | one sample trace |
| `POST /api/audit` | `{"trace": ...}` to audit, graph edges and the matching agent |
| `POST /api/replay` | `{"trace": ..., "sets": ["step2.output=..."]}` to the replay result and the audit of the replayed run |

The engine binds to 127.0.0.1 only. Traces are analysed in memory and not written anywhere.

## Options

```bash
rootcast serve --port 9000 --agent my_agent.py --traces runs/ --open
```

* `--agent` loads a replay agent (a file with `replay_agent(rec)`, see [replay.md](./replay.md)). Repeat for several. The UI picks the agent that registers the trace's step names. By default the repo's `examples/scenarios` are loaded when run from a checkout.
* `--traces` adds folders whose traces are offered as samples. The trace store (`.rootcast/runs`) and `examples/traces` are included automatically.

## Links

A replay can be shared as a link: `/?sample=stale_policy&set=step2.output%3Dpolicy_2026&step=step3` opens the sample, runs the replay and selects step 3.
