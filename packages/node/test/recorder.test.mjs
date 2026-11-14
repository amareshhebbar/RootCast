import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  INLINE_LIMIT_BYTES,
  Recorder,
  TraceValidationError,
  currentStep,
  inferDependencies,
  listTraces,
  loadTrace,
  tracePath,
  validate,
  validateFile,
} from "../dist/index.js";

function clock() {
  let t = 0;
  return () => ++t;
}

test("record captures named inputs, output, status and timestamps", () => {
  const rec = new Recorder({ runId: "d", clock: clock() });
  const getOrder = rec.record(function get_order(order_id, region = "eu") {
    return { id: order_id, region };
  }, { kind: "tool" });
  assert.deepEqual(getOrder(7), { id: 7, region: "eu" });
  const [step] = rec.toData().steps;
  assert.equal(step.name, "get_order");
  assert.equal(step.kind, "tool");
  assert.deepEqual(step.inputs, { order_id: 7, region: "eu" });
  assert.deepEqual(step.output, { id: 7, region: "eu" });
  assert.equal(step.status, "pass");
  assert.equal(step.started_at, 1);
  assert.equal(step.ended_at, 2);
});

test("record keeps sync functions sync and async functions async", async () => {
  const rec = new Recorder({ runId: "d" });
  const syncFn = rec.record((x) => x + 1);
  const asyncFn = rec.record(async (x) => x + 1);
  assert.equal(syncFn(1), 2);
  const pending = asyncFn(1);
  assert.ok(pending instanceof Promise);
  assert.equal(await pending, 2);
});

test("record handles arrows, rest params, explicit params and extra args", () => {
  const rec = new Recorder({ runId: "d" });
  rec.record((a) => a)(1);
  rec.record(function many(first, ...rest) {})(1, 2, 3);
  rec.record(function renamed(a, b) {}, { params: ["order", "policy"] })(1, 2);
  rec.record(function one(a) {})(1, 2);
  rec.record(function picky(secret, keep) {}, { exclude: ["secret"] })("pw", "ok");
  rec.record(function quiet(a) {}, { captureInputs: false })(1);
  const inputs = rec.toData().steps.map((s) => s.inputs);
  assert.deepEqual(inputs, [
    { a: 1 },
    { first: 1, rest: [2, 3] },
    { order: 1, policy: 2 },
    { args: [1, 2] },
    { keep: "ok" },
    undefined,
  ]);
});

test("thrown errors fail the step with Name: message and rethrow", async () => {
  const rec = new Recorder({ runId: "d" });
  const boom = rec.record(function boom() {
    throw new TypeError("seats must be int");
  });
  assert.throws(() => boom(), TypeError);
  await assert.rejects(rec.step("async_boom", async () => {
    throw new Error("");
  }));
  const [a, b] = rec.toData().steps;
  assert.equal(a.status, "fail");
  assert.equal(a.error, "TypeError: seats must be int");
  assert.equal(b.error, "Error");
  assert.equal(rec.toData().status, "fail");
});

test("currentStep follows async context and nesting", async () => {
  const rec = new Recorder({ runId: "d" });
  assert.equal(currentStep(), undefined);
  const inner = rec.record(async function inner() {
    await new Promise((r) => setTimeout(r, 1));
    currentStep().status("warn");
    return currentStep().id;
  });
  const outer = rec.record(async function outer() {
    const id = await inner();
    currentStep().error("bad value");
    return [currentStep().id, id];
  });
  assert.deepEqual(await outer(), ["step1", "step2"]);
  const [o, i] = rec.toData().steps;
  assert.equal(o.error, "bad value");
  assert.equal(i.status, "warn");
});

test("snapshots are taken at record time", () => {
  const rec = new Recorder({ runId: "d" });
  const payload = { items: [1] };
  rec.record(function f(p) {
    return p;
  })(payload);
  payload.items.push(2);
  assert.deepEqual(rec.toData().steps[0].output, { items: [1] });
});

