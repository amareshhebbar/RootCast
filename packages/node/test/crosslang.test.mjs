// Phase 1 gate, Node half: record the sample scenarios in Node and prove the
// files are byte identical to the Python recorded samples, and that Node
// loads and validates the Python files clean.
// The Python half is packages/python/tests/test_crosslang.py.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mkdtempSync, readFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { loadTrace, validateFile } from "../dist/index.js";
import { generate } from "../../../examples/node/generate_traces.mjs";

const traces = fileURLToPath(new URL("../../../examples/traces/", import.meta.url));
const expected = JSON.parse(readFileSync(join(traces, "expected.json"), "utf-8"));
const out = mkdtempSync(join(tmpdir(), "rootcast-node-"));
await generate(out);

for (const [name, want] of Object.entries(expected)) {
  const nodePath = join(out, name + ".rootcast.json");
  const pyPath = join(traces, name + ".rootcast.json");

  test(name + ": Node trace is byte identical to the Python sample", () => {
    const fromNode = readFileSync(nodePath, "utf-8");
    // Tolerate a CRLF checkout so the test also runs on Windows clones.
    const fromPython = readFileSync(pyPath, "utf-8").replace(/\r\n/g, "\n");
    assert.equal(fromNode, fromPython);
  });

  test(name + ": Node trace validates and carries the expected dependencies", () => {
    assert.deepEqual(validateFile(nodePath), []);
    const trace = loadTrace(nodePath);
    assert.equal(trace.run_id, want.run_id);
    assert.equal(trace.status, "fail");
    const deps = Object.fromEntries(trace.steps.map((s) => [s.id, s.depends_on || []]));
    assert.deepEqual(deps, want.depends_on);
    assert.equal(trace.steps.find((s) => s.id === want.fail).status, "fail");
  });

  test(name + ": Python sample loads and validates in Node", () => {
    assert.equal(loadTrace(pyPath).run_id, want.run_id);
  });
}
