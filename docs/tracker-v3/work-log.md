# Tracker v3 work log

Статус: append-only factual log.

Этот файл отвечает на вопрос «что реально сделано». Намерения, будущие задачи и
оценки находятся в `implementation-plan.md`; нерешённые вопросы — в
`open-issues.md`.

## Правила ведения

1. Существующие записи не переписываются, кроме исправления явной опечатки.
2. Исправление факта оформляется новой записью с `corrects`.
3. Запись добавляется после завершения или проверки действия, не заранее.
4. Для code/data work указываются tests и commit/ref.
5. `blocked` допустим только со ссылкой на blocker ID.
6. Рутинные команды внутри одного work package не требуют отдельных строк.

## Log

| ID | Date | Branch/ref | Action | Artifacts/result | Verification | Status |
|---|---|---|---|---|---|---|
| L-0001 | 2026-09-22 | `main` / `6a9d0cc` | Выполнен широкий GitHub landscape review | `docs/github-job-tracker-inspiration-analysis-2026-09-22.md` | full tests green before push | complete |
| L-0002 | 2026-09-22 | `codex/tracker-v3` / `cb58753` | Импортирован deep research report и создана integration branch | `docs/deep-research-report.md`, docs index | documentation tests 11/11 | complete |
| L-0003 | 2026-09-22 | `codex/tracker-v3` / current planning change | Создан planning workspace и baseline до изменения кода | `docs/tracker-v3/*` | strict validation, projections and contract fresh; 213 tests green | complete |
| L-0004 | 2026-09-23 | `codex/tracker-v3` / annotation review change | Разобраны пользовательские пометки и уточнены gates; приняты D-010/D-011 | `annotation-review-2026-09-23.md`, decisions, open issues, plan, risks, verification matrix | 11 documentation tests green; `git diff --check`; targeted inventory 458 jobs | complete |
| L-0005 | 2026-09-23 | `codex/tracker-v3` / read-only event alpha change | Пройден Gate 0; реализованы WP1.1–WP1.2 без production writes | D-012, `event-contract-v1.md`, synthetic layout benchmark, `scripts/event_ledger.py`, `tests/test_event_ledger.py` | 221 tests green; strict validation 458/474; tracker/index/contract fresh; `git diff --check` | verified |
| L-0006 | 2026-09-23 | `codex/tracker-v3` / isolated transaction prototype change | Проверен WP1.3a crash-recovery на synthetic file set; исправлены статусы B-003/B-004 | D-013, `tracker_transaction.py`, `transaction-prototype.md`, fault/kill/concurrency tests; production write path не изменён | 232 tests green; strict validation 458/474; tracker/index/contract fresh; `git diff --check` | verified |
| L-0007 | 2026-09-24 | `codex/tracker-v3` / shared-lock integration change | Начат WP1.3b: legacy dataset transaction разделяет lock с v3 publisher и восстанавливает pending journal | `tracker_write.py`, transaction tests, fixture scripts; event writes не включены | 234 tests green; strict validation 458/474; `git diff --check` | verified |
| L-0008 | 2026-09-24 | `codex/tracker-v3` / CSV revision guard change | Все основные dataset writes проверяют исходные ревизии jobs/source CSV под общим lock; connector stale race получает conflict | `tracker_write.py`, `tracker_ingest.py`, `agent_operations.py`, maintenance repair и тесты stale snapshot/conflict | 236 tests green; strict validation 458/474; `git diff --check` | verified |
| L-0009 | 2026-09-24 | `codex/tracker-v3` / card revision guard change | Обычные и batch writes проверяют исходную ревизию изменяемой application card; появившаяся или изменённая позже карточка не перезаписывается | `tracker_write.py`, `agent_operations.py`, card race tests | 239 tests green; strict validation 458/474; `git diff --check` | verified |
| L-0010 | 2026-09-24 | `codex/tracker-v3` / journal publisher integration change | Dataset writes публикуют CSV/card через recoverable journal; CLI read commands держат lock, connector делает recovery перед request | `tracker_write.py`, `tracker_cli.py`, `agent_operations.py`, process-kill CLI test | 240 tests green; strict validation 458/474; projections fresh; `git diff --check` | verified |
| L-0011 | 2026-09-24 | `codex/tracker-v3` / atomic projections change | Tracker Markdown и три индекса формируются из будущего snapshot и публикуются с CSV/card в одном journal | `tracker_write.py`, `tracker_render.py`, seven-replacement crash test и generation-failure test | 241 tests green; strict validation 458/474; projections fresh; `git diff --check` | verified |

## Entry template

```text
| L-NNNN | YYYY-MM-DD | branch / commit | фактически выполненное действие |
  изменённые артефакты и результат | точные проверки | status |
```
