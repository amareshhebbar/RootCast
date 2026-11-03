import { writeFileSync } from "fs";
import {
  Step,
  StepKind,
  StepStatus,
  TraceData,
  ROOTCAST_VERSION,
  INLINE_LIMIT_BYTES,
  refOf,
} from "./schema.js";

export interface StepHandle {
  input(data: Record<string, unknown>): void;
  output(value: unknown): void;
  dependsOn(...ids: string[]): void;
  status(value: StepStatus): void;
}

export interface StepOptions {
  kind?: StepKind;
  dependsOn?: string[];
}

export class Recorder {
  private runId: string;
  private meta: Record<string, unknown>;
  private steps: Step[] = [];
  private blobs: Record<string, unknown> = {};
  private counter = 0;
  private runStatus: "pass" | "fail" | "unknown" = "unknown";

  constructor(opts: { runId: string; meta?: Record<string, unknown> }) {
    this.runId = opts.runId;
    this.meta = opts.meta || {};
  }

  private nextId(): string {
    this.counter += 1;
    return "step" + this.counter;
  }

  private handleFor(step: Step): StepHandle {
    const blobs = this.blobs;
    return {
      input(data) {
        step.inputs = data;
      },
      output(value) {
        const raw = JSON.stringify(value);
        if (raw && raw.length > INLINE_LIMIT_BYTES) {
          const ref = refOf(value);
          step.output_ref = ref;
          blobs[ref] = value;
        } else {
          step.output = value;
        }
      },
      dependsOn(...ids) {
        step.depends_on = Array.from(new Set([...(step.depends_on || []), ...ids]));
      },
      status(value) {
        step.status = value;
      },
    };
  }

  async step<T>(
    name: string,
    opts: StepOptions,
    fn: (handle: StepHandle) => Promise<T> | T
  ): Promise<T> {
    const step: Step = {
      id: this.nextId(),
      name,
      kind: opts.kind || "custom",
      depends_on: opts.dependsOn || [],
      status: "unknown",
      started_at: Date.now() / 1000,
    };
    this.steps.push(step);
    const handle = this.handleFor(step);
    try {
      const result = await fn(handle);
      if (step.status === "unknown") {
        step.status = "pass";
      }
      return result;
    } catch (err) {
      step.status = "fail";
      step.error = String(err);
      throw err;
    } finally {
      step.ended_at = Date.now() / 1000;
    }
  }

  mark(status: "pass" | "fail" | "unknown"): void {
    this.runStatus = status;
  }

  toData(): TraceData {
    let status = this.runStatus;
    if (status === "unknown") {
      status = this.steps.some((s) => s.status === "fail") ? "fail" : "pass";
    }
    const data: TraceData = {
      rootcast_version: ROOTCAST_VERSION,
      run_id: this.runId,
      status,
      steps: this.steps,
    };
    if (Object.keys(this.meta).length > 0) {
      data.meta = this.meta;
    }
    if (Object.keys(this.blobs).length > 0) {
      data.blobs = this.blobs;
    }
    return data;
  }

  save(path: string): string {
    writeFileSync(path, JSON.stringify(this.toData(), null, 2), "utf-8");
    return path;
  }
}
