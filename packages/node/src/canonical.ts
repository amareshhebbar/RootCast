import { createHash } from "node:crypto";

export function formatNumber(n: number): string {
  return Number.isFinite(n) ? String(n) : "null";
}

export function compareCodePoints(a: string, b: string): number {
  if (a === b) return 0;
  const ia = a[Symbol.iterator]();
  const ib = b[Symbol.iterator]();
  for (;;) {
    const ca = ia.next();
    const cb = ib.next();
    if (ca.done) return cb.done ? 0 : -1;
    if (cb.done) return 1;
    const da = ca.value.codePointAt(0)!;
    const db = cb.value.codePointAt(0)!;
    if (da !== db) return da < db ? -1 : 1;
  }
}

export function codePointLength(s: string): number {
  let n = 0;
  for (const _ of s) n += 1;
  return n;
}

export class Sorted {
  constructor(readonly value: unknown) {}
}

export interface EncodeOptions {

  indent?: number;

  sortKeys?: boolean;
}

export function encode(value: unknown, opts: EncodeOptions = {}): string {
  return enc(value, opts.indent, opts.sortKeys === true, 0);
}

function enc(value: unknown, indent: number | undefined, sort: boolean, depth: number): string {
  if (value instanceof Sorted) {
    return enc(value.value, indent, true, depth);
  }
  if (value === null || value === undefined) return "null";
  switch (typeof value) {
    case "boolean":
      return value ? "true" : "false";
    case "number":
      return formatNumber(value);
    case "string":
      return JSON.stringify(value);
    case "bigint":
      return value.toString();
  }
  if (Array.isArray(value)) {
    const parts = value.map((v) => enc(v, indent, sort, depth + 1));
    return wrap("[", "]", parts, indent, depth);
  }
  if (typeof value === "object") {
    let keys = Object.keys(value as object).filter(
      (k) => (value as Record<string, unknown>)[k] !== undefined
    );
    if (sort) keys = keys.sort(compareCodePoints);
    const sep = indent === undefined ? ":" : ": ";
    const parts = keys.map(
      (k) => JSON.stringify(k) + sep + enc((value as Record<string, unknown>)[k], indent, sort, depth + 1)
    );
    return wrap("{", "}", parts, indent, depth);
  }
  return JSON.stringify(String(value));
}

function wrap(open: string, close: string, parts: string[], indent: number | undefined, depth: number): string {
  if (parts.length === 0) return open + close;
  if (indent === undefined) return open + parts.join(",") + close;
  const inner = "\n" + " ".repeat(indent * (depth + 1));
  return open + inner + parts.join("," + inner) + "\n" + " ".repeat(indent * depth) + close;
}

export function toPlain(value: unknown): unknown {
  const raw = JSON.stringify(value, (_k, v) => (typeof v === "bigint" ? v.toString() : v));
  return raw === undefined ? null : JSON.parse(raw);
}

export function canonicalJson(value: unknown): string {
  return encode(toPlain(value), { sortKeys: true });
}

export function canonicalBytes(value: unknown): Uint8Array {
  return new TextEncoder().encode(canonicalJson(value));
}

export function refOf(value: unknown): string {
  return "sha256:" + createHash("sha256").update(canonicalBytes(value)).digest("hex");
}

export function snapshot(value: unknown): unknown {
  return JSON.parse(canonicalJson(value));
}
