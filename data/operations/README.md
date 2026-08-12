# Agent operations inbox

`data/operations/` is the Git-tracked transport between an AI agent using the
GitHub connector and the trusted GitHub Actions runner. It is not canonical job
data.

```text
connector → requests/<operation_id>.json → trusted GitHub Actions runner
                                              ├→ jobs.py → canonical CSV/cards
                                              ├→ render-tracker → docs/tracker.md
                                              └→ results/<operation_id>.json
                                                           ↓
                                              audited commit on main or agent/* PR
```

The connector may create exactly one new request per commit. It must not edit
`data/jobs.csv`, `data/job_sources.csv`, or a request that already exists. The
target branch controls delivery:

- `main` is the direct mode, used only for an explicit user instruction. The
  runner validates and commits the canonical result directly to `main`.
- `agent/<operation_id>` is the review mode. The runner commits to that branch
  and opens a PR to `main`.

The runner creates the matching result exactly once in either mode. It then
strictly validates the resulting dataset, regenerates and exact-checks
[`docs/tracker.md`](../../docs/tracker.md), runs the unit suite, enforces its
changed-file allowlist, and commits the result. `docs/tracker.md` is a generated
side effect of the trusted runner: the connector must neither edit nor include it
in a request.

## Connector procedure

1. Read the current canonical job and choose a supported domain command.
2. Choose `main` only after an explicit user instruction; otherwise create the
   request on `agent/<operation_id>` for review.
3. Add exactly one new file named
   `data/operations/requests/<operation_id>.json` in the commit. Do not edit
   canonical CSV, cards, `docs/tracker.md`, or an existing request.
4. Wait for the matching immutable result in `data/operations/results/` and the
   runner's canonical diff. A request is not complete merely because its JSON
   file was created.

For a completed operation the audited commit contains the immutable request and
result, any permitted canonical changes, and a fresh tracker page. For a
`conflict`, canonical data remains unchanged; the immutable result explains why
the request could not be applied.

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
filename. For commands that update an existing job, `expected` is a non-empty
optimistic lock: any mismatch records a `conflict` result without changing
canonical data. Include `last_update` and the state fields that the decision
depends on (for example `application_status`, `listing_status`, or
`decision_reason`). This v1 field-level lock is intentional; do not omit it to
make a request shorter.

Allowed single commands:

- `add`: has only `version`, `operation_id`, `command`, and `args`; `job_id` is
  assigned by `jobs.py` and `expected` is not used. It requires `company`,
  `role`, and `source`, accepts the canonical `jobs.py add` input fields, and
  permits only `application_status=not_started|reviewing`. External sources
  require `source_url` or `source_job_id`. Optional `duplicate_of` attaches the
  new source reference to an existing canonical job; optional boolean `force`
  explicitly resolves a fuzzy duplicate or shared discovery URL.

- `screen`: requires `decision_reason`; optional `notes`. It works only before
  application, clears the next action, and leaves listing/verification fields
  untouched. `closed_before_application` and `duplicate_listing` are forbidden.
- `verify`: requires `listing_status`, `first_party_verified`, and
  `apply_verified`; optional fields are `original_url`, `decision_reason`,
  `notes`, `level`, `remote_policy`, `stack`, `salary`, and `match_score`.
  A passed open verification may additionally set
  `application_status=apply` with a non-empty `next_action` (and optional
  `next_action_date`) when evidence shows that a person has already begun,
  but not submitted, the application process.
- `set`: only `next_action`, `next_action_date`, and
  `listing_status=closed` after a human application already exists.
- `status`: records an explicitly user-confirmed lifecycle event. It requires
  `application_status` and the literal boolean `confirmed_by_user=true`;
  optional fields are `stage`, `applied_at`, `response_at`, `decision_reason`,
  `next_action`, `next_action_date`, `cv_version`, and `notes`. It supports all
  canonical application statuses and remains subject to tracker date, stage,
  and transition invariants.

The agent must never infer a human event. `confirmed_by_user=true` is valid only
when the user explicitly reported or requested that lifecycle change. Every
`status` operation is medium risk and uses optimistic locking.

Example rejection request for an existing application:

```json
{
  "version": 1,
  "operation_id": "status-exampleco-rejected-20260812",
  "command": "status",
  "job_id": "job-0001",
  "expected": {
    "application_status": "applied",
    "last_update": "2026-08-11"
  },
  "args": {
    "application_status": "rejected",
    "confirmed_by_user": true
  }
}
```

Example new-job request:

```json
{
  "version": 1,
  "operation_id": "add-exampleco-frontend-20260811",
  "command": "add",
  "args": {
    "company": "ExampleCo",
    "role": "Frontend Developer",
    "source": "LinkedIn",
    "source_url": "https://www.linkedin.com/jobs/view/123",
    "original_url": "https://careers.example.com/jobs/frontend",
    "application_status": "reviewing",
    "listing_status": "open",
    "first_party_verified": "yes",
    "apply_verified": "yes",
    "remote_policy": "Europe",
    "stack": "React; TypeScript",
    "match_score": 8
  }
}
```

An unresolved fuzzy duplicate or a conflicting source reference produces an
immutable `conflict` result without adding a row. A confirmed duplicate is sent
as a new request with `duplicate_of`. Every `add` is classified as medium risk.

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
      "command": "screen",
      "job_id": "job-0099",
      "expected": {
        "application_status": "not_started",
        "listing_status": "unknown"
      },
      "args": {
        "decision_reason": "geo_restriction"
      }
    },
    {
      "command": "screen",
      "job_id": "job-0117",
      "expected": {
        "application_status": "not_started",
        "listing_status": "unknown"
      },
      "args": {
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

`add` is currently single-operation only and cannot be a batch child. `status`
can be a batch child, but every entry still requires `confirmed_by_user=true`.
Declarative ingest remains outside the current agent gateway.

`screen` and `set` are low-risk. `add`, `status`, and `verify` with enrichment
or a transition to `reviewing`/`apply` are medium-risk. A batch inherits the
highest risk of its children, so a screening-only batch remains low-risk.

## Runner contract

The Action invokes the checked-in trusted code, not a request-provided shell
string:

```bash
python3 scripts/agent_operations.py validate data/operations/requests/op-20260811-001.json
python3 scripts/agent_operations.py apply data/operations/requests/op-20260811-001.json --format json
```

`apply` delegates canonical writes to the same tracker functions as the manual
CLI, then writes one immutable result file. The workflow runs strict validation,
regenerates and exact-checks `docs/tracker.md`, runs all unit tests, checks the
changed-path allowlist, and then commits directly to `main` or opens a PR from
an `agent/` branch according to the delivery mode above.

The runner permits only these changed paths: `data/jobs.csv`,
`data/job_sources.csv`, `docs/tracker.md`, the expected immutable result, and
new `applications/job-*.md` cards. It rejects any operation that changes policy,
workflow, or executable files.
