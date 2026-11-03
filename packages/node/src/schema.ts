import { createHash } from "crypto";

export const ROOTCAST_VERSION = "0.1";

export type StepKind = "tool" | "llm" | "decision" | "io" | "custom";
export type StepStatus = "pass" | "warn" | "fail" | "unknown";
export type RunStatus = "pass" | "fail" | "unknown";

export const INLINE_LIMIT_BYTES = 2048;

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
  meta?: Record<string, unknown>;
  steps: Step[];
  blobs?: Record<string, unknown>;
}

export function refOf(payload: unknown): string {
  const raw = JSON.stringify(payload);
  return "sha256:" + createHash("sha256").update(raw).digest("hex");
}

export function validate(data: TraceData): string[] {
  const errors: string[] = [];
  if (data.rootcast_version !== ROOTCAST_VERSION) {
    errors.push("rootcast_version must be " + ROOTCAST_VERSION);
  }
  if (!data.run_id) {
    errors.push("run_id is required");
  }
  const seen = new Set<string>();
  (data.steps || []).forEach((step, i) => {
    if (!step.id) {
      errors.push("steps[" + i + "].id is required");
    } else if (seen.has(step.id)) {
      errors.push("steps[" + i + "].id is duplicated: " + step.id);
    } else {
      seen.add(step.id);
    }
  });
  (data.steps || []).forEach((step, i) => {
    (step.depends_on || []).forEach((dep) => {
      if (!seen.has(dep)) {
        errors.push("steps[" + i + "].depends_on unknown id: " + dep);
      }
    });
  });
  return errors;
}
