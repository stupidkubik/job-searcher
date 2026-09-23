# Tracker v3 open issues and blockers

Статус: active register.

## Severity and status

- `blocker` — следующий phase gate пройти нельзя;
- `high` — можно продолжать независимую работу, но нельзя завершить phase;
- `medium` — требует решения до соответствующего work package;
- `low` — улучшение или наблюдение.

Статусы: `open`, `investigating`, `decision_ready`, `resolved`, `deferred`.

## Current blocking summary

Первый read-only срез WP1.1–WP1.2 прошёл Gate 0 по D-012. B-003 остаётся
блокером dual-write (WP1.3), B-005 — backfill (WP1.5) и Gate 1. Принятые
направления и оставшиеся доказательства разобраны в
[`annotation-review-2026-09-23.md`](annotation-review-2026-09-23.md).
Внешних credential/network blockers сейчас нет. Inbox и browser вопросы не
блокируют event/packet foundation.

## Event ledger blockers

### B-001 — physical event storage

- Severity: blocker
- Status: resolved
- Blocks: WP1.1
- Question: один canonical JSONL, per-job files или per-event immutable files?
- Options:
  - single JSONL: простой scan/validation, но конфликтный hot file;
  - per-job JSONL: локальная история и меньше конфликтов, больше file management;
  - per-event JSON: естественная immutability, но много файлов и дороже projection.
- Evidence needed: prototype на synthetic 1k/10k events, Git diff readability,
  transaction behavior, lookup/bootstrap cost.
- Resolution: D-012, 2026-09-23; per-job JSONL выбран после synthetic 1k/10k
  benchmark (`scripts/maintenance/bench_event_layouts.py`). Exact path,
  append order и retention заданы в `event-contract-v1.md`.

### B-002 — event identity, ordering and corrections

- Severity: blocker
- Status: resolved
- Blocks: WP1.1–WP1.2
- Questions:
  - UUID/ULID/content-derived ID или operation-provided stable ID?
  - что упорядочивает одинаковые `occurred_at`?
  - correction — `supersedes`, compensating event или оба механизма?
  - может ли correction менять только payload или также event type/time?
- Resolution: D-012, 2026-09-23; caller-provided ID, UTC `recorded_at` и
  `supersedes` зафиксированы. Pure validator отвергает duplicate IDs, forks,
  forward references и неверный порядок. Равенство/конфликт повторного ID
  задано контрактом; writer retry проверяется в WP1.3 как часть B-003.

### B-003 — dual-write transaction boundary

- Severity: blocker
- Status: investigating
- Blocks: WP1.3
- Question: как атомарно заменить event artifact, jobs CSV, application card и
  generated projections внутри существующего dataset transaction?
- Constraints:
  - no partial success;
  - connector retry remains honest;
  - lock scope bounded;
  - failed projection must not leave canonical pair inconsistent.
- Evidence needed: fault-injection tests at every replacement boundary.
- Exit criteria: one service function owns event + snapshot mutation and rollback.
- Agreed direction: одна внешняя операция для агента/connector; внутренний
  transaction journal или другой доказанный crash-recovery protocol.
- Progress 2026-09-23: D-013, isolated journal prototype and process-kill tests
  pass on synthetic files. Existing `jobs.py` readers/writers, connector result
  and generated views still use different boundaries; integration tests and
  rollback rehearsal remain before resolution. См.
  [`transaction-prototype.md`](transaction-prototype.md).

### B-004 — minimum event taxonomy and projection rules

- Severity: blocker
- Status: resolved
- Blocks: WP1.1
- Question: какие events входят в v3 core, какие только informational, какие
  изменяют `application_status`, `stage_reached`, `applied_at`, `response_at`?
- Risk: слишком широкий enum заморозит неудачную domain model; слишком узкий
  снова потеряет interview rounds.
- Exit criteria: synthetic scenarios имеют однозначную projection table.
- Resolution: D-012, 2026-09-23; closed enum и projection table в
  `event-contract-v1.md`, десять synthetic scenarios и correction проверены в
  `tests/test_event_ledger.py`. Расширение enum требует versioned contract.

### B-005 — historical backfill precision

- Severity: blocker
- Status: decision_ready
- Blocks: WP1.5 and Gate 1
- Questions:
  - date-only `applied_at` становится midnight timestamp или date precision?
  - как обозначить inferred stage without known transition time?
  - создавать ли событие для every rejected row или только known dates?
- Recommendation: first-class `precision=date|instant|unknown` and
  `source=migration`; never invent midnight as real occurrence time. Направление
  согласовано; backfill table и dry-run ещё нужны.
- Exit criteria: backfill table covers every current lifecycle combination.

## Packet and evidence issues

### Q-006 — packet path and version identity

- Severity: high
- Status: decision_ready
- Blocks: WP2.1
- Question: `applications/job-NNNN.packet.json`, versioned directory или packet
  ID files?
- Need: multiple preparations per job without overwriting history.
- Candidate: `applications/job-NNNN/packets/<packet-id>.json`, but this changes
  current flat application-card convention and requires migration/docs review.
