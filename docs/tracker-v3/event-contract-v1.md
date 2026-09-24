# Application event contract v1

Статус: контракт WP1.1–WP1.4 проверен на fixtures. CLI и connector commands
реализованы, но production writes закрыты feature gate до отдельного cutover.

## Storage and identity

- Canonical target path after a later cutover:
  `data/application_events/job-NNNN.jsonl`. One complete JSON object per line,
  UTF-8, newline `\n`, no blank lines. Filename `job_id` and row `job_id` must
  agree. Existing lines are never edited or reordered; correction appends a row.
  Canonical rows are retained for the lifetime of the tracker; there is no
  event deletion or compaction in v1.
- `event_id` is a globally unique idempotency key. The manual CLI caller supplies
  it; the connector derives it from its immutable single `operation_id`.
  Retrying with the same ID and identical content returns the original result;
  same ID with different content is a conflict. A content hash cannot replace
  the ID because two real follow-ups can have equal payloads.
- File order is `(recorded_at, event_id)` ascending. `recorded_at` is a UTC
  instant ending in `Z`; equal timestamps are ordered by `event_id`. The
  business `occurred_at` may be older than `recorded_at`.
- A full dataset scan checks cross-file ID uniqueness; a targeted job read
  checks all local invariants. Normal agent bootstrap does not scan the ledger.

Benchmark method: `python3 scripts/maintenance/bench_event_layouts.py` writes
only synthetic events to a temporary directory and measures three read passes.
On 2026-09-23, 10k events across 100 jobs yielded:

| Layout | Files | Full scan | One job lookup | Git/transaction consequence |
|---|---:|---:|---:|---|
| One JSONL | 1 | 13.41 ms | 13.57 ms | global hot file; every event replaces it |
| Per-job JSONL | 100 | 15.18 ms | 0.16 ms | one readable line in one job file; transaction touches that file |
| Per-event JSON under job dirs | 10,000 | 226.53 ms | 1.90 ms | many small files and Git entries |

These timings are local observations, not performance guarantees. All layouts
stored the same 1,510,000 JSON bytes. Per-job JSONL balances targeted access,
full validation and reviewable Git diffs; the production transaction and crash
recovery remain B-003.

## Exact event shape

Every row has exactly these keys (nullable keys are still present):

```json
{
  "schema_version": 1,
  "event_id": "op-example-001",
  "job_id": "job-0001",
  "event_type": "application_submitted",
  "occurred_at": "2026-09-23",
  "precision": "date",
  "recorded_at": "2026-09-23T12:00:00Z",
  "source": "manual",
  "actor": "user",
  "confirmed_by_user": true,
  "evidence_ref": null,
  "payload": {},
  "supersedes": null
}
```

- `event_id`: 1–128 ASCII letters/digits/`._:-`, first character alphanumeric.
- `job_id`: existing `job-NNNN` (four or more digits).
- `event_type`: closed enum in the table below.
- `precision=date`: `occurred_at` is a real `YYYY-MM-DD`.
  `precision=instant`: aware RFC 3339 timestamp with an offset or `Z`.
  `precision=unknown`: `occurred_at=null`. All events that change the snapshot
  require `date` or `instant`, except `event_voided` which requires `unknown`.
- `recorded_at`: aware UTC RFC 3339 timestamp using `Z`.
- `source`: `manual|connector|migration`; `actor`: `user|agent|migration`.
  `source=migration` requires `actor=migration` and
  `confirmed_by_user=false`; all other events require explicit
  `confirmed_by_user=true`. An inbox adapter cannot emit a canonical row.
- `evidence_ref`: null or a non-empty single-line reference, maximum 500 chars.
  It is a locator, not copied evidence or a credential.
- `payload`: exact type-specific keys below; no arbitrary extra fields.
- `supersedes`: null or an earlier `event_id` in the same job. A correction is
  a full replacement business event with `supersedes`; `event_voided` removes
  a wrong fact without inventing a replacement.

## Event types and payload

| Event type | Payload | Snapshot effect |
|---|---|---|
| `application_submitted` | `{}` | status `applied`, stage `Applied`, `applied_at` |
| `acknowledgement_received` | `{}` | none; acknowledgement is not a substantive response |
| `response_received` | `{}` | candidate for first `response_at` |
| `assessment_invited` / `assessment_completed` | `assessment_id` | stage `Test task`; invitation is substantive response |
| `interview_scheduled` / `interview_completed` / `interview_cancelled` | `round_id`, `round_kind`; `stage_hint` only for `other` | scheduled/completed set status `interviewing` and stage; cancellation is informational |
| `offer_received` | `{}` | status `offer`, stage `Offer`, substantive response |
| `rejection_received` | `{}` | status `rejected`, substantive response |
| `candidate_withdrew` | `{}` | status `withdrawn` |
| `no_response_closed` | `{}` | status `ghosted` |
| `follow_up_sent` | `{}` | none |
| `event_voided` | `{}` plus required `supersedes` | removes one wrong event from effective history |

`assessment_id` and `round_id` use the same identifier syntax as `event_id`.
`round_kind` is `recruiter|technical|final|other`; `stage_hint` for `other`
must be one of `Recruiter screen|Tech interview|Test task|Final interview`.
Rescheduling appends another `interview_scheduled` for the same `round_id`.
Accepted event types are deliberately narrower than the brainstorming list in
the implementation plan. Further types need a versioned contract change.

## Correction and effective order

1. `supersedes` points to a previously recorded event in the same job. Each
   event may have at most one direct successor. Chains may be extended, never
   forked or cyclic.
2. The final event in a chain is effective unless it is `event_voided`; all
   earlier versions stay visible in the audit timeline.
3. An effective correction occupies its chain root's *logical slot* for
   lifecycle projection. Thus a later correction of an early interview does
   not accidentally reopen an application after a later rejection. Its own
   `occurred_at` supplies its business date; its `recorded_at` remains the audit
   time. This also permits correction of type and time.
4. `stage_reached` is the maximum stage of effective events. A correction can
   lower a previously erroneous maximum; ordinary new events cannot.

## Pure projection

Projection reads effective events by root slot; it does not write the snapshot.
An application must have exactly one effective `application_submitted` before
other business events. `applied_at` is its Europe/Belgrade business date.
`response_at` is the earliest business date of a substantive response:
`response_received`, assessment invitation/completion, interview scheduling/
completion, offer or rejection. Acknowledgements and candidate actions do not
set it. Date-only precision never becomes a synthetic midnight instant.

`stage_reached` uses the current schema order: `None`, `Applied`, `Recruiter
screen`, `Tech interview`, `Test task`, `Final interview`, `Offer`. An assessment
can precede an interview while the historical maximum remains `Test task`.
`interview_cancelled` does not erase a reached stage. The latest effective
lifecycle transition sets `application_status`; terminal states may only be
followed by informational events or an explicit correction. Listing closure and
source duplicates are outside this event projection.

The mismatch report compares only `application_status`, `stage_reached`,
`applied_at` and `response_at` for jobs with an event file. Legacy jobs without
events are not treated as mismatches before migration.

## Alpha boundaries

The parser, writer, CLI and connector route are tested on fixtures. Public
writes require the versioned `config/event-ledger-cutover.json` marker, which is
published atomically with the historical migration under D-017. The
`TRACKER_V3_EVENT_WRITES=1` override is for fixtures and one-time maintenance.
An `event` connector operation cannot be a batch child.
