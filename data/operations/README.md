# Agent operations inbox

`data/operations/` is the Git-tracked transport between an AI agent using the
GitHub connector and the trusted GitHub Actions runner. It is not canonical job
data.

```text
connector → requests/<operation_id>.json → GitHub Actions → jobs.py
                                                    └→ results/<operation_id>.json
```

The connector may create exactly one new request per commit. It must not edit
`data/jobs.csv`, `data/job_sources.csv`, or a request that already exists. The
target branch controls delivery:

- `main` is the direct mode, used only for an explicit user instruction. The
  runner validates and commits the canonical result directly to `main`.
- `agent/<operation_id>` is the review mode. The runner commits to that branch
  and opens a PR to `main`.

The runner creates the matching result exactly once in either mode.

## Single-operation schema

```json
{
  "version": 1,
  "operation_id": "op-20260811-001",
  "command": "verify",
  "job_id": "job-0122",
  "expected": {
    "application_status": "not_started",
    "last_update": "2026-08-11"
  },
  "args": {
    "listing_status": "closed",
    "first_party_verified": "yes",
    "apply_verified": "no",
    "decision_reason": "closed_before_application"
  }
}
```

`operation_id` uses lowercase letters, digits, `.`, `_`, `-` and must match the
filename. `expected` is a non-empty optimistic lock: any mismatch records a
`conflict` result without changing canonical data.

Allowed child commands:

- `verify`: requires `listing_status`, `first_party_verified`, and
  `apply_verified`; optional fields are `original_url`, `decision_reason`,
  `notes`, `level`, `remote_policy`, `stack`, `salary`, and `match_score`.
  A passed open verification may additionally set
  `application_status=apply` with a non-empty `next_action` (and optional
  `next_action_date`) when evidence shows that a person has already begun,
  but not submitted, the application process.
- `set`: only `next_action`, `next_action_date`, and
  `listing_status=closed` after a human application already exists.

Submitted-application human-event fields remain forbidden. A request cannot set
`application_status` to `applied`, `interviewing`, `offer`, or `withdrawn`, nor
change `applied_at` or `response_at`.

## Phase B: atomic batch

A batch contains up to 100 unique job operations and must explicitly opt into
atomic execution:

```json
{
  "version": 1,
  "operation_id": "himalayas-review-20260811",
  "command": "batch",
  "atomic": true,
  "operations": [
    {
      "command": "verify",
      "job_id": "job-0099",
      "expected": {
        "application_status": "not_started",
        "last_update": "2026-08-11"
      },
      "args": {
        "listing_status": "open",
        "first_party_verified": "no",
        "apply_verified": "no",
        "decision_reason": "geo_restriction"
      }
    },
    {
      "command": "verify",
      "job_id": "job-0117",
      "expected": {
        "application_status": "not_started",
        "last_update": "2026-08-11"
      },
      "args": {
        "listing_status": "open",
        "first_party_verified": "no",
        "apply_verified": "no",
        "decision_reason": "seniority_too_high"
      }
    }
  ]
}
```

Batch guarantees:

- every child schema and every optimistic-lock precondition is checked before
  any canonical write;
- duplicate `job_id` entries are rejected;
- children execute against an isolated tracker copy using the existing
  `jobs.py` write functions;
- the resulting dataset is validated as a whole;
- the real tracker is replaced through one `jobs.apply_dataset_transaction`;
- if a child fails after previous children have run in the isolated copy, the
  canonical dataset remains unchanged;
- one immutable result records either `atomic_batch_applied` or the complete
  stale-operation conflict list.

`add` and declarative ingest are still outside the current agent gateway and can
be added as later Phase B extensions without changing this batch contract.

## Runner contract

The Action invokes the checked-in trusted code, not a request-provided shell
string:

```bash
python3 scripts/agent_operations.py validate data/operations/requests/op-20260811-001.json
python3 scripts/agent_operations.py apply data/operations/requests/op-20260811-001.json --format json
```

`apply` delegates canonical writes to the same tracker functions as the manual
CLI, then writes one immutable result file. The workflow runs strict validation
and all unit tests, checks the changed-path allowlist, then either commits
directly to `main` or opens a PR from an `agent/` branch according to the
delivery mode above.
