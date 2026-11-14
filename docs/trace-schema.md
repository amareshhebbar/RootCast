# Rootcast trace schema

Version 0.1 (frozen)

A Rootcast trace is a single JSON object describing one agent run. Any tool that reads or writes this object is a valid Rootcast tool. The schema is intentionally small so it can be emitted from any language or framework.

Version 0.1 is frozen. Fields below will not be renamed or removed inside 0.1. New optional fields may only be added under `meta`. Any breaking change bumps `rootcast_version`.

## Top level

| Field | Type | Required | Meaning |
|---|---|---|---|
| rootcast_version | string | yes | Schema version, exactly "0.1" |
| run_id | string | yes | Stable id for this run |
| status | string | yes | One of pass, fail, unknown |
| steps | array | yes | Ordered list of step objects, in start order |
| meta | object | no | Free form run metadata (model, framework, env) |
| blobs | object | no | Map of ref hash to stored payload for large outputs |

## Step object

| Field | Type | Required | Meaning |
|---|---|---|---|
| id | string | yes | Unique step id inside the run |
| name | string | yes | Human readable step name |
| kind | string | yes | One of tool, llm, decision, io, custom |
| inputs | object | no | Inputs passed into the step |
| output | any | no | Inline output when small |
| output_ref | string | no | sha256 reference when the output is large, payload lives in blobs |
| depends_on | array | no | Step ids whose output fed this step |
| status | string | no | Per step status: pass, warn, fail, unknown |
| error | string | no | Error text if the step raised or was marked failed |
| started_at | number | no | Unix seconds |
| ended_at | number | no | Unix seconds, never before started_at |

A step carries either `output` or `output_ref`, never both.

## Validation rules

A trace is valid when all of the following hold:

1. `rootcast_version` is "0.1", `run_id` is a non empty string, `status` is a run status.
2. Every step has a unique non empty `id`, a non empty `name`, and a known `kind`.
3. `status`, when present, is a step status.
4. `inputs`, when present, is an object.
5. `output_ref`, when present, starts with `sha256:`. If `blobs` is present the ref must be a key in it.
6. `depends_on` only names steps that appear earlier in `steps`. No self references, no forward references. This keeps every trace a DAG in file order.
7. `started_at` and `ended_at` are numbers when present.

## Canonical encoding

Every SDK must produce identical bytes for the same logical payload. This is what makes hashes and dependency inference work across languages.

Canonical JSON, used for hashing and for the inline size check:

1. Object keys sorted by Unicode code point, at every depth (not by UTF 16 unit).
2. No whitespace. Separators are `,` and `:`.
3. Non ASCII characters written as UTF 8, not escaped. Strings escape `"`, `\`, and control characters below U+0020 the way JSON.stringify does (`\n`, `\t`, `\b`, `\f`, `\r`, otherwise `\u00xx` lowercase).
4. Numbers are written as ECMAScript `Number.prototype.toString` writes them, as in RFC 8785. A float with no fraction has no `.0` (`129.0` is `129`), exponents look like `1e-7` and `1e+21`, and NaN and infinities are `null`. JSON has one number type, so `129` and `129.0` are the same value and must be the same bytes.
5. Hash is `sha256:` followed by the lowercase hex sha256 of the canonical UTF 8 bytes.

The same number and string rules apply to the trace file itself. Shared test vectors for all of this live in `examples/conformance`.

Inline limit: if the canonical bytes of an output are longer than 2048 bytes, the step stores `output_ref` and the payload goes in `blobs` under that ref. Otherwise the output is inline.

Recorded values are snapshots taken at record time. A later mutation in the agent never changes the trace.

## File layout

Trace files are written as UTF 8 with two space indentation, `": "` after keys, LF line endings and a trailing newline. Recorded payloads (`inputs`, `output`, blob values) have their keys in canonical order. Top level keys appear in this order: rootcast_version, run_id, status, steps, meta, blobs. Step keys appear in this order: id, name, kind, inputs, output, output_ref, depends_on, status, error, started_at, ended_at. Fields that are null or an empty array are omitted.

Naming, blob placement and the multi run store are in [trace-files.md](./trace-files.md).

## Error text

When a step raises, recorders set `status` to `fail` and `error` to the exception class name, a colon, a space and the message, for example `TypeError: seats must be an integer, got str`. With an empty message the error is the class name alone. Text set explicitly by the agent is stored as given.

## Dependency semantics

`depends_on` separates ran before from fed into. A step that merely executed earlier is not a cause. A step whose output is consumed by a later decision is a candidate cause.

## Dependency inference

When a framework does not declare dependencies, Rootcast infers them from data flow. The Python and Node recorders run the same inference on save (`infer_dependencies` and `inferDependencies`), so they produce the same edges. Strings are measured in Unicode code points.

For each step with no declared `depends_on`, in file order:

1. Index every earlier step by the canonical hash of its whole output, of its `output_ref` string, and of every nested value inside its output that is not trivial.
2. Walk each input value top down. If the value hash matches an earlier step, link to the most recent such step and stop descending into that value. Otherwise descend into its children.
3. A producer only counts if it ended at or before the consumer started, when both timestamps exist.

A value is trivial when it is null, a boolean, a number, a string shorter than 8 characters, or an empty object or array. Trivial values never create a link, with one exception: a number passed as a whole top level input links to an earlier step whose whole output is that same number.

Declared dependencies are never removed. Inferred edges are listed in `meta.inferred_depends_on` as a map from step id to the ids that were added, so tools can draw them differently.

## Minimal valid example

```json
{
  "rootcast_version": "0.1",
  "run_id": "demo",
  "status": "fail",
  "steps": [
    { "id": "s1", "name": "read_order", "kind": "tool" },
    { "id": "s3", "name": "lookup_policy", "kind": "tool", "depends_on": ["s1"] }
  ]
}
```

## Sample traces

Three committed samples live in `examples/traces`, generated deterministically by `python examples/generate_traces.py`. `examples/traces/expected.json` records the failing step, the known injected cause, and the expected dependency graph for each. These are the regression spine for the causal engine and replay.

| Sample | Run id | Failure | Known cause |
|---|---|---|---|
| stale_policy | refund-7af3 | step4 issue_refund outside the real window | step2 lookup_policy returned the 2024 policy |
| rag_lookup | rag-21c9 | step4 check_answer finds the answer cites the adult doc | step2 retrieve ranked the adult doc first |
| tool_args | tool-58d2 | step4 update_subscription raises on seats | step3 plan_action emitted seats as a string |
