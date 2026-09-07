# Agent operations inbox

`data/operations/` is the Git-tracked transport between an AI agent using the
GitHub connector and the trusted GitHub Actions runner. It is not canonical job
data.

This contract starts after discovery and verification. The GitHub connector
does not provide arbitrary-site Browser access: a ChatGPT web workflow must use
the separately installed Browser plugin for source/ATS/Apply navigation, then
use this connector path only for repository reads and immutable writes. Web
search results do not satisfy Browser preflight or first-party verification.

[`contract.md`](contract.md) is the generated field-by-field reference: which
field each command accepts, its type and allowed values, which fields no
command accepts at all, and the cross-field invariants. It is assembled from
the same allowlists this document's schemas summarize below, so read it before
building an unfamiliar `args` object — a field or value it does not list is
rejected. Regenerate it with
`python3 scripts/agent_operations.py render-contract` after changing any
allowlist in `scripts/agent_operations.py`.

```text
connector → requests/<operation_id>.json → trusted GitHub Actions runner
                                              ├→ jobs.py → canonical CSV/cards
                                              ├→ render-tracker → docs/tracker.md
                                              └→ results/<operation_id>.json
                                                           ↓
                                              audited commit on main
```

The connector may create exactly one new request per commit. It must not edit
`data/jobs.csv`, `data/job_sources.csv`, or a request that already exists. Every
connector operation is delivered through `main`: the runner validates and
commits the canonical result directly to `main`. Operation branches and review
PRs are not part of this write path.

The runner creates the matching result exactly once. It then
strictly validates the resulting dataset, regenerates and exact-checks
[`docs/tracker.md`](../../docs/tracker.md), runs the unit suite, enforces its
changed-file allowlist, and commits the result. `docs/tracker.md` is a generated
side effect of the trusted runner: the connector must neither edit nor include it
in a request.

Operation `executed_at` values are exact UTC timestamps. Calendar fields written
to the tracker, including default `found_at`, `verified_at`, and `last_update`,
use `Europe/Belgrade` independently of the GitHub runner's process timezone.

## Connector procedure

1. Read the current canonical job and choose a supported domain command.
2. Create the request directly on `main`.
3. Add exactly one new file named
   `data/operations/requests/<operation_id>.json` in the commit. Do not edit
   canonical CSV, cards, `docs/tracker.md`, or an existing request.
4. Wait for the matching immutable result in `data/operations/results/` and the
   runner's canonical diff. A request is not complete merely because its JSON
   file was created.
5. Wait for the matching result and successful workflow on `main` before
   reporting completion.

For a completed operation the audited commit on `main` contains the immutable
request and result, any permitted canonical changes, and a fresh tracker page. For a
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
  explicitly resolves a fuzzy duplicate or shared discovery URL. **A
  `duplicate_of` add takes only the required fields plus a source reference**
  (`source_url`/`source_job_id`/`found_at`) and `force` — any other canonical
  field next to `duplicate_of` is rejected as `duplicate_add_extra_fields`,
  since it would silently be ignored on the existing job. See
  [`contract.md`](contract.md) for the exact field list of both forms.

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

## Phase B: batch

