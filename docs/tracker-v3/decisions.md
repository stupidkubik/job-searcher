# Tracker v3 decision log

Статус: ADR-lite register.

Решения не удаляются. Новое решение может `supersede` старое. `Proposed` entries
помогают планировать, но не дают права менять действующие контракты.

## D-001 — preserve current canonical snapshot during transition

- Status: accepted (inherited)
- Date: 2026-09-22
- Decision: `data/jobs.csv` остаётся canonical current snapshot, а v3 artifacts
  добавляются рядом. Полный event sourcing не является первым этапом.
- Reason: current write path, reports, connector and validation already rely on
  the snapshot; additive evolution has smaller rollback radius.
- Consequences:
  - нужен explicit consistency validator;
  - dual-write atomicity становится critical risk;
  - future event-derived snapshot remains possible after measured need.

## D-002 — preserve human authority for application lifecycle

- Status: accepted (inherited)
- Date: 2026-09-22
- Decision: фактическая отправка и human-only lifecycle events не выводятся из
  browser/email/source signals. Adapters могут создавать только proposals.
- Consequences:
  - inbox cannot write canonical events;
  - packet preparation is not application submission;
  - explicit user confirmation remains in CLI/connector contract.

## D-003 — add an append-only event ledger with initial dual-write

- Status: proposed
- Date: 2026-09-22
- Decision: introduce canonical append-only application events while retaining
  `jobs.csv` snapshot; one transaction updates both.
- Alternatives:
  - immediate event sourcing;
  - keep snapshot only;
  - store history only in application Markdown.
- Reason: events unlock inbox, interview rounds and correct analytics without a DB
  migration, while snapshot compatibility limits scope.
- Open dependencies: B-001/B-002/B-004 для event contract;
  B-003 для dual-write и B-005 для migration/Gate 1.
- Acceptance evidence: event prototype, fault tests, migration dry-run.

## D-004 — make application packets immutable and content-addressed

- Status: superseded by D-019; never adopted as a required workflow
- Date: 2026-09-22
- Decision: every prepared/submitted packet records schema version, profile/JD
  revision, artifact paths and SHA-256 hashes. Historical packet manifests are
  never overwritten.
- Reason: filename or `cv_version` alone cannot prove submitted bytes.
- Consequences:
  - multiple packets per job must be supported;
  - raw byte hash is identity; path is locator;
  - stale file is detected, not silently accepted.
- Open dependencies: Q-006–Q-007.

The original proposal is retained for historical context. D-019 removes it
from the active v3 scope.

## D-005 — decompose match into evidence, confidence and eligibility

- Status: proposed
- Date: 2026-09-22
- Decision: агент извлекает требования, связывает evidence и выставляет
  итоговый `match_score` 1–10 с обоснованием. Код проверяет schema,
  evidence links, диапазон и явное отражение eligibility blockers/unknown;
  preference остаётся отдельной. Правило владения итоговым баллом принято
  отдельно в D-010.
- Reason: one score hides hard blockers and model uncertainty.
- Consequences:
  - stable profile evidence IDs required;
  - historical analysis version and agent rationale retained;
  - formula-based score не вводится без нового решения;
  - `match_score` compatibility must be documented.
- Open dependencies: Q-008; Phase 3 golden corpus.

## D-006 — separate source observation from listing truth

- Status: proposed
- Date: 2026-09-22
- Decision: source-health and `last_seen` artifacts cannot set
  `listing_status=closed`; only first-party evidence can.
- Reason: adapter failure, rate limit and zero results are different from closure.
- Consequences: source health gets its own taxonomy and projection.

## D-007 — inbox is deterministic-first and proposal-only

- Status: proposed; deferred until Phase 5
- Date: 2026-09-22
- Decision: parse bounded read-only input; use rules first and classifier only for
  ambiguity; output proposals with evidence and confidence.
- Consequences:
  - OAuth is not required for first offline-fixture slice;
  - every corrected classification becomes a regression fixture;
  - promotion reuses ordinary authorized write path.

