import { createHash } from "node:crypto";

/**
 * Cross language JSON encoding. Every Rootcast SDK must produce the same
 * bytes for the same logical value, see docs/trace-schema.md.
 *
 * Numbers use ECMAScript Number.prototype.toString, which is what
 * String(n) already does in JS. Strings use JSON.stringify escaping.
 * Keys sort by Unicode code point, not by UTF-16 unit.
 */

export function formatNumber(n: number): string {
  return Number.isFinite(n) ? String(n) : "null";
}

/** Compare two strings by Unicode code point, the order Python uses for str. */
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

/** Length in Unicode code points, the way Python len() counts a str. */
export function codePointLength(s: string): number {
  let n = 0;
  for (const _ of s) n += 1;
  return n;
}

/**
 * Marks a subtree whose object keys must be written sorted, even inside a
 * pretty printed file. Recorded payloads are always sorted, which keeps
 * integer like keys (that JS objects reorder) in the same place as Python.
 */
export class Sorted {
  constructor(readonly value: unknown) {}
}

export interface EncodeOptions {
  /** Spaces per level for the pretty file form. Omit for the compact form. */
  indent?: number;
  /** Sort object keys at every depth. */
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

/** Plain JSON copy of a value: toJSON applied, undefined and functions dropped, bigint as string. */
export function toPlain(value: unknown): unknown {
  const raw = JSON.stringify(value, (_k, v) => (typeof v === "bigint" ? v.toString() : v));
  return raw === undefined ? null : JSON.parse(raw);
}

/** Canonical compact form with sorted keys, as a string. */
export function canonicalJson(value: unknown): string {
  return encode(toPlain(value), { sortKeys: true });
}

/** Canonical form as UTF-8 bytes. */
export function canonicalBytes(value: unknown): Buffer {
  return Buffer.from(canonicalJson(value), "utf-8");
}

/** "sha256:" plus the lowercase hex sha256 of the canonical bytes. */
export function refOf(value: unknown): string {
  return "sha256:" + createHash("sha256").update(canonicalBytes(value)).digest("hex");
}

/** Detached snapshot of a value at record time, with keys in canonical order. */
export function snapshot(value: unknown): unknown {
  return JSON.parse(canonicalJson(value));
}