- Agreed direction: versioned manifests; flat cards сохраняются до отдельной
  безопасной миграции со ссылочным audit и rollback rehearsal.
- Exit criteria: exact path, identity, schema version and lookup rule accepted.

### Q-007 — hash scope and canonical byte representation

- Severity: high
- Status: open
- Blocks: WP2.1–WP2.2
- Questions:
  - hash source DOCX/PDF only or also rendered derivative?
  - normalize line endings for text artifacts or hash raw bytes?
  - how represent `none` and missing?
- Recommendation: hash raw bytes; derived files each get own hash; no silent
  normalization.

### Q-008 — stable profile evidence namespace

- Severity: high
- Status: open
- Blocks: WP3.1
- Question: как адресовать факты `config/profile.md`, чтобы обычное редактирование
  Markdown не ломало все historical links?
- Options: explicit IDs in Markdown, sidecar registry, structured profile source.
- Preferred prototype: explicit IDs beside profile facts; проверить rename,
  tombstone и referential validation на fixtures.
- Risk: sidecar/profile divergence versus noisy IDs in human document.
- Exit criteria: rename/edit/delete semantics and validator proven on fixtures.

### Q-009 — compatibility of `match_score`

- Severity: medium
- Status: resolved
- Blocks: WP3.2–WP3.3
- Decision: итоговый `match_score` 1–10 выставляет агент и сохраняет вместе с
  версией анализа и обоснованием; код проверяет контракт, но не вычисляет балл.
- Constraint: existing analytics and 1–10 values must remain interpretable.
- Resolution: D-010, 2026-09-23; legacy значения сохраняются без выдуманного
  evidence. Schema/validator для нового artifact проверяются в Phase 3.

## Branch, migration and operations issues

### Q-010 — long-lived branch synchronization

- Severity: high
- Status: investigating
- Blocks: canonical cutover, not fixture/code work
- Context: `main` receives frequent audited job operations. За короткий период
  перед созданием research branch remote получил 44 commits.
- Plan: no force-push; periodic merge checkpoints; production migration only
  from fresh main; avoid editing canonical CSV during feature development.
- Direction confirmed; перед cutover проверить ancestry и отсутствие потерянных
  operation commits.
- Exit criteria: cutover checklist demonstrates zero lost operation commits.

### Q-011 — connector contract evolution

- Severity: high
- Status: open
- Blocks: WP1.4
- Question: новый `event` command, extension of `status`, или versioned operation
  child? Нужно сохранить v1 compatibility и error taxonomy.
- Direction confirmed: единый trusted runner и одна операция; форму команды
  выбрать после event contract.
- Exit criteria: generated field × command contract, stale precondition and retry
  behavior defined before runner code.

### Q-012 — bootstrap projections for new artifacts

- Severity: medium
- Status: investigating
- Blocks: Gate 1/2/3
- Question: какие compact indexes нужны агенту, чтобы не читать полный event,
  packet и match corpus?
- Exit criteria: measured bootstrap delta and targeted read path.
- Agreed direction: targeted read по job и никаких новых обязательных индексов
  до измеренной потребности; измерить на каждом gate.

## Later-phase issues

### Q-013 — inbox credential and privacy model

- Severity: high for Phase 5; non-blocking now
- Status: deferred
- Topics: Gmail OAuth versus IMAP app password, local session storage, allowlist,
  redaction, retention, deletion, message links, provider error leakage.
- Direction confirmed: credential/session и raw mail остаются вне Git и CI
  artifacts; repo хранит только код и synthetic/redacted fixtures. Секреты CI
  не вводить без отдельного решения о необходимости CI-доступа.

### Q-014 — inbox proposal retention

- Severity: medium
- Status: deferred
- Question: хранить rejected proposals, evidence excerpts или только hashes and
  reason? Нужно сохранить auditability без лишнего PII. Направление согласовано,
  retention policy остаётся вопросом Phase 5.

### Q-015 — contact graph threshold

- Severity: medium
- Status: resolved
- Question: какая фактическая плотность повторяющихся contacts/referrals оправдает
  отдельную schema?
- Exit criteria: inventory real data before Phase 7.
- Resolution: D-011, 2026-09-23; 0 заполненных `contact_name` и `contact_url`
  в 458 jobs. Отдельную contact schema сейчас не вводить; пересмотреть при
  реальных повторяющихся контактах или multi-job outreach workflow.

### Q-016 — browser assistance authority

- Severity: blocker for Phase 8; non-blocking now
- Status: deferred
- Constraint: human presses final Submit. Нужны packet, threat model, permission
  review и maintenance budget до extension prototype.
- Direction confirmed: эти материалы готовятся перед Phase 8 по отдельному
  запросу.

## Resolved issues

B-001, B-002, B-004, Q-009 и Q-015 разрешены design-решениями; записи выше
остаются на месте.
При разрешении запись получает:

- `Status: resolved`;
- ссылку на decision ID;
- дату;
- implementation/test reference, если применимо.

## New issue template

```text
### X-NNN — short title

- Severity: blocker|high|medium|low
- Status: open
- Blocks: phase/work package
- Context/question:
- Options:
- Evidence needed:
- Exit criteria:
- Resolution: decision/test/commit link
```
