import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { TraceData, validate } from "./schema.js";

export const TRACE_SUFFIX = ".rootcast.json";
export const DEFAULT_STORE = ".rootcast";
export const STORE_ENV = "ROOTCAST_DIR";

export function safeRunId(runId: string): string {
  return runId.replace(/[^A-Za-z0-9._-]/g, "_") || "_";
}

export function storeRoot(root?: string): string {
  return root || process.env[STORE_ENV] || DEFAULT_STORE;
}

export function tracePath(runId: string, root?: string): string {
  return join(storeRoot(root), "runs", safeRunId(runId) + TRACE_SUFFIX);
}

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

export function readTrace(path: string): unknown {
  return JSON.parse(readFileSync(path, "utf-8"));
}

export function validateFile(path: string): string[] {
  let data: unknown;
  try {
    data = readTrace(path);
  } catch (err) {
    return ["cannot read trace: " + (err instanceof Error ? err.message : String(err))];
  }
  return validate(data);
}

export function loadTrace(path: string): TraceData {
  const data = readTrace(path);
  const errors = validate(data);
  if (errors.length > 0) throw new TraceValidationError(path, errors);
  return data as TraceData;
}