A batch declares an explicit `atomic` boolean and is capped by mode:
`atomic: true` allows at most **10** operations (a single conflicting child
still discards the whole batch, so the blast radius of one bad child is kept
small); `atomic: false` allows up to **100** and keeps whatever children
succeed instead of rolling everything back (P6, Э4 in
[`docs/agent-write-path-plan-2026-09-07.md`](../../docs/agent-write-path-plan-2026-09-07.md)).
Static schema validation is unconditional in both modes: a child that fails
contract validation rejects the whole request before anything is applied.
Only the three *runtime* outcomes — `unresolved_duplicate`,
`source_reference_conflict`, `stale_operation` — are partial under
`atomic: false`.

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
    },
    {
      "command": "add",
      "client_ref": "himalayas:example-guid",
      "args": {
        "company": "ExampleCo",
        "role": "Frontend Developer",
        "source": "Himalayas",
        "source_job_id": "example-guid",
        "decision_reason": "geo_restriction",
        "notes": "Remote is limited to the United States."
      }
    }
  ]
}
```

Batch guarantees:

- every child schema is checked before any canonical write, in both modes;
- duplicate existing-job `job_id` entries and duplicate add `client_ref` values
  are rejected, in both modes;
- children execute against an isolated tracker copy using the existing
  `jobs.py` write functions;
- the resulting dataset (the children that actually applied) is validated as a
  whole;
- the real tracker is replaced through one `jobs.apply_dataset_transaction`,
  only when at least one child applied;
- `atomic: true`: an optimistic-lock mismatch on any child, or an unresolved
  duplicate/source-reference conflict on any add child, discards every child
  and produces one `conflict` result — either `stale_operation` (checked
  up front, so no isolated copy work happens) or `batch_child_conflict`
  (raised while applying);
- `atomic: false`: the same two runtime conflicts are recorded on their own
  child instead, which is excluded from the applied set; every other child
  still applies. The result `status` is `completed` (every child applied),
  `partial` (some did), or `conflict` (none did — canonical data is
  unchanged, exactly as for a rejected atomic batch).

An `add` child has exactly `command`, a caller-assigned stable `client_ref`, and
`args`; it does not provide `job_id` or `expected`. IDs are allocated in child
order inside the isolated transaction and the immutable result maps each
`client_ref` to its assigned `job_id`. `status` can also be a batch child, but
every entry still requires `confirmed_by_user=true`. Declarative ingest
remains outside the current agent gateway.

Every conflicting child — in either mode, and in a single-operation `add` or
non-batch update too — carries a `retry` object with requests ready to resend
under a **new** `operation_id` (P5, Э4): `as_separate` resends the same args
with `force: true`; `as_duplicate` attaches a source reference to the job the
conflict unambiguously points at (omitted when a fuzzy duplicate matched more
than one candidate — the caller picks from `candidates` instead) for an add
conflict, or repeats the same `command`/`job_id`/`args` with `expected`
refreshed to the row's current values for a `stale_operation` conflict. Each
fragment validates on its own as a batch child or a single operation; it does
not carry `version`/`operation_id` since a retry always needs a fresh one.

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
changed-path allowlist, and pushes the audited commit directly to `main`.

The runner permits only these changed paths: `data/jobs.csv`,
`data/job_sources.csv`, `docs/tracker.md`, the expected immutable result, and
new `applications/job-*.md` cards. It rejects any operation that changes policy,
workflow, or executable files. A `rejected` result is the one exception: its
allowlist is exactly its own result file, since a rejected operation must not
touch canonical data.

The request must reach `main` as a direct, non-merge push. This is enforced
twice: `validate.yml` fails any pull request that touches
`data/operations/requests/**` before it can be merged, and the operation
workflow independently refuses to run against a merge commit. Both failures
say the same thing: this delivery path is not supported, commit the request
directly to `main`.

The final push to `main` can lose a race with another operation that pushed
first — `concurrency` on the operation workflow serializes the runs
themselves, but does not rebase an already-checked-out run onto the new tip.
`scripts/ci/apply_operation.sh` handles this without ever rebasing over
canonical data: on a non-fast-forward push it fetches and hard-resets to the
new `origin/main` (which already contains this run's own request commit),
deletes its own not-yet-pushed result file, and reapplies the same request
from scratch — up to three attempts. A reapply is also a correct re-check of
the optimistic lock: if the row changed in the meantime, the retry produces an
honest `conflict` result instead of silently overwriting it.

### Result status and the `rejected` shape

Every `apply` produces exactly one of four `status` values:

- `completed` — the operation applied; canonical data changed as described in
  `result`.
- `conflict` — an optimistic-lock mismatch or an unresolved duplicate; canonical
  data is unchanged.
- `partial` — `atomic: false` batch only: at least one child applied and at
  least one conflicted; canonical data reflects only the children that
  applied.
- `rejected` — the request failed contract validation, or an internal
  invariant broke before any canonical write; canonical data is unchanged.
  `risk` is `none`. Unlike `conflict`, a `rejected` result also makes the GitHub
  Actions run itself fail (non-zero exit): the run being red is what tells a
  human to look, since the agent already has the machine-readable reason in the
  result file.

A `rejected` result always carries a structured `error`:

```json
{
  "version": 1,
  "operation_id": "jaabz-20260907-frontend-pass-004",
  "status": "rejected",
  "command": "add",
  "executed_at": "2026-09-07T12:34:56Z",
  "risk": "none",
  "error": {
    "code": "unknown_args",
    "layer": "operations",
    "field": "args.next_action",
    "message": "unknown add args: next_action",
    "allowed": ["company", "role", "source", "..."],
    "hint": "create the job first, then send a separate set operation with next_action"
  }
}
```

`error.code` is one value from a closed set (`invalid_json`,
`request_too_large`, `filename_mismatch`, `unsupported_command`,
`unknown_top_level_fields`, `missing_top_level_fields`, `unknown_args`,
`missing_args`, `bad_type`, `bad_enum_value`, `bad_format`,
`duplicate_add_extra_fields`, `invariant_violation`, `unknown_job`,
`result_exists`, `batch_not_atomic`, `lost_before_apply`,
`contract_violation`); `layer` is `operations` for a contract violation caught
before any tracker call, or `jobs` for a rule enforced deeper in `jobs.py`.
`field`, `allowed`, and `hint` are present when they add information; only
`code`, `layer`, and `message` are guaranteed. A closed-set test keeps
`error.code` from growing new ad hoc values. `contract_violation` is the
generic fallback for a handful of `verify`/`set`/`screen` validation branches
that a later wave still has to migrate to a specific code; `lost_before_apply`
is written only by `scripts/maintenance/backfill_missing_results.py` for a
historical request that has no result even though it still passes contract
validation today.

`command` reflects the request's own top-level `command` field whenever the
raw JSON could be read at all, and is `unknown` only when it could not (for
example `invalid_json`).

**A rejected result is immutable, exactly like a completed or conflict one.**
Retrying a rejected operation means fixing the request and sending it under a
**new** `operation_id`; the runner refuses to overwrite an existing result
(`error.code: "result_exists"`), even a rejected one.
