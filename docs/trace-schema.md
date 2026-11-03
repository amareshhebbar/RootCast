# Rootcast trace schema

Version 0.1

A Rootcast trace is a single JSON object describing one agent run. Any tool that reads or writes this object is a valid Rootcast tool. The schema is intentionally small so it can be emitted from any language or framework.

## Top level

| Field | Type | Required | Meaning |
|---|---|---|---|
| rootcast_version | string | yes | Schema version, currently "0.1" |
| run_id | string | yes | Stable id for this run |
| status | string | yes | One of pass, fail, unknown |
| meta | object | no | Free form run metadata (model, framework, env) |
| steps | array | yes | Ordered list of step objects |
| blobs | object | no | Map of ref hash to stored payload when payloads are inlined |

## Step object

| Field | Type | Required | Meaning |
|---|---|---|---|
| id | string | yes | Unique step id inside the run |
| name | string | yes | Human readable step name |
| kind | string | yes | One of tool, llm, decision, io, custom |
| inputs | object | no | Inputs passed into the step |
| output | any | no | Inline output when small |
| output_ref | string | no | Hash reference when the output is large |
| depends_on | array | no | Step ids whose output fed this step |
| status | string | no | Per step status: pass, warn, fail, unknown |
| error | string | no | Error text if the step raised |
| started_at | number | no | Unix seconds |
| ended_at | number | no | Unix seconds |

## Dependency semantics

`depends_on` separates ran before from fed into. A step that merely executed earlier is not a cause. A step whose output is consumed by a later decision is a candidate cause. When a framework does not declare dependencies, the causal engine infers them by matching step outputs to later step inputs.

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
