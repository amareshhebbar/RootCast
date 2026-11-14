# rootcast

The flight recorder for AI agents, for Node and TypeScript. Record why an agent made each choice, then find the exact step where it went wrong.

```bash
npm install rootcast
```

## Record

Wrap the functions your agent calls. Arguments become the step inputs, the return value its output. Sync functions stay sync, async stay async.

```js
import { Recorder, currentStep } from "rootcast";

const rec = new Recorder({ runId: "refund-7af3", meta: { framework: "generic" } });

const readOrder = rec.record(async function read_order(order_id) {
  return db.orders.get(order_id);
}, { kind: "tool" });

const decideRefund = rec.record(function decide_refund(order, policy) {
  if (order.days > policy.window_days) currentStep().status("warn");
  return { allowed: order.days <= policy.window_days };
}, { kind: "decision" });

const order = await readOrder(4417);
decideRefund(order, policy);

rec.save(); // .rootcast/runs/refund-7af3.rootcast.json
```

Parameter names are read from the function source. Bundlers and minifiers rename them, so pass `params: ["order", "policy"]` for bundled code. `exclude` drops arguments such as secrets, and `captureInputs: false` records no inputs.

Or record a block by hand:

```js
await rec.step("lookup_policy", { kind: "tool", inputs: { query: "refund window" } }, async (s) => {
  const policy = await searchPolicy("refund window");
  s.output(policy);
  return policy;
});
```

A thrown error marks the step `fail` with `error` set to `Name: message`, then is rethrown. Outputs over 2048 bytes are stored once in the trace's `blobs` map by sha256. On save, `depends_on` is inferred from data flow for any step that did not declare it.

## Load and validate

```js
import { loadTrace, validateFile, listTraces } from "rootcast";

const errors = validateFile("refund-7af3.rootcast.json"); // [] when valid
const trace = loadTrace("refund-7af3.rootcast.json");     // throws TraceValidationError when invalid
```

```bash
npx rootcast validate .rootcast/runs/*.rootcast.json
npx rootcast list
```

## Same file as Python

Node and Python write byte identical traces for the same run, and each validates the other's files. See [trace-schema.md](https://github.com/amareshhebbar/rootcast/blob/main/docs/trace-schema.md) and [trace-files.md](https://github.com/amareshhebbar/rootcast/blob/main/docs/trace-files.md).

Full docs: https://github.com/amareshhebbar/rootcast
