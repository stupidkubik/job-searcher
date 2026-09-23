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
