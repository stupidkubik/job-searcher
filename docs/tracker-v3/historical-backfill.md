# WP1.5 — historical application event backfill

Status: implementation and temporary-copy rehearsal verified on 2026-09-24.
Production event writes remain gated; Gate 1 remains open.

## Decision table

Only `application_status`, `stage_reached`, `applied_at` and `response_at` are
used. `notes`, `last_update`, listing state and application cards do not supply
event dates. Every emitted event has `precision=date`, `source=migration`,
`actor=migration`, `confirmed_by_user=false`, and a stable `migration-v1` ID.
No event claims a time of day. An equal applied/response date uses the known
submit-before-response causality and the stable event ID order.

| Snapshot combination | Decision |
|---|---|
| `not_started`, `reviewing`, `apply`; stage `None`; both dates empty | No event. Pre-application work is outside the event ledger. |
| Any pre-application status with a date or reached stage | Block: inconsistent snapshot. |
| Post-application status without `applied_at` | Block: submission date unknown. |
| Any post-application stage beyond `Applied` | Block: neither the transition date nor the intermediate sequence is proven. |
| `applied`, stage `Applied`, applied date, no response date | `application_submitted` on applied date. |
| `applied`, stage `Applied`, both dates | Submit and `response_received` on their respective dates. |
| `rejected`, stage `Applied`, both dates | Submit and `rejection_received`; no duplicate generic response event. |
| `rejected`, stage `Applied`, no response date | Block: rejection date unknown. |
| `interviewing`, `offer`, `ghosted`, `withdrawn` with stage `Applied` | Block: transition cannot be dated or represented exactly by v1 events. |
| Response date before applied date | Block: invalid lifecycle dates. |

The last two blocked cases are deliberate. Using `response_at` as an interview
or offer date would invent a stage transition; using `last_update` for
withdrawal or ghosting would invent a lifecycle date. A future migration rule
must first define a truthful representation and pass projection checks.

## Safe execution

`python3 scripts/maintenance/backfill_application_events.py` is a read-only
dry-run. It reports every snapshot category, pending event count by type,
blocked IDs, existing event count and row conservation. It creates no lock,
ledger directory or file. Existing event files are validated against the
snapshot before planning; an existing valid timeline is left untouched.

`--apply` requires an explicit `--root`. Against this checkout, it additionally
requires a one-command `TRACKER_V3_EVENT_WRITES=1` maintenance override.
`--apply --cutover` publishes all pending event files and the versioned
`config/event-ledger-cutover.json` write gate in the same transaction. It refuses the whole plan
when any lifecycle row is blocked. It publishes complete per-job JSONL files
through the recoverable transaction with missing-file preconditions, checks the
original CSV hash inside the transaction, and validates every projection before
commit. A failed validation rolls back all event files. The CSV and generated
views are never rewritten by this migration.

Temporary-copy rehearsal on the current 458-row CSV: 413 untouched rows,
45 migrated jobs, 45 `application_submitted` and 8 `rejection_received` events,
0 blocked. The second pass found 45 existing jobs and 0 pending events. The
copied and canonical CSV bytes retained SHA-256
`8475a8a52c307ddb6e00e93485fe8dc3d0644a566845dcfb2c850a1f7cac4fd2`.
The unit test also forces a validation failure after replacements and checks
that the ledger files and new directory are removed by rollback.

D-017 cutover rehearsal uses
`python3 scripts/maintenance/rehearse_application_cutover.py`. On a fresh copy
of the 458-row tracker it injected a failure after the first replacement,
recovered the exact copied baseline, then atomically published 53 events and
the write-gate marker. Existing CSV, source references, cards and generated
views kept their original bytes; retry found 0 pending jobs. This rehearsal
does not change production data.

Before a production cutover, rerun the dry-run on fresh `main`, inspect every
blocked ID and category count, then repeat the temporary-copy apply and
rollback rehearsal. No production historical events were written in WP1.5.
