# rootcast

The flight recorder for AI agents. Record why an agent made each choice, then find the exact step where it went wrong and prove the fix.

```bash
pip install rootcast
```

See it work on three real failed agent runs, no setup:

```bash
rootcast demo
rootcast audit rootcast-demo/stale_policy.rootcast.json
rootcast replay rootcast-demo/stale_policy.rootcast.json --set step2.output=policy_2026
rootcast serve --open
```

`audit` names the step that caused the failure. `replay` changes that one step and shows the run flip from FAIL to PASS. `serve` opens the decision map in your browser.

Record your own agent, decorator form, two lines of change:

```python
from rootcast import Recorder

rec = Recorder(run_id="refund-7af3")

@rec.record(kind="tool")
def lookup_policy(query):
    return search_policy(query)

lookup_policy("refund window")
rec.save("refund-7af3.rootcast.json")
```

Context manager form:

```python
with rec.step("lookup_policy", kind="tool") as s:
    s.input({"query": "refund window"})
    s.output(search_policy("refund window"))
```

Inside any recorded step, `current_step()` returns the live handle so the agent can set `status` or `error`. Dependencies between steps are inferred from data flow on save when you do not declare them.

```bash
rootcast view refund-7af3.rootcast.json
rootcast validate refund-7af3.rootcast.json
rootcast infer some-trace.rootcast.json
```

Full docs: https://github.com/amareshhebbar/rootcast
