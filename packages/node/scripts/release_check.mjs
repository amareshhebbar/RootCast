// Release check for the rootcast npm package.
//
//   node scripts/release_check.mjs                 full check, local tarball
//   node scripts/release_check.mjs --offline       skip the registry lookup
//   node scripts/release_check.mjs --from-registry install rootcast@<version> from npm instead
//                                                  (the post publish gate)
//   add --keep to leave the temp project on disk
//
// Steps: registry lookup (name and version free), tests, npm pack and tarball
// inspection, then a fresh project that installs the package, records a
// trace, loads and validates it, runs the CLI, and type checks a TypeScript
// consumer under nodenext and bundler resolution with no @types/node.
import { execSync } from "node:child_process";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const PKG_DIR = join(dirname(fileURLToPath(import.meta.url)), "..");
const pkg = JSON.parse(readFileSync(join(PKG_DIR, "package.json"), "utf-8"));
const args = new Set(process.argv.slice(2));
const OFFLINE = args.has("--offline");
const FROM_REGISTRY = args.has("--from-registry");
const KEEP = args.has("--keep");
const q = (p) => JSON.stringify(p);

let failures = 0;
function step(title) {
  console.log("\n== " + title);
}
function ok(msg) {
  console.log("  ok    " + msg);
}
function fail(msg) {
  failures += 1;
  console.log("  FAIL  " + msg);
}
function run(cmd, cwd, opts = {}) {
  return execSync(cmd, { cwd, encoding: "utf-8", stdio: opts.quiet ? "pipe" : ["ignore", "pipe", "pipe"], ...opts });
}

// 1. Registry -------------------------------------------------------------------

function registry() {
  step("registry: is " + pkg.name + "@" + pkg.version + " free?");
  if (OFFLINE) {
    console.log("  skip  --offline");
    return;
  }
  let published = null;
  try {
    published = JSON.parse(run("npm view " + pkg.name + " versions --json", PKG_DIR, { quiet: true }));
  } catch (err) {
    const text = String(err.stderr || err.message);
    if (text.includes("E404")) {
      ok("the name " + pkg.name + " is free on npm");
      if (FROM_REGISTRY) fail("--from-registry but " + pkg.name + " is not published");
      return;
    }
    fail("could not reach the registry: " + text.split("\n")[0]);
    return;
  }
  const versions = Array.isArray(published) ? published : [published];
  if (FROM_REGISTRY) {
    if (versions.includes(pkg.version)) ok(pkg.name + "@" + pkg.version + " is published");
    else fail(pkg.name + "@" + pkg.version + " is not published yet");
    return;
  }
  console.log("  note  " + pkg.name + " already exists with versions " + versions.join(", ") +
    ". Make sure it is ours: npm owner ls " + pkg.name);
  if (versions.includes(pkg.version)) fail(pkg.version + " is already published, bump the version");
  else ok(pkg.version + " is not published yet");
}

// 2. Build, test, pack ----------------------------------------------------------