## D-008 — defer database, SPA and browser extension

- Status: accepted for v3 core
- Date: 2026-09-22
- Decision: no database/UI/browser platform work until the relevant contracts
  are stable and measured pain justifies the maintenance surface. D-019 later
  removed packet work as a prerequisite for unrelated tracker phases.
- Reason: current high-value changes fit versioned files and existing CLI.
- Revisit trigger:
  - measured performance ceiling;
  - interaction impossible through CLI/generated view;
  - stable event API; a materials contract if browser assistance needs one;
  - explicit threat model and maintenance budget.

## D-009 — use the public v3 branch as an integration branch without force-push

- Status: accepted
- Date: 2026-09-22
- Decision: `codex/tracker-v3` tracks origin and is synchronized through explicit
  checkpoints. Production migration occurs only from a fresh main baseline.
- Reason: main receives frequent canonical job operation commits; rewriting branch
  history would obscure integration and risk lost data changes.

## D-010 — agent owns the final match score

- Status: accepted
- Date: 2026-09-23
- Decision: агент выставляет итоговый `match_score` 1–10. Versioned match
  artifact сохраняет балл, rationale, eligibility, evidence и confidence;
  validator проверяет согласованность и диапазон, но не рассчитывает другой
  балл по скрытым весам.
- Reason: это явное правило пользователя; численная оценка остаётся суждением
  агента и должна быть проверяема по сохранённым основаниям.
- Consequences: существующие баллы остаются legacy snapshot без выдуманного
  provenance; новый расчет формулой возможен только через отдельное решение.

## D-011 — defer contact graph until real contacts exist

- Status: accepted
- Date: 2026-09-23
- Decision: не добавлять contact entity/schema в v3 core. Использовать
  существующие поля и application cards; вернуться к модели при повторяющихся
  контактах или необходимости связывать один contact с несколькими jobs.
- Evidence: текущие 458 jobs содержат 0 `contact_name` и 0 `contact_url`.
- Consequences: Phase 7 не начинается по одному лишь плану; новый inventory и
  отдельное решение требуются при появлении данных.

## D-012 — accept the read-only event contract v1

- Status: accepted for WP1.1–WP1.2; production writes remain gated by B-003.
- Date: 2026-09-23
- Decision: use one append-only JSONL per canonical job at
  `data/application_events/job-NNNN.jsonl`; use caller-provided `event_id`,
  UTC `recorded_at` plus ID ordering, date/instant/unknown business precision,
  full replacement corrections via `supersedes`, and the minimal event taxonomy
  in [`event-contract-v1.md`](event-contract-v1.md). Correction projection uses
  the original event's logical slot. Read-only validation and projection are
  the first implementation slice.
- Alternatives: one global JSONL or one JSON per event; content-derived event
  IDs; mutating an old event when correcting it.
- Evidence: synthetic 1k/10k layout benchmark, ten lifecycle scenarios,
  correction/ordering/confirmation tests in `tests/test_event_ledger.py`.
- Consequences: B-001/B-002/B-004 design questions are resolved. D-003 is
  still proposed until the write transaction, connector and migration gates
  have evidence. No production event files are created by this decision.

## D-013 — prototype recoverable file-set publication before integration

- Status: accepted for isolated WP1.3a prototype; not yet a production write
  protocol.
- Date: 2026-09-23
- Decision: test a single-lock fileset publisher with expected old hashes,
  durable backups/manifest, fsynced replacements, commit marker and repeatable
  recovery before changing `jobs.py` or connector operations. Include the
  immutable operation result in the demonstrated file set.
- Evidence: [`transaction-prototype.md`](transaction-prototype.md),
  `scripts/tracker_transaction.py` and process-kill/fault/concurrency tests in
  `tests/test_tracker_transaction.py`.
- Consequences: B-003 remains investigating until readers, existing writers,
  connector results and generated projections share the integrated boundary
  and pass the same crash/retry tests.

## D-014 — use a gated single `event` command for v3 lifecycle history

