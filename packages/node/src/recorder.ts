import { AsyncLocalStorage } from "node:async_hooks";
import { canonicalBytes, refOf, snapshot } from "./canonical.js";
import { inferDependencies } from "./infer.js";
import {
  INLINE_LIMIT_BYTES,
  ROOTCAST_VERSION,
  RunStatus,
  Step,
  StepKind,
  StepStatus,
  TraceData,
  traceToJson,
} from "./schema.js";
import { writeTraceFile, tracePath } from "./store.js";

export interface StepHandle {
  readonly id: string;
  input(data: Record<string, unknown>): void;
  output(value: unknown): void;
  dependsOn(...ids: string[]): void;
  status(value: StepStatus): void;
  error(message: string): void;
}

export interface StepOptions {
  kind?: StepKind;
  dependsOn?: string[];
  inputs?: Record<string, unknown>;
}

export interface RecordOptions {

  name?: string;
  kind?: StepKind;
  dependsOn?: string[];

  captureInputs?: boolean;

  params?: string[];

  exclude?: string[];
}

export interface RecorderOptions {
  runId: string;
  meta?: Record<string, unknown>;

  clock?: () => number;

  infer?: boolean;
}

const CURRENT = new AsyncLocalStorage<StepHandle>();

export function currentStep(): StepHandle | undefined {
  return CURRENT.getStore();
}

export function formatError(err: unknown): string {
  if (err instanceof Error) {
    return err.message ? err.name + ": " + err.message : err.name;
  }
  return String(err);
}

function isThenable(value: unknown): value is PromiseLike<unknown> {
  return (
    (typeof value === "object" || typeof value === "function") &&
    value !== null &&
    typeof (value as { then?: unknown }).then === "function"
  );
}

export class Recorder {
  readonly runId: string;
  readonly meta: Record<string, unknown>;
  private steps: Step[] = [];
  private blobs: Record<string, unknown> = {};
  private counter = 0;
  private runStatus: RunStatus = "unknown";
  private clock: () => number;
  private inferOnFinalize: boolean;

  constructor(opts: RecorderOptions) {
    this.runId = opts.runId;
    this.meta = { ...(opts.meta || {}) };
    this.clock = opts.clock || (() => Date.now() / 1000);
    this.inferOnFinalize = opts.infer !== false;
  }

  private open(name: string, opts: StepOptions): StepHandle {
    this.counter += 1;
    const step: Step = {
      id: "step" + this.counter,
      name,
      kind: opts.kind || "custom",
      depends_on: [...(opts.dependsOn || [])],
      status: "unknown",
      started_at: this.clock(),
    };
    this.steps.push(step);
    const handle = this.handleFor(step);
    if (opts.inputs !== undefined) handle.input(opts.inputs);
    return handle;
  }

  private handleFor(step: Step): StepHandle {
    const blobs = this.blobs;
    return {
      id: step.id,
      input(data) {
        step.inputs = snapshot(data) as Record<string, unknown>;
      },
      output(value) {
        if (canonicalBytes(value).length > INLINE_LIMIT_BYTES) {
          const ref = refOf(value);
          delete step.output;
          step.output_ref = ref;
          blobs[ref] = snapshot(value);
        } else {
          delete step.output_ref;
          step.output = snapshot(value);
        }
      },
      dependsOn(...ids) {
        const deps = step.depends_on || (step.depends_on = []);
        for (const id of ids) if (!deps.includes(id)) deps.push(id);
      },
      status(value) {
        step.status = value;
      },
      error(message) {
        step.error = message;
      },
    };
  }

  private run<T>(name: string, opts: StepOptions, body: (handle: StepHandle) => T): T {
    const handle = this.open(name, opts);
    const step = this.steps[this.steps.length - 1];
    const ok = () => {
      if (step.status === "unknown") step.status = "pass";
      step.ended_at = this.clock();
    };
    const fail = (err: unknown) => {
      step.status = "fail";
      step.error = formatError(err);
      step.ended_at = this.clock();
    };
    let result: T;
    try {
      result = CURRENT.run(handle, () => body(handle));
    } catch (err) {
      fail(err);
      throw err;
    }
    if (isThenable(result)) {
      return Promise.resolve(result).then(
        (value) => {
          ok();
          return value;
        },
        (err) => {
          fail(err);
          throw err;
        }
      ) as T;
    }
    ok();
    return result;
  }

  async step<T>(name: string, opts: StepOptions, fn: (handle: StepHandle) => Promise<T> | T): Promise<T>;
  async step<T>(name: string, fn: (handle: StepHandle) => Promise<T> | T): Promise<T>;
  async step<T>(
    name: string,
    optsOrFn: StepOptions | ((handle: StepHandle) => Promise<T> | T),
    maybeFn?: (handle: StepHandle) => Promise<T> | T
  ): Promise<T> {
    const opts = typeof optsOrFn === "function" ? {} : optsOrFn;
    const fn = typeof optsOrFn === "function" ? optsOrFn : maybeFn!;
    return await this.run(name, opts, fn);
  }

