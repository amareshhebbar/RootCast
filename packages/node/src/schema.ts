import { Sorted, encode, refOf } from "./canonical.js";

export { refOf };

export const ROOTCAST_VERSION = "0.1";

export type StepKind = "tool" | "llm" | "decision" | "io" | "custom";
export type StepStatus = "pass" | "warn" | "fail" | "unknown";
export type RunStatus = "pass" | "fail" | "unknown";

export const STEP_KINDS: ReadonlySet<string> = new Set(["tool", "llm", "decision", "io", "custom"]);
export const STEP_STATUS: ReadonlySet<string> = new Set(["pass", "warn", "fail", "unknown"]);
export const RUN_STATUS: ReadonlySet<string> = new Set(["pass", "fail", "unknown"]);

export const INLINE_LIMIT_BYTES = 2048;

export const STEP_FIELD_ORDER = [
  "id",
  "name",
  "kind",
  "inputs",
  "output",
  "output_ref",
  "depends_on",
  "status",
  "error",
  "started_at",
  "ended_at",
] as const;

export interface Step {
  id: string;
  name: string;
  kind: StepKind;
  inputs?: Record<string, unknown>;
  output?: unknown;
  output_ref?: string;
  depends_on?: string[];
  status?: StepStatus;
  error?: string;
  started_at?: number;
  ended_at?: number;
}

export interface TraceData {
  rootcast_version: string;
  run_id: string;
  status: RunStatus;
  steps: Step[];
  meta?: Record<string, unknown>;
  blobs?: Record<string, unknown>;
}

const PAYLOAD_FIELDS = new Set(["inputs", "output"]);

function omitted(value: unknown): boolean {
  return value === null || value === undefined || (Array.isArray(value) && value.length === 0);
}

/**
 * The trace file text: two space indent, trailing LF, keys in spec order,
 * null fields and empty depends_on omitted. Byte identical to the Python SDK.
 */
export function traceToJson(data: TraceData): string {
  const steps = data.steps.map((step) => {
    const out: Record<string, unknown> = {};
    const src = step as unknown as Record<string, unknown>;
    for (const key of STEP_FIELD_ORDER) {
      const value = src[key];
      if (omitted(value)) continue;
      out[key] = PAYLOAD_FIELDS.has(key) ? new Sorted(value) : value;
    }
    return out;
  });
  const top: Record<string, unknown> = {
    rootcast_version: data.rootcast_version,
    run_id: data.run_id,
    status: data.status,
    steps,
  };
  if (data.meta && Object.keys(data.meta).length > 0) {
    top.meta = data.meta;
  }
  if (data.blobs && Object.keys(data.blobs).length > 0) {
    const blobs: Record<string, unknown> = {};
    for (const [ref, payload] of Object.entries(data.blobs)) blobs[ref] = new Sorted(payload);
    top.blobs = blobs;
  }
  return encode(top, { indent: 2 }) + "\n";
}

function isObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isNumber(value: unknown): value is number {
  return typeof value === "number";
}

function nonEmptyString(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

/** Validate a parsed trace. Same rules and messages as the Python validator. */
export function validate(data: unknown): string[] {
  const errors: string[] = [];
  if (!isObject(data)) return ["trace must be a JSON object"];
  if (data.rootcast_version !== ROOTCAST_VERSION) {
    errors.push("rootcast_version must be " + ROOTCAST_VERSION);
  }
  if (!nonEmptyString(data.run_id)) errors.push("run_id is required");
  if (typeof data.status !== "string" || !RUN_STATUS.has(data.status)) {
    errors.push("status must be one of " + [...RUN_STATUS].sort().join(", "));
  }
  if ("meta" in data && !isObject(data.meta)) errors.push("meta must be an object");
  let blobs: Record<string, unknown> = {};
  if ("blobs" in data) {
    if (isObject(data.blobs)) blobs = data.blobs;
    else errors.push("blobs must be an object");
  }
  const hasBlobs = Object.keys(blobs).length > 0;
  if (!Array.isArray(data.steps)) {
    errors.push("steps must be an array");
    return errors;
  }

  const seen = new Set<string>();
  data.steps.forEach((step: unknown, i: number) => {
    const where = "steps[" + i + "]";
    if (!isObject(step)) {
      errors.push(where + " must be an object");
      return;
    }
    const sid = step.id;
    if (!nonEmptyString(sid)) errors.push(where + ".id is required");
    else if (seen.has(sid)) errors.push(where + ".id is duplicated: " + sid);
    if (!nonEmptyString(step.name)) errors.push(where + ".name is required");
    if (typeof step.kind !== "string" || !STEP_KINDS.has(step.kind)) errors.push(where + ".kind invalid");
    if ("status" in step && (typeof step.status !== "string" || !STEP_STATUS.has(step.status))) {
      errors.push(where + ".status invalid");
    }
    if ("inputs" in step && !isObject(step.inputs)) errors.push(where + ".inputs must be an object");
    if ("output" in step && "output_ref" in step) errors.push(where + " has both output and output_ref");
    const ref = step.output_ref;
    if (ref !== undefined && ref !== null) {
      if (typeof ref !== "string" || !ref.startsWith("sha256:")) {
        errors.push(where + ".output_ref must start with sha256:");
      } else if (hasBlobs && !(ref in blobs)) {
        errors.push(where + ".output_ref missing from blobs: " + ref);
      }
    }
    if ("error" in step && typeof step.error !== "string") errors.push(where + ".error must be a string");
    for (const key of ["started_at", "ended_at"]) {
      if (key in step && !isNumber(step[key])) errors.push(where + "." + key + " must be a number");
    }
    if (isNumber(step.started_at) && isNumber(step.ended_at) && step.ended_at < step.started_at) {
      errors.push(where + ".ended_at is before started_at");
    }
    let deps: unknown[] = [];
    if ("depends_on" in step) {
      if (Array.isArray(step.depends_on)) deps = step.depends_on;
      else errors.push(where + ".depends_on must be an array");
    }
    for (const dep of deps) {
      if (dep === sid) errors.push(where + ".depends_on references itself");
      else if (typeof dep !== "string" || !seen.has(dep)) {
        errors.push(where + ".depends_on unknown or later id: " + String(dep));
      }
    }
    if (nonEmptyString(sid)) seen.add(sid);
  });
  return errors;
}