- Status: accepted for WP1.4; production cutover remains separate.
- Date: 2026-09-24
- Decision: add a dedicated `event` command beside legacy `status`. The manual
  CLI accepts a full v1 event JSON and supports `--dry-run`; connector v1 accepts
  only business fields in one existing-job operation with an `expected` lock.
  The trusted runner derives `event_id` from `operation_id`, records its own
  UTC timestamp and sets `source=connector`, `actor=user`. Both routes require
  explicit human confirmation. Connector event is not a batch child. Public
  writes require `TRACKER_V3_EVENT_WRITES=1` after a separate cutover.
- Alternatives: overload `status`, allow event batch children immediately, or
  enable event writes before historical migration is ready.
- Evidence: generated `data/operations/contract.md`, CLI dry-run/write-gate
  tests, connector validation/staging/immutable-result tests, and an end-to-end
  CI runner allowlist test for event JSONL.
- Consequences: Q-011 is resolved. Existing v1 commands remain valid and
  production events remain absent until cutover. WP1.5 backfill and WP1.6
  timeline are still required for Gate 1.

## D-015 — migrate only dated, exactly representable lifecycle facts

- Status: accepted for WP1.5; production cutover remains separate.
- Date: 2026-09-24
- Decision: historical event migration reads only four structured lifecycle
  fields. Known dates retain `precision=date`; all rows use `source=migration`
  and no user confirmation. A row with an unproven stage or undated transition
  blocks application rather than receiving an inferred event. See the full
  [decision table](historical-backfill.md).
- Alternatives: synthetic midnight instants, parsing notes, treating
  `response_at` as an interview or offer date, and using `last_update` for a
  terminal event. Each would assert more than the snapshot proves.
- Evidence: 458-row dry-run, 45-job temporary-copy apply and idempotent retry,
  exact projection checks, forced rollback test, and 263 passing tests.
- Consequences: B-005 is resolved for current data. Production event writes
  stay gated until cutover; future unrepresentable rows fail closed.

## D-016 — fence legacy lifecycle writes before event cutover

- Status: accepted as a cutover safety invariant; Gate 1 remains open.
- Date: 2026-09-24
- Decision: while `TRACKER_V3_EVENT_WRITES` is off, `status` retains its v2
  behavior for jobs without an event file. Once a job has an event file,
  `status` rejects before writing. When the event write gate is on,
  post-application `status` rejects even for jobs without an event file;
  pre-application `status` remains available. Human-confirmed lifecycle facts
  must enter through the atomic `event` path.
- Reason: accepting a snapshot-only `status` after event history begins would
  create a gap or disagree with the ledger. The v2 `status` arguments cannot
  faithfully express every v1 event, including interview round identity.
- Evidence: `event_required` tests cover a job with history, a new application
  under the write gate and a pre-application transition; transaction mismatch
  tests remain as the race backstop.
- Consequences: B-006 tracks the remaining compatibility decision for legacy
  post-application callers and metadata such as `cv_version`. The write gate
  stays off until that path is resolved and rehearsed.

## D-017 — use explicit events after cutover and migrate historical snapshots

- Status: accepted by the user on 2026-09-24; production migration is a
  separate audited commit.
- Date: 2026-09-24
- Decision: after cutover, post-application lifecycle changes use the `event`
  command. Legacy `status` remains available for pre-application work and is
  rejected for post-application states. Historical snapshot dates are migrated
  by D-015, with no inferred interview rounds or precise times. A confirmed
  `cv_version` is written through the restricted connector `set` command; its
  card front matter is updated in the same dataset transaction.
- Cutover boundary: the historical event files and versioned
  `config/event-ledger-cutover.json` marker are published in one recoverable
  transaction. Public event writes become available through that marker;
  `TRACKER_V3_EVENT_WRITES=1` remains a fixture/maintenance override.
- Consequences: v2 post-application `status` callers must switch to `event`.
  This is the explicit compatibility exception to the original Gate 1 wording.
  No generic status-to-event conversion is attempted.

