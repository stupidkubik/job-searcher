# WP1.3 current-data rehearsal — 2026-09-24

Command: `python3 scripts/maintenance/rehearse_event_transaction.py`

The command copied the current tracker dataset, application cards, generated
views and any event files under the shared lock into a temporary directory. It
then added one synthetic job only inside that copy. No real job was assigned a
synthetic lifecycle event.

Observed baseline: 458 production jobs and 474 source references. The fixture
received `job-0459` in the copy. A child process was killed after the first
event transaction replacement. Recovery returned `rolled_back`; SHA-256 for
every copied CSV, generated view, application card and existing event file
matched the exact pre-event fixture baseline. The new event file was absent.

A subsequent append completed. A repeat of the same event returned
`already_recorded`; the copy had one event file, 459 jobs including the fixture
and 474 source references. Full event projection and generated-view byte checks
passed. The temporary directory was deleted on exit. `git status --short`
showed only the rehearsal script as untracked after the run: production data
and views were unchanged.

Connector boundary: `workspace_snapshot` now includes per-job event JSONL.
Synthetic integration tests stage event + CSV + card + views + immutable result,
then publish them through one journal. Kills after replacing the event and the
result both roll back event, snapshot and result. The public connector event
command and CI changed-path allowlist remain WP1.4 work.

Limits: this rehearsal proves the current-data copy, one synthetic first event,
recovery and retry. It does not migrate historical applications or authorize
production event writes. A fresh run is required before cutover from a newer
`main` snapshot.
