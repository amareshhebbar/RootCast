# rootcast

The flight recorder for AI agents, for Node and TypeScript. Record why an agent made each choice, then find the exact step where it went wrong.

```bash
npm install rootcast
```

```js
import { Recorder } from "rootcast";

const rec = new Recorder({ runId: "refund-7af3" });
await rec.step("lookup_policy", { kind: "tool" }, async (s) => {
  const policy = await searchPolicy("refund window");
  s.output(policy);
  return policy;
});
rec.save("refund-7af3.rootcast.json");
```

Full docs: https://github.com/amareshhebbar/rootcast