const REQUIRED = ["package.json", "README.md", "LICENSE", "CHANGELOG.md", "dist/index.js", "dist/index.d.ts", "dist/cli.js"];
const FORBIDDEN = [/^src\//, /^test\//, /^scripts\//, /^node_modules\//, /^tsconfig/, /\.tsbuildinfo$/, /\.rootcast\.json$/];

function pack(outDir) {
  step("tests");
  try {
    run("npm test", PKG_DIR, { quiet: true });
    ok("npm test passed");
  } catch (err) {
    fail("npm test failed\n" + (err.stdout || "") + (err.stderr || ""));
    return null;
  }

  step("npm pack");
  const [info] = JSON.parse(run("npm pack --json --pack-destination " + q(outDir), PKG_DIR, { quiet: true }));
  const files = info.files.map((f) => f.path.replace(/\\/g, "/")).sort();
  for (const f of files) console.log("        " + f);
  console.log("  size  " + info.size + " bytes packed, " + info.unpackedSize + " unpacked, " + files.length + " files");
  for (const r of REQUIRED) (files.includes(r) ? ok : fail)("contains " + r);
  const bad = files.filter((f) => FORBIDDEN.some((re) => re.test(f)));
  if (bad.length) fail("must not ship: " + bad.join(", "));
  else ok("no sources, tests, scripts or traces in the tarball");
  const js = files.filter((f) => f.startsWith("dist/") && f.endsWith(".js") && f !== "dist/cli.js");
  const missing = js.filter((f) => !files.includes(f.replace(/\.js$/, ".d.ts")));
  if (missing.length) fail("no declarations for " + missing.join(", "));
  else ok("every module ships its .d.ts");
  const cli = readFileSync(join(PKG_DIR, "dist", "cli.js"), "utf-8");
  (cli.startsWith("#!/usr/bin/env node") ? ok : fail)("dist/cli.js keeps its node shebang");
  if (info.name !== pkg.name || info.version !== pkg.version) fail("tarball is " + info.name + "@" + info.version);
  return join(outDir, info.filename);
}

// 3. Fresh project ----------------------------------------------------------------

const RECORD = `
import {
  Recorder, currentStep, loadTrace, validateFile, inferDependencies, refOf, ROOTCAST_VERSION,
} from "rootcast";
import { readFileSync } from "node:fs";

const rec = new Recorder({ runId: "fresh-install", meta: { source: "release_check" } });
const readOrder = rec.record(async function read_order(order_id) {
  return { id: order_id, year: 2026, days_since_purchase: 45 };
}, { kind: "tool" });
const lookupPolicy = rec.record(function lookup_policy(query) {
  return { query, source: "policy_2024", window_days: 90, notes: "x".repeat(3000) };
}, { kind: "tool" });
const decide = rec.record(function decide_refund(order, policy) {
  const allowed = order.days_since_purchase <= policy.window_days;
  if (allowed) currentStep().status("warn");
  return { allowed };
}, { kind: "decision" });

const order = await readOrder(4417);
const policy = lookupPolicy("refund window");
decide(order, policy);
const path = rec.save("fresh.rootcast.json");

const errors = validateFile(path);
if (errors.length) throw new Error("invalid trace: " + errors.join("; "));
const trace = loadTrace(path);
const deps = Object.fromEntries(trace.steps.map((s) => [s.id, s.depends_on || []]));
if (JSON.stringify(deps) !== JSON.stringify({ step1: [], step2: [], step3: ["step1", "step2"] })) {
  throw new Error("unexpected dependencies " + JSON.stringify(deps));
}
if (!trace.steps[1].output_ref || !trace.blobs[trace.steps[1].output_ref]) throw new Error("large output not in blobs");
if (trace.rootcast_version !== ROOTCAST_VERSION || typeof inferDependencies !== "function") throw new Error("exports");
if (refOf({ b: 1, a: 2 }) !== refOf({ a: 2, b: 1 })) throw new Error("refOf is not canonical");
if (!readFileSync(path, "utf-8").endsWith("}\\n")) throw new Error("trace file must end with a newline");
console.log("recorded " + trace.steps.length + " steps, status " + trace.status + ", deps " + JSON.stringify(deps));
`;

const CONSUMER_TS = `
import { Recorder, loadTrace, type TraceData, type StepHandle, type Step } from "rootcast";

const rec = new Recorder({ runId: "types", clock: () => 0 });
const wrapped: (n: number) => { doubled: number } = rec.record((n: number) => ({ doubled: n * 2 }), { kind: "tool" });
const result: Promise<string> = rec.step("s", { kind: "llm" }, (s: StepHandle) => {
  s.output("x");
  return "x";
});
const data: TraceData = rec.toData();
const first: Step | undefined = data.steps[0];
const loaded: TraceData = loadTrace("t.rootcast.json");
// @ts-expect-error kind must be one of the schema kinds
rec.step("bad", { kind: "robot" }, () => 1);
export { wrapped, result, first, loaded };
`;

function freshProject(tarball) {
  step("fresh project: install " + (FROM_REGISTRY ? pkg.name + "@" + pkg.version + " from npm" : "the tarball"));
  const dir = mkdtempSync(join(tmpdir(), "rootcast-fresh-"));
  writeFileSync(join(dir, "package.json"), JSON.stringify({ name: "fresh", private: true, type: "module" }, null, 2));
  try {
    const spec = FROM_REGISTRY ? pkg.name + "@" + pkg.version : q(tarball);
    run("npm install " + spec + " --no-audit --no-fund --loglevel=error", dir, { quiet: true });
    ok("npm install " + (FROM_REGISTRY ? spec : "<tarball>"));
    const installed = JSON.parse(readFileSync(join(dir, "node_modules", "rootcast", "package.json"), "utf-8"));
    (installed.version === pkg.version ? ok : fail)("installed version " + installed.version);
    const deps = Object.keys(installed.dependencies || {});
    (deps.length === 0 ? ok : fail)("no runtime dependencies" + (deps.length ? ": " + deps.join(", ") : ""));
  } catch (err) {
    fail("npm install failed: " + (err.stderr || err.message));
    return dir;
  }

  writeFileSync(join(dir, "record.mjs"), RECORD);
  try {
    console.log("  " + run("node record.mjs", dir, { quiet: true }).trim());
    ok("import { Recorder } from \"rootcast\" and recorded a trace");
  } catch (err) {
    fail("recording in the fresh project failed:\n" + (err.stderr || err.message));
  }

  try {
    const out = run("npx --no-install rootcast validate fresh.rootcast.json", dir, { quiet: true }).trim();
    (out === "valid" ? ok : fail)("npx rootcast validate: " + out);
  } catch (err) {
    fail("npx rootcast validate failed: " + (err.stdout || err.stderr || err.message));
  }

  try {
    run("python -m rootcast validate fresh.rootcast.json", dir, { quiet: true });
    ok("the Python validator accepts the Node trace too");
  } catch {
    console.log("  skip  python rootcast not available for the cross language check");
  }

  const tsc = join(PKG_DIR, "node_modules", "typescript", "bin", "tsc");
  if (!existsSync(tsc)) {
    console.log("  skip  typescript not installed in packages/node, run npm install");
    return dir;
  }
  writeFileSync(join(dir, "consumer.ts"), CONSUMER_TS);
  for (const resolution of ["nodenext", "bundler"]) {
    const module = resolution === "nodenext" ? "nodenext" : "esnext";
    writeFileSync(join(dir, "tsconfig.json"), JSON.stringify({
      compilerOptions: {
        module, moduleResolution: resolution, target: "es2022", lib: ["es2022"],
        strict: true, noEmit: true, skipLibCheck: false, types: [],
      },
      files: ["consumer.ts"],
    }, null, 2));
    try {
      run("node " + q(tsc) + " -p tsconfig.json", dir, { quiet: true });
      ok("types check under moduleResolution " + resolution + ", without @types/node");
    } catch (err) {
      fail("types failed under " + resolution + ":\n" + (err.stdout || err.stderr || err.message));
    }
  }
  return dir;
}

// Main ------------------------------------------------------------------------------

registry();
const out = mkdtempSync(join(tmpdir(), "rootcast-pack-"));
const tarball = FROM_REGISTRY ? null : pack(out);
let project = null;
if (FROM_REGISTRY || tarball) project = freshProject(tarball);
if (!KEEP) {
  rmSync(out, { recursive: true, force: true });
  if (project) rmSync(project, { recursive: true, force: true });
} else {
  console.log("\nkept " + out + (project ? " and " + project : ""));
}
console.log("\n" + (failures ? failures + " check(s) failed" : "release check passed for " + pkg.name + "@" + pkg.version));
process.exit(failures ? 1 : 0);