  record<F extends (...args: any[]) => any>(fn: F, opts: RecordOptions = {}): F {
    const label = opts.name || fn.name || "anonymous";
    const signature = opts.params ? { params: opts.params.map((name) => ({ name })) } : parseParams(fn);
    const excluded = new Set(opts.exclude || []);
    const capture = opts.captureInputs !== false;
    const rec = this;
    const wrapped = function (this: unknown, ...args: unknown[]) {
      const inputs = capture ? bindArgs(signature, args, excluded) : undefined;
      return rec.run(label, { kind: opts.kind, dependsOn: opts.dependsOn, inputs }, (handle) => {
        const result = fn.apply(this, args);
        if (isThenable(result)) {
          return Promise.resolve(result).then((value) => {
            handle.output(value);
            return value;
          });
        }
        handle.output(result);
        return result;
      });
    };
    Object.defineProperty(wrapped, "name", { value: fn.name });
    return wrapped as unknown as F;
  }

  mark(status: RunStatus): void {
    this.runStatus = status;
  }

  infer(): Record<string, string[]> {
    return inferDependencies(this.raw());
  }

  private raw(): TraceData {
    return {
      rootcast_version: ROOTCAST_VERSION,
      run_id: this.runId,
      status: this.runStatus,
      steps: this.steps,
      meta: this.meta,
      blobs: this.blobs,
    };
  }

  toData(): TraceData {
    if (this.inferOnFinalize) {
      const raw = this.raw();
      inferDependencies(raw);
    }
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
    if (Object.keys(this.meta).length > 0) data.meta = this.meta;
    if (Object.keys(this.blobs).length > 0) data.blobs = this.blobs;
    return data;
  }

  toJSONString(): string {
    return traceToJson(this.toData());
  }

  save(path?: string): string {
    const target = path || tracePath(this.runId);
    writeTraceFile(target, this.toJSONString());
    return target;
  }
}

interface Param {
  name: string;
  rest?: boolean;
  default?: { value: unknown };
}

interface Signature {
  params: Param[];
}

function bindArgs(sig: Signature | null, args: unknown[], excluded: Set<string>): Record<string, unknown> {
  const hasRest = sig !== null && sig.params.some((p) => p.rest);
  if (sig === null || (!hasRest && args.length > sig.params.length)) {
    return { args };
  }
  const out: Record<string, unknown> = {};
  sig.params.forEach((p, i) => {
    if (excluded.has(p.name)) return;
    if (p.rest) {
      out[p.name] = args.slice(i);
      return;
    }
    let value = args[i];
    if (value === undefined && p.default) value = p.default.value;
    if (value !== undefined) out[p.name] = value;
  });
  return out;
}

const IDENT = /^[A-Za-z_$][\w$]*$/;

export function parseParams(fn: Function): Signature | null {
  const src = Function.prototype.toString.call(fn).replace(/\/\*[\s\S]*?\*\/|\/\/[^\n]*/g, "");
  const arrow = /^(?:async\s+)?([A-Za-z_$][\w$]*)\s*=>/.exec(src);
  if (arrow) return { params: [{ name: arrow[1] }] };
  const start = src.indexOf("(");
  if (start < 0) return null;
  const parts: string[] = [];
  let depth = 0;
  let quote = "";
  let cur = "";
  for (let i = start + 1; i < src.length; i++) {
    const c = src[i];
    if (quote) {
      cur += c;
      if (c === "\\") cur += src[++i] ?? "";
      else if (c === quote) quote = "";
      continue;
    }
    if (c === '"' || c === "'" || c === "`") {
      quote = c;
      cur += c;
      continue;
    }
    if (c === "(" || c === "[" || c === "{") depth++;
    if (c === ")" || c === "]" || c === "}") {
      if (depth === 0) {
        if (cur.trim()) parts.push(cur.trim());
        break;
      }
      depth--;
    }
    if (c === "," && depth === 0) {
      parts.push(cur.trim());
      cur = "";
      continue;
    }
    cur += c;
  }
  const params: Param[] = [];
  for (const part of parts) {
    if (part.startsWith("...")) {
      const name = part.slice(3).trim();
      if (!IDENT.test(name)) return null;
      params.push({ name, rest: true });
      continue;
    }
    const eq = part.indexOf("=");
    const name = (eq < 0 ? part : part.slice(0, eq)).trim();
    if (!IDENT.test(name)) return null;
    const param: Param = { name };
    if (eq >= 0) {
      try {
        param.default = { value: JSON.parse(part.slice(eq + 1).trim()) };
      } catch {

      }
    }
    params.push(param);
  }
  return { params };
}
