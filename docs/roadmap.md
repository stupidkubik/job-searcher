# Roadmap

## Implemented

- Canonical `data/jobs.csv`, source provenance, application cards and safe
  writes through `scripts/jobs.py`.
- v2 data model: separate listing/application lifecycle, validation, structured
  input, source registry, inbox/ingest, Himalayas adapter, `todo`, `stale`,
  stats and reports.
- Browser-first generated view: [`tracker.md`](tracker.md) with an exact
  freshness gate in CI.
- GitHub connector gateway: immutable requests, trusted runner, immutable
  results and direct-to-`main` delivery without operation branches or review PRs.
- Batch-friendly source sweeps: atomic `add` children receive IDs inside one
  transaction and report a stable `client_ref → job_id` mapping.
- Read-only Himalayas discovery workflow with normalized artifacts, exact UTC
  run timestamps and `Europe/Belgrade` tracker dates.
- Self-explaining write path: every operation leaves exactly one immutable
  result, a contract rejection carries a machine-readable `error.code`, batches
  choose their atomicity and hand back ready-to-send `retry` fragments, and the
  agent boots from generated `data/index/*` instead of the full CSV.

The implementation plan and its accepted decisions remain in
[`tracker-v2-plan.md`](tracker-v2-plan.md); it is now an implementation record,
not a queue of unstarted phases. The browser-view specification is preserved in
[`tracker-browser-view-plan.md`](tracker-browser-view-plan.md).

## Остатки закрытого write-path плана

[`agent-write-path-plan-2026-09-07.md`](agent-write-path-plan-2026-09-07.md)
закрыт: все этапы Э0–Э10 реализованы. Четыре пункта его DoD остались
незакрытыми и живут здесь, потому что исторический документ не переписывается
задним числом.

- **`original_url` у агрегаторных строк.** Э5(B) дал
  `scripts/maintenance/backfill_original_url.py`, но на реальных данных он
  меняет ноль строк: все 24 строки `Company Careers` уже заполнены, а 281
  пустая приходится на агрегаторы (Hirify, LinkedIn, Himalayas, YC…), чей
  `source_url` — страница находки, а не первоисточник. Целевая метрика «281 →
  < 150» этим скриптом недостижима. Нужно решение: заполнять `original_url`
  только по ходу обычной first-party верификации (тогда метрику снять) либо
  расширить список источников, чей `source_url` считается first-party.
- **Вес бутстрапа.** Э6 дал 2.45× (329 618 → 134 364 Б, ~33.6K токенов) против
  целевых ~24K / 3.5×. Индексы тут не виноваты: в бюджет Э6 не входили
  `data/operations/contract.md` (Э2) и `docs/sources/README.md`, которые
  контракт теперь требует читать. Отдельно: `BOOT_SET` в
  `scripts/maintenance/ops_health.py` всё ещё перечисляет набор до Э6, поэтому
  инструмент не измеряет ту метрику, ради которой заведён.
- **Placeholder-дедуп только в одном из двух путей.** Э5(3) исключил
  placeholder-компании в `find_duplicate_candidates` (write path), но не в
  `find_fuzzy_duplicates` — функции, на которой стоит отчёт `dupes`. Поэтому
  пары вида `Undisclosed (hirify-NNNNNN)` по-прежнему попадают в отчёт как
  ложные кандидаты, и `dupes --fail` не может стать чистым.
- **Вторая волна таксономии ошибок.** В `agent_operations.py` осталось 32
  вызова `raise OperationError(...)` без явного `code`: вся валидация аргументов
  `verify` / `set` / `screen` отдаёт агенту общий `contract_violation` без
  `field` и `hint`. Э1 сознательно ограничился волной 1; закрытие волны 2
  делает `contract_violation` недостижимым.

## Next, only after a concrete need

- Design a versioned connector v2 only if manifest repetition or stale-operation
  conflicts become an observed burden. Preserve v1 compatibility while
  considering filename-derived operation identity, inherent batch atomicity and
  a stronger revision token.
- Add source adapters or optional analytics after a source demonstrates stable
  value and verification quality.

## Later, only after a confirmed need

- an interactive UI beyond the existing Markdown browser view;
- SQLite/Postgres;
- GitHub Issues как intake layer;
- автоматическая отправка заявок.

These items do not supersede the current CSV + Markdown + Git audit trail.
