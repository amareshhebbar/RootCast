import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { TraceData, validate } from "./schema.js";

/**
 * On disk conventions, see docs/trace-files.md.
 *
 *   <store>/runs/<run_id>.rootcast.json
 *
 * The store is ROOTCAST_DIR, or .rootcast in the working directory.
 * Every file is self contained: large payloads live in its own blobs map.
 */

export const TRACE_SUFFIX = ".rootcast.json";
export const DEFAULT_STORE = ".rootcast";
export const STORE_ENV = "ROOTCAST_DIR";

export function safeRunId(runId: string): string {
  return runId.replace(/[^A-Za-z0-9._-]/g, "_") || "_";
}

export function storeRoot(root?: string): string {
  return root || process.env[STORE_ENV] || DEFAULT_STORE;
}

/** Conventional path of a run inside a trace store. */
export function tracePath(runId: string, root?: string): string {
  return join(storeRoot(root), "runs", safeRunId(runId) + TRACE_SUFFIX);
}

/** Paths of every trace in a store, sorted by file name. */
export function listTraces(root?: string): string[] {
  const dir = join(storeRoot(root), "runs");
  if (!existsSync(dir)) return [];
  return readdirSync(dir)
    .filter((f) => f.endsWith(TRACE_SUFFIX))
    .sort()
    .map((f) => join(dir, f));
}

export function writeTraceFile(path: string, text: string): void {
  mkdirSync(dirname(path), { recursive: true });
  writeFileSync(path, text, "utf-8");
}

export class TraceValidationError extends Error {
  constructor(readonly path: string, readonly errors: string[]) {
    super(path + " is not a valid trace: " + errors.join("; "));
    this.name = "TraceValidationError";
  }
}

/** Read and parse a trace file without validating it. */
export function readTrace(path: string): unknown {
  return JSON.parse(readFileSync(path, "utf-8"));
}

/** Validate a trace file. Returns errors, empty when valid. Unreadable or non JSON files are errors too. */
export function validateFile(path: string): string[] {
  let data: unknown;
  try {
    data = readTrace(path);
  } catch (err) {
    return ["cannot read trace: " + (err instanceof Error ? err.message : String(err))];
  }
  return validate(data);
}

/** Load a trace file, throwing TraceValidationError when it is not valid. */
export function loadTrace(path: string): TraceData {
  const data = readTrace(path);
  const errors = validate(data);
  if (errors.length > 0) throw new TraceValidationError(path, errors);
  return data as TraceData;
}
