# rootcast

The flight recorder for AI agents. Record why an agent made each choice, then find the exact step where it went wrong and prove the fix.

```bash
pip install rootcast
```

```python
from rootcast import Recorder

rec = Recorder(run_id="refund-7af3")
with rec.step("lookup_policy", kind="tool") as s:
    s.input({"query": "refund window"})
    s.output(search_policy("refund window"))
rec.save("refund-7af3.rootcast.json")
```

```bash
rootcast view refund-7af3.rootcast.json
```

Full docs: https://github.com/amareshhebbar/rootcast
