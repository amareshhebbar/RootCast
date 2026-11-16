# CLI

Both packages install a `rootcast` command. The Python one carries the engine (audit, replay, the UI). The Node one validates and lists traces. Traces are the same format either way, so the Python commands work on traces written from Node.

## Python

| Command | Does |
|---|---|
| `rootcast demo [DIR]` | writes the three sample failed runs to `DIR` (default `rootcast-demo`) and prints the next commands |
| `rootcast view <trace>` | prints each step and its status |
| `rootcast validate <trace>` | checks a trace against the schema, exits 1 when invalid |
| `rootcast audit <trace> [--baseline PATH] [--json]` | scores steps, names the cause, see [Audit](./audit.md) |
| `rootcast replay <trace or run id> [--agent FILE.py] --set STEP.output=VALUE [--json]` | re runs with a value changed, see [Replay](./replay.md) |
| `rootcast serve [--port N] [--agent FILE.py] [--traces DIR] [--open]` | starts the web UI and its local engine, see [Web UI](./ui.md) |
| `rootcast --version` | prints the version |

`python -m rootcast` works too. For the bundled sample runs, `replay` and `serve` use the replay agents shipped inside the package, so `--agent` is only needed for your own agents. `replay` takes a run id as well as a path, and looks it up in the trace store.

## Node

| Command | Does |
|---|---|
| `npx rootcast validate <trace...>` | validates one or more traces, exits 1 when any is invalid |
| `npx rootcast list [store]` | lists the traces in the trace store |

## Environment

| Variable | Meaning |
|---|---|
| `ROOTCAST_DIR` | root of the trace store, default `.rootcast` in the working directory |
