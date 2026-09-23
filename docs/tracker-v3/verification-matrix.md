# Tracker v3 verification matrix

Статус: planning baseline. Расширяется вместе с контрактами и тестами.

## Global quality gate

После каждого work package:

```bash
python3 scripts/jobs.py validate --strict --format json
python3 scripts/jobs.py render-tracker --check --format json
python3 scripts/jobs.py render-index --check --format json
python3 scripts/agent_operations.py render-contract --check --format json
python3 -m unittest discover -s tests -v
git diff --check
git status --short
```

Если меняется source/adapter, дополнительно проверяется read-only checkout. Если
меняется canonical write path, обязательны fault injection и rollback tests.

## Event ledger requirements

| ID | Requirement | Automated evidence | Manual/review evidence | Gate |
|---|---|---|---|---|
| EVT-001 | Event schema rejects unknown/missing fields | unit fixtures | contract review | 1 |
| EVT-002 | Every event references an existing job | foreign-key test | migration summary | 1 |
| EVT-003 | Event IDs are unique and retries idempotent | duplicate/retry tests | operation result review | 1 |
| EVT-004 | Original event is never overwritten | filesystem/diff test | correction timeline review | 1 |
| EVT-005 | Correction chain is deterministic and acyclic | loop/supersession tests | rendered example | 1 |
| EVT-005a | Correction may recompute an erroneous historical maximum downward without allowing ordinary stage regression | correction/snapshot tests | before/after timeline review | 1 |
| EVT-006 | Human-only events require explicit confirmation | negative CLI/connector tests | approval flow review | 1 |
| EVT-007 | Event + snapshot update is atomic, including process crash and retry | fault/kill injection and recovery tests at each replace boundary | rollback rehearsal and connector result review | 1 |
| EVT-008 | Snapshot agrees with effective event history | projection mismatch test | sampled migrated jobs | 1 |
| EVT-009 | `occurred_at` and business date preserve timezone/precision | timezone/date-only fixtures | migration table review | 1 |
| EVT-010 | Listing closure does not rewrite application history | regression test | timeline review | 1 |
| EVT-011 | Adapter/inbox cannot write event directly | boundary/changed-path tests | workflow permissions review | 1/5 |
| EVT-012 | Backfill is dry-run safe and idempotent | migration tests | before/after count report | 1 |

## Application packet requirements

| ID | Requirement | Automated evidence | Manual/review evidence | Gate |
|---|---|---|---|---|
| PKT-001 | Manifest has version, job, profile/JD and artifact identity | schema tests | sample manifest review | 2 |
| PKT-002 | SHA-256 covers exact raw bytes | known-hash fixtures | compare source/download | 2 |
| PKT-003 | Changed/missing artifact fails verification | mutation/delete tests | clear CLI output review | 2 |
| PKT-004 | Multiple packets do not overwrite history | version/id tests | per-job listing review | 2 |
| PKT-005 | Preparation/review does not imply submission | lifecycle negative tests | workflow review | 2 |
| PKT-006 | Submitted packet links to human-confirmed applied event | cross-artifact test | sampled applied job | 2 |
| PKT-007 | Legacy applied jobs without packet remain valid and visible | legacy fixture tests | migration report | 2 |
| PKT-008 | Logs/results do not expose artifact contents or secrets | captured-output tests | privacy review | 2 |

## Match analysis requirements

| ID | Requirement | Automated evidence | Manual/review evidence | Gate |
|---|---|---|---|---|
| MAT-001 | Atomic requirements and evidence links are versioned | schema/ref tests | sample analysis | 3 |
| MAT-002 | Eligibility is separate from preference and evidence | invariant tests | golden corpus review | 3 |
| MAT-003 | Unknown never silently becomes pass | negative fixtures | false-positive review | 3 |
| MAT-004 | Same saved artifact preserves the agent score and rationale | serialization/reload test | repeated view review | 3 |
| MAT-005 | Analysis version and rationale are retained | history/version tests | version diff review | 3 |
| MAT-006 | Missing/deleted profile evidence is detected | referential tests | remediation UX review | 3 |
| MAT-007 | Human override requires reason and preserves original | override tests | audit view review | 3 |
| MAT-008 | `match_score` is the validated agent score; legacy values remain distinct | compatibility tests | old/new comparison | 3 |

## Source health requirements