test("large outputs move to blobs by UTF-8 byte length", () => {
  const rec = new Recorder({ runId: "d" });
  // 1000 UTF-16 units but 3000 UTF-8 bytes: must be referenced, not inlined.
  const big = "日".repeat(1000);
  const small = "x".repeat(100);
  rec.record(function f() {
    return big;
  })();
  rec.record(function g() {
    return small;
  })();
  const data = rec.toData();
  const [a, b] = data.steps;
  assert.ok(Buffer.byteLength(JSON.stringify(big)) > INLINE_LIMIT_BYTES);
  assert.equal(a.output, undefined);
  assert.match(a.output_ref, /^sha256:[0-9a-f]{64}$/);
  assert.equal(data.blobs[a.output_ref], big);
  assert.equal(b.output, small);
  assert.deepEqual(validate(JSON.parse(rec.toJSONString())), []);
});

test("inference links through blobs and respects declared deps", () => {
  const rec = new Recorder({ runId: "d" });
  const big = { rows: Array.from({ length: 200 }, (_, i) => ({ row: i, label: "row-number-" + i })) };
  const produce = rec.record(function produce() {
    return big;
  });
  const consume = rec.record(function consume(row) {
    return row;
  });
  const declared = rec.record(function declared(data) {}, { dependsOn: ["step2"] });
  const rows = produce().rows;
  consume(rows[5]);
  declared(rows);
  const data = rec.toData();
  assert.ok(data.steps[0].output_ref);
  assert.deepEqual(data.steps[1].depends_on, ["step1"]);
  assert.deepEqual(data.steps[2].depends_on, ["step2"]);
  assert.deepEqual(data.meta.inferred_depends_on, { step2: ["step1"] });
});

test("inference matches a whole number output but ignores trivial nested values", () => {
  const trace = {
    rootcast_version: "0.1",
    run_id: "n",
    status: "pass",
    steps: [
      { id: "a", name: "count", kind: "tool", output: 42 },
      { id: "b", name: "flag", kind: "tool", output: { ok: true, n: 42 } },
      { id: "c", name: "use", kind: "tool", inputs: { n: 42, nested: { ok: true } } },
    ],
  };
  assert.deepEqual(inferDependencies(trace), { c: ["a"] });
});

test("inference ignores producers that had not finished", () => {
  const trace = {
    rootcast_version: "0.1",
    run_id: "t",
    status: "pass",
    steps: [
      { id: "a", name: "outer", kind: "tool", output: { k: "shared-value" }, started_at: 0, ended_at: 5 },
      { id: "b", name: "inner", kind: "tool", inputs: { k: "shared-value" }, started_at: 1, ended_at: 2 },
    ],
  };
  assert.deepEqual(inferDependencies(trace), {});
});

test("save defaults to the trace store and the loader validates", () => {
  const root = mkdtempSync(join(tmpdir(), "rootcast-"));
  const prev = process.env.ROOTCAST_DIR;
  process.env.ROOTCAST_DIR = root;
  try {
    const rec = new Recorder({ runId: "team/run 1" });
    rec.record(function f() {
      return 1;
    })();
    const path = rec.save();
    assert.equal(path, join(root, "runs", "team_run_1.rootcast.json"));
    assert.equal(path, tracePath("team/run 1"));
    assert.deepEqual(listTraces(), [path]);
    const text = readFileSync(path, "utf-8");
    assert.ok(text.endsWith("}\n") && !text.includes("\r"));
    assert.equal(loadTrace(path).run_id, "team/run 1");
    assert.deepEqual(validateFile(path), []);
  } finally {
    if (prev === undefined) delete process.env.ROOTCAST_DIR;
    else process.env.ROOTCAST_DIR = prev;
  }
});

test("loadTrace throws on invalid traces and validateFile reports bad JSON", async () => {
  const dir = mkdtempSync(join(tmpdir(), "rootcast-"));
  const bad = join(dir, "bad.rootcast.json");
  const { writeFileSync } = await import("node:fs");
  writeFileSync(bad, JSON.stringify({ rootcast_version: "0.1", run_id: "x", status: "pass", steps: [{ id: "a" }] }));
  assert.throws(() => loadTrace(bad), TraceValidationError);
  writeFileSync(bad, "{not json");
  assert.match(validateFile(bad)[0], /^cannot read trace: /);
});
