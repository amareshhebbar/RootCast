import { codePointLength, refOf } from "./canonical.js";
import type { Step, TraceData } from "./schema.js";

/**
 * Data flow dependency inference. A line for line port of the Python
 * rootcast.infer module so both SDKs infer the same edges.
 * See "Dependency inference" in docs/trace-schema.md.
 */

export const MIN_STRING_LEN = 8;
export const META_KEY = "inferred_depends_on";

export interface InferOptions {
  /** Only infer for steps with no declared depends_on. Default true. */
  onlyUndeclared?: boolean;
  minStringLen?: number;
}

function isNumber(value: unknown): value is number {
  return typeof value === "number";
}

function isScalarTrivial(value: unknown, minLen: number): boolean {
  if (value === null || value === undefined || typeof value === "boolean") return true;
  if (isNumber(value)) return true;
  if (typeof value === "string") return codePointLength(value) < minLen;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value as object).length === 0;
  return false;
}

function isEmpty(value: unknown): boolean {
  if (value === null || value === undefined || typeof value === "boolean") return true;
  if (Array.isArray(value)) return value.length === 0;
  if (typeof value === "object") return Object.keys(value as object).length === 0;
  return false;
}

function children(value: unknown): unknown[] {
  if (Array.isArray(value)) return value;
  if (typeof value === "object" && value !== null) return Object.values(value);
  return [];
}

function* walk(value: unknown): Generator<unknown> {
  yield value;
  for (const child of children(value)) yield* walk(child);
}

function resolvedOutput(step: Step, blobs: Record<string, unknown>): unknown {
  if (step.output_ref !== undefined && step.output_ref in blobs) return blobs[step.output_ref];
  return step.output;
}

function outputHashes(step: Step, blobs: Record<string, unknown>, minLen: number): Set<string> {
  const hashes = new Set<string>();
  if (step.output_ref !== undefined) hashes.add(refOf(step.output_ref));
  const value = resolvedOutput(step, blobs);
  if (isEmpty(value)) return hashes;
  hashes.add(refOf(value));
  let root = true;
  for (const node of walk(value)) {
    if (root) {
      root = false;
      continue;
    }
    if (!isScalarTrivial(node, minLen)) hashes.add(refOf(node));
  }
  return hashes;
}

function finishedBefore(producer: Step, consumer: Step): boolean {
  if (producer.ended_at === undefined || consumer.started_at === undefined) return true;
  return producer.ended_at <= consumer.started_at;
}

type Produced = Array<[Step, Set<string>]>;

function latestProducer(produced: Produced, h: string, consumer: Step): Step | undefined {
  for (let i = produced.length - 1; i >= 0; i--) {
    const [producer, hashes] = produced[i];
    if (hashes.has(h) && finishedBefore(producer, consumer)) return producer;
  }
  return undefined;
}

function match(
  value: unknown,
  top: boolean,
  produced: Produced,
  consumer: Step,
  minLen: number,
  found: string[]
): void {
  const eligible = !isScalarTrivial(value, minLen) || (top && isNumber(value));
  if (eligible) {
    const producer = latestProducer(produced, refOf(value), consumer);
    if (producer !== undefined) {
      if (!found.includes(producer.id)) found.push(producer.id);
      return;
    }
  }
  for (const child of children(value)) match(child, false, produced, consumer, minLen, found);
}

/**
 * Fill depends_on from data flow, in place. Returns the edges that were
 * added, and records them under meta.inferred_depends_on.
 */
export function inferDependencies(trace: TraceData, opts: InferOptions = {}): Record<string, string[]> {
  const onlyUndeclared = opts.onlyUndeclared !== false;
  const minLen = opts.minStringLen ?? MIN_STRING_LEN;
  const blobs = trace.blobs || {};
  const produced: Produced = [];
  const inferred: Record<string, string[]> = {};
  const order = new Map(trace.steps.map((s, i) => [s.id, i]));
  const byOrder = (a: string, b: string) => (order.get(a) ?? 0) - (order.get(b) ?? 0);

  for (const step of trace.steps) {
    const declared = step.depends_on || [];
    if (!onlyUndeclared || declared.length === 0) {
      const found: string[] = [];
      for (const value of Object.values(step.inputs || {})) {
        match(value, true, produced, step, minLen, found);
      }
      const newIds = found.sort(byOrder).filter((id) => !declared.includes(id));
      if (newIds.length > 0) {
        step.depends_on = [...declared, ...newIds].sort(byOrder);
        inferred[step.id] = newIds;
      }
    }
    produced.push([step, outputHashes(step, blobs, minLen)]);
  }

  if (Object.keys(inferred).length > 0) {
    trace.meta = trace.meta || {};
    const prior = trace.meta[META_KEY];
    const existing: Record<string, string[]> =
      typeof prior === "object" && prior !== null && !Array.isArray(prior)
        ? (prior as Record<string, string[]>)
        : {};
    for (const [sid, ids] of Object.entries(inferred)) {
      const merged = [...(existing[sid] || [])];
      for (const dep of ids) if (!merged.includes(dep)) merged.push(dep);
      existing[sid] = merged;
    }
    trace.meta[META_KEY] = existing;
  }
  return inferred;
}
