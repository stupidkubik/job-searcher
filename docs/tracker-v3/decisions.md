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
- Open dependencies: B-001–B-005.
- Acceptance evidence: event prototype, fault tests, migration dry-run.

## D-004 — make application packets immutable and content-addressed

- Status: proposed
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

## D-005 — decompose match into evidence, confidence and eligibility

- Status: proposed
- Date: 2026-09-22
- Decision: LLM may extract requirements/propose links; deterministic code owns
  scoring, caps and unknown handling. Preference remains separate.
- Reason: one score hides hard blockers and model uncertainty.
- Consequences:
  - stable profile evidence IDs required;
  - historical analysis version/weights retained;
  - `match_score` compatibility projection must be documented.
- Open dependencies: Q-008–Q-009.

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
- Decision: no database/UI/browser platform work until event and packet contracts
  are stable and measured pain justifies the maintenance surface.
- Reason: current high-value changes fit versioned files and existing CLI.
- Revisit trigger:
  - measured performance ceiling;
  - interaction impossible through CLI/generated view;
  - stable packet/event APIs;
  - explicit threat model and maintenance budget.

## D-009 — use the public v3 branch as an integration branch without force-push

- Status: accepted
- Date: 2026-09-22
- Decision: `codex/tracker-v3` tracks origin and is synchronized through explicit
  checkpoints. Production migration occurs only from a fresh main baseline.
- Reason: main receives frequent canonical job operation commits; rewriting branch
  history would obscure integration and risk lost data changes.

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
