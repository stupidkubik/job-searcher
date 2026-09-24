# Gate 1 checkpoint — 2026-09-24

Status: **open**. This is a cutover audit, not a production migration.

After `git fetch origin`, `codex/tracker-v3` was 17 commits ahead of
`origin/main` and 0 behind at the start of this checkpoint. No production
event files were created. The current snapshot has 458 jobs and 474 source
references; strict validation and both generated-view checks pass.

| Gate 1 requirement | Evidence | State |
|---|---|---|
| Documented event contract and deterministic validator/projection | D-012, `event-contract-v1.md`, synthetic fixtures | verified |
| Atomic event + snapshot publication | D-013/D-014, journal fault/recovery and connector result tests | verified on fixtures and temporary copy |
| Historical migration precision and idempotence | D-015, 458-row dry-run: 45 jobs, 53 events, 0 blockers; earlier temporary-copy retry and rollback | verified for current data |
| Targeted human timeline | WP1.6 CLI and correction/void/evidence tests | verified |
| Existing lifecycle command compatibility after cutover | D-016 prevents snapshot-only writes, but v2 `status` cannot express all event facts or metadata updates | **blocked by B-006** |
| Generated views and full tests | tracker/index fresh; 272 tests pass | verified |
| Source/inbox cannot write events directly | connector allowlist and event confirmation tests | verified on fixtures; recheck at cutover |

D-016 now rejects `status` before writing when a job already has event history.
With `TRACKER_V3_EVENT_WRITES=1`, it also rejects post-application `status` for
jobs without history. A connector request receives an immutable rejected
result with the existing `invariant_violation` error code; canonical data stays
unchanged. Pre-application `status` and all ungated legacy jobs retain current
behavior. This is a safety fence, not a compatibility adapter.

B-006 must resolve how callers of v2 `status` move to v3 without fabricating
interview rounds or transition times, and where metadata such as `cv_version`
is written. D-003 remains proposed until that route and fresh-main cutover
rehearsal are accepted. Keep `TRACKER_V3_EVENT_WRITES` disabled in production.

Rollback of this checkpoint code is `git revert` of its single commit. Since
it changed no canonical CSV, ledger or generated view, there is no data
migration to undo.
