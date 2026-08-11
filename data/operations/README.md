# Agent operations inbox

`data/operations/` is the Git-tracked transport between an AI agent using the
GitHub connector and the trusted GitHub Actions runner. It is not canonical job
data.

```text
connector → requests/<operation_id>.json → GitHub Actions → jobs.py
                                                    └→ results/<operation_id>.json
```

The connector may create exactly one new request on a new `agent/<operation_id>`
branch. It must not edit `data/jobs.csv`, `data/job_sources.csv`, or a request
that already exists. The runner creates the matching result exactly once.

## Phase A request schema

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

`version`, `operation_id`, `command`, `job_id`, `expected`, and `args` are all
required. `operation_id` uses lowercase letters, digits, `.`, `_`, `-` and must
match the filename. `expected` is a non-empty optimistic lock: any mismatch
records a `conflict` result without changing canonical data.

Allowed commands:

- `verify`: requires `listing_status`, `first_party_verified`, and
  `apply_verified`; optional fields are `original_url`, `decision_reason`,
  `notes`, `level`, `remote_policy`, `stack`, `salary`, and `match_score`.
  A passed open verification may additionally set
  `application_status=apply` with a non-empty `next_action` (and optional
  `next_action_date`) when evidence shows that a person has already begun,
  but not submitted, the application process.
- `set`: only `next_action`, `next_action_date`, and
  `listing_status=closed` after a human application already exists.

`add`, batch operations, ingest and every submitted-application human-event
field are intentionally outside Phase A. In particular, a request cannot set
`application_status` to `applied`, `interviewing`, `offer`, or `withdrawn`, nor
change `applied_at` or `response_at`.

## Runner contract

The Action invokes the checked-in trusted code, not a request-provided shell
string:

```bash
python3 scripts/agent_operations.py validate data/operations/requests/op-20260811-001.json
python3 scripts/agent_operations.py apply data/operations/requests/op-20260811-001.json --format json
```

`apply` calls the same `jobs.py` functions as the manual CLI, then writes one
immutable result file. The workflow runs strict validation and all unit tests,
checks the changed-path allowlist, and opens a PR from the `agent/` branch.