| ID | Requirement | Automated evidence | Manual/review evidence | Gate |
|---|---|---|---|---|
| SRC-001 | Run outcome distinguishes zero, blocked, auth, rate, parse and partial | adapter fixtures | source report review | 4 |
| SRC-002 | Observation absence cannot close listing | invariant test | sampled source run | 4 |
| SRC-003 | Run artifact contains exact time/query/version/counts | schema tests | artifact review | 4 |
| SRC-004 | Discovery workflow remains read-only | workflow/path test | permissions review | 4 |
| SRC-005 | Repeated run does not create duplicate observation identity | idempotency test | run history review | 4 |

## Inbox requirements

| ID | Requirement | Automated evidence | Manual/review evidence | Gate |
|---|---|---|---|---|
| INB-001 | Message identity/dedupe is stable | fixture/retry tests | sample proposal history | 5 |
| INB-002 | Rules handle negation, hypothetical and process descriptions | regression corpus | misclassification review | 5 |
| INB-003 | AI sees only ambiguous bounded input | call/mock tests | privacy/prompt review | 5 |
| INB-004 | Inbox output is proposal-only | boundary tests | workflow review | 5 |
| INB-005 | Proposal includes evidence, confidence and source reference | schema tests | review screen/output | 5 |
| INB-006 | Accept/reject/correct is explicit and idempotent | integration tests | user-flow review | 5 |
| INB-007 | Credentials/raw mail stay outside Git/logs | path/permission/output tests | local storage audit | 5 |

## Analytics requirements

| ID | Requirement | Automated evidence | Manual/review evidence | Gate |
|---|---|---|---|---|
| ANA-001 | Every counted transition comes from effective event history | golden fixture | hand calculation | 6 |
| ANA-002 | Corrected events are not double-counted | correction fixture | Sankey/table review | 6 |
| ANA-003 | Date-only/unknown precision excluded from exact duration | precision fixtures | methodology review | 6 |
| ANA-004 | Current, furthest and traversed stage are separate metrics | semantic tests | labels/documentation | 6 |
| ANA-005 | Cohort denominator is explicit | report snapshot tests | report review | 6 |
| ANA-006 | Render is deterministic and handles empty/legacy data | repeat/empty tests | browser view review | 6 |

## Non-functional requirements

| ID | Requirement | Evidence | Threshold/decision |
|---|---|---|---|
| NFR-001 | Existing full test suite does not regress unexpectedly | timed CI-equivalent run | investigate >25% unexplained increase from comparable baseline |
| NFR-002 | Normal agent bootstrap avoids full new artifact corpus | ops-health extension | targeted index/read path documented |
| NFR-003 | No new required runtime/dependency without decision | dependency diff | explicit accepted decision |
| NFR-004 | Public branch never requires force-push | Git history/status | fast-forward/merge workflow |
| NFR-005 | Canonical migration has tested rollback | temp-copy apply/revert | exact pre-migration state restored |
| NFR-006 | New artifacts remain inspectable in Git diff | fixture review | no opaque binary canonical format |

## Required synthetic scenarios

1. Apply confirmed; no response.
2. Apply → acknowledgement → recruiter screen → rejection.
3. Apply → assessment invited/completed → technical interview → offer.
4. Interview scheduled → rescheduled → completed.
5. Candidate withdrawal before response.
6. Wrong rejection event corrected/superseded.
7. Listing closes after application; lifecycle remains intact.
8. Same job discovered under multiple URLs; events attach to canonical job.
9. Legacy applied row with date-only precision.
10. Inbox hypothetical text that must not become an interview event.

WP1.1–WP1.2 evidence (2026-09-23): `tests/test_event_ledger.py` contains all ten
synthetic scenarios plus malformed fields, IDs, correction chains, timezone,
confirmation, cross-file identity and mismatch checks. The read-only CLI
returns nonzero on mismatch. `scripts/maintenance/bench_event_layouts.py`
measures 1k/10k synthetic event layouts. EVT-007, writer retry and migration
evidence remain pending for WP1.3/WP1.5; these tests do not authorize writes.

WP1.3a evidence (2026-09-23): `tests/test_tracker_transaction.py` kills a child
process after preparation, each replacement and commit marker; checks recovery,
normal faults, stale hashes, corrupt backup, cleanup failure, owner-only journal
and two-process race. EVT-007 remains pending for integrated `jobs.py`/connector
readers, immutable result, generated views and current-data rollback rehearsal.

## Phase evidence package

Каждый phase gate должен оставить:

- test output summary;
- migration/dry-run summary if relevant;
- before/after counts;
- exact changed paths;
- unresolved issues and updated risks;
- decision IDs used;
- rollback instructions;
- work-log entry.