## D-018 — accept the branch-local application event cutover

- Status: accepted on the integration branch; deployed through PR #21 on
  2026-09-24, with passing PR checks and post-merge tree validation.
- Date: 2026-09-24
- Supersedes: D-003's proposed dual-write boundary with the D-017 explicit
  `event` API and documented legacy `status` exception.
- Decision: keep `jobs.csv` as the current snapshot and
  `data/application_events/job-NNNN.jsonl` as canonical application history.
  The 45 historical applications and versioned write marker are published in
  one recoverable transaction. New human-confirmed lifecycle writes use
  `event`, which publishes event and snapshot atomically.
- Evidence: [cutover report](cutover-2026-09-24.md), 53 migrated events, zero
  projection mismatches, exact-baseline rollback rehearsal, idempotent retry,
  277 tests and fresh generated views.
- Consequences: branch-local Gate 1 evidence is complete. Main deployment
  still needs review/merge and validation of the merged state.

## D-019 — defer full application packets for the single-user tracker

- Status: accepted by the user on 2026-09-24
- Date: 2026-09-24
- Supersedes: D-004
- Decision: do not require packet manifests, packet IDs, JD/profile snapshots,
  or per-artifact hashes in the current application workflow. Defer Phase 2 and
  Q-006/Q-007. Existing `cv_version`, application cards, Git history, and
  human-confirmed `application_submitted` events remain the working record.
- Reason: this is a single-user tracker, not a web platform. The full packet
  workflow would add routine steps without a demonstrated loss of information
  in the current workflow.
- Revisit trigger: a concrete case where multiple CVs or other submitted
  materials cannot be identified reliably, or where a changed/missing file
  prevents a needed audit. Start with the smallest explicit record of the
  submitted file path and SHA-256 if that case arises; choose a write contract
  then. A full packet requires a separate decision and privacy review.
- Consequences: no new packet requirement for future submissions, no event
  schema change for `packet_id`, and no packet dependency for Phase 3 or 4.
  Historical applications need no packet backfill.

## D-020 — pilot lightweight match explanations before Phase 3 schema work

- Status: accepted by the user on 2026-09-24
- Date: 2026-09-24
- Decision: use a bounded retrospective sample and a short score/reason,
  gap-or-unknown, and decision summary in future full reviews before adding
  profile evidence IDs or versioned match artifacts. Do not rescore or backfill
  historical jobs to manufacture missing rationale.
- Evidence: [eight-record matching pilot](matching-pilot-2026-09-24.md) found
  substantive analysis in four cards, readable rationale somewhere in seven
  records, and one stored score without recoverable rationale in reviewed fields.
- Consequences: Q-008 and D-005 remain open for the full Phase 3 proposal;
  neither blocks the lightweight trial. No new canonical field, index, or
  operation is introduced by this decision.

## D-021 — start source health with a read-only Himalayas run outcome

- Status: accepted for the first Phase 4 slice on 2026-09-24
- Date: 2026-09-24
- Decision: classify each Himalayas adapter run as `success`, `zero_results`,
  `partial`, `auth_required`, `blocked`, `rate_limited`, `parse_error` or
  `request_failed`. Preserve an immutable read-only artifact for failed
  `--artifact` runs and mark incomplete runs explicitly. Only a complete run
  may write an inbox raw batch.
- Reason: a failed adapter run must not appear to be an empty vacancy feed.
  The existing workflow already uploads a short-lived read-only artifact, so
  this adds no step to the user's application workflow.
- Consequences: D-006's separation of source observation and canonical listing
  truth is exercised for one adapter. No `listing_status`, job row or source
  reference changes from a run outcome. Broader `last_seen` storage, source
  projection and quiet-board alerts remain decisions for later Phase 4 work.

## Decision template

```text
## D-NNN — title

- Status: proposed|accepted|rejected|superseded
- Date: YYYY-MM-DD
- Supersedes: optional ID
- Context:
- Decision:
- Alternatives:
- Reason:
- Consequences:
- Acceptance evidence:
```
