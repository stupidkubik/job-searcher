# WP1.3 reader and legacy-writer audit — 2026-09-24

Scope: current Python/CI entry points that read a canonical snapshot, event
ledger or connector result while a journal publication may be pending. All
verification used synthetic event data; production has no event files.

| Surface | Consistency path | Result |
|---|---|---|
| `jobs.py` read commands | `tracker_cli.main` locks root and recovers before command | covered by existing CLI crash tests |
| Normal `jobs.py` writes | `load_for_write` reads under lock; publisher checks revisions | covered by stale and crash tests |
| Internal event append/retry | reads CSV + JSONL under lock; publisher checks both revisions and global ledger | integrated tests cover retry, stale snapshot and every replace boundary |
| `event_ledger.py` diagnostic CLI | canonical `data/application_events` + `data/jobs.csv` pair now recovers and reads under root lock | killed-writer recovery test |
| Connector staging | copies snapshot, cards, indexes, tracker and event files under lock; snapshot includes per-job JSONL | staged writes validate event projection |
| Connector final publisher | validates snapshot and event projection before durable marker | existing result recovery tests; event command remains WP1.4 |
| `ops_health.py` | builds report under dataset lock | command smoke check |
| Historical maintenance `save` helpers | fail closed once `data/application_events` exists | guard test |
| CI apply script | uses `jobs.py` validation after operation; commits only after result | no public event operation yet; event allowlist and `git add` belong to WP1.4 |

Residual boundaries:

1. Direct opening of CSV, JSONL or generated Markdown by a separate process
   does not take the lock and can observe an intermediate replacement during an
   active transaction. Supported commands use the lock; Git commits are made
   only after publication. A future UI must use a locked read API or a
   versioned snapshot, rather than reading several raw files independently.
2. Historical maintenance scripts are outside the live write path. Their
   direct saves now reject a checkout with a ledger, but their dry-run reads do
   not offer a cross-artifact snapshot. They remain offline migration tools.
3. Public event CLI/connector routing and changed-path allowlist are WP1.4
   work. A synthetic event/result publication has now proved the shared journal
   boundary, but Gate 1 still requires the public command and backfill.

Verification: `tests/test_tracker_event_write.py` checks process kill after
prepare, after all eight replacements and after durable commit; rollback and
identical retry; stale snapshot; cross-job ID; direct maintenance save guard.
The isolated journal tests in `tests/test_tracker_transaction.py` continue to
cover corrupt backup, cleanup failure and two-process publisher race.
