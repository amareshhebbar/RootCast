# rootcast

The flight recorder for AI agents. Record why an agent made each choice, then find the exact step where it went wrong and prove the fix.

```bash
pip install rootcast
```

Decorator form, two lines of change:

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
