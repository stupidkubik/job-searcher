# Анализ: эргономика репозитория для ИИ-агентов

> Historical record. Not a contract.

Статус: **исследование** — 2026-09-07. Это не контракт и не план работ.
Основание для плана
[`agent-write-path-plan-2026-09-07.md`](agent-write-path-plan-2026-09-07.md),
который с 2026-09-08 тоже закрыт. Все замеры ниже — снимок на 2026-09-07 и
после реализации плана устарели; свежие цифры даёт
`python3 scripts/maintenance/ops_health.py`.

Что проверено:

- 100 последних прогонов `.github/workflows/agent-operations.yml` через `gh run list` / `gh run view --log-failed`;
- все 137 файлов `data/operations/requests/` против 110 файлов `data/operations/results/`;
- локальная перевалидация каждого «немого» запроса через `python3 scripts/agent_operations.py validate`;
- побайтовые размеры boot-payload и поколоночный вес `data/jobs.csv`;
- статический разбор `scripts/*.py` (AST: длины функций, аннотации, docstring-покрытие);
- тайминги CLI и полного тест-прогона.

Локальный checkout на момент анализа отставал от `origin/main` на 15 коммитов —
это нормально для архитектуры, где коммитит runner, но любой локальный анализ
надо начинать с `git pull`.

---

## 1. Ошибки при добавлении карточек

### 1.1 Фактическая картина

| Метрика | Значение |
|---|---|
| Прогонов `agent operations` (последние 100) | 100 |
| Успешных | 65 |
| Упавших | **35 (35%)** |
| Запросов в `requests/` | 137 |
| Результатов в `results/` | 110 |
| **Запросов без результата** | **27** |
| Результатов `status: conflict` | **12** |

То есть примерно **каждая третья операция агента не доходит до canonical
записи**, и в 27 случаях агент вообще не получил машиночитаемого объяснения:
workflow упал до записи result-файла, а логи GHA агент не читает.

Стадии падения:

| Шаг workflow | Падений |
|---|---|
| `Validate and apply the declarative operation` | 27 |
| `Find the one new request` | 6 |
| `Commit and push the audited result` | 2 |

### 1.2 Таксономия 35 падений

| Ошибка (точный текст из лога) | Раз | Класс |
|---|---|---|
| `unknown add args: next_action` | **12** | контракт полей |
| `unknown add args: verified_at` | **5** (+1 в паре с предыдущей) | контракт полей |
| `duplicate add contains canonical fields that would be ignored: …` | 3 | контракт `duplicate_of` |
| `operations[N].args.remote_policy is not a known value` | 3 | enum |
| `operations[N].args.level is not a known value` | 1 | enum |
| `operations[0].args.first_party_verified must be a string` | 1 | тип значения |
| `operation.args.listing_status must be open or closed` | 1 | контракт `verify` |
| `для непрошедшей verification до отклика нужен --decision-reason` | 1 | инвариант (RU + CLI-флаг) |
| `изменение отклонено:` | 1 | инвариант (RU) |
| `! [rejected] HEAD -> main (fetch first)` | 2 | инфраструктура runner'а |
| push содержал больше одного файла / merge-коммит PR | 6 | процесс доставки |

**17 из 35 падений (49%) — это два поля: `next_action` и `verified_at`.**

Плюс 12 `conflict`-результатов. Это не падение workflow, но потерянная работа:

| Причина конфликта | Раз |
|---|---|
| `batch_child_conflict` → `unresolved_duplicate` | 9 |
| `batch_child_conflict` → `source_reference_conflict` | 1 |
| `stale_operation` (optimistic lock) | 2 |

Худший случай — `hirify-pass4b-20260821`: конфликт на child **#26** откатил
весь batch.

Цена ретраев видна прямо в истории коммитов `main`:

```text
jobs: add Jaabz frontend pass 2026-09-07            → упал (duplicate add … notes)
jobs: retry Jaabz frontend pass without duplicate notes → упал (unknown add args: next_action)
jobs: retry Jaabz frontend pass without add next_action → успех
```

Аналогично: Perena и Epic Games → `-v2`, Constructor → `-r2`, HiringCafe →
«schema retry», Himalayas → `-v2`, LinkedIn email → «retry request format».
Каждая попытка — коммит, прогон workflow и 21 с тестов.

### 1.3 Корневые причины

Ни одна из них не сводится к «агент ошибся». Каждая — свойство документации
или контракта, которое ошибку **провоцирует**.

**RC-1. Нет таблицы «поле × команда».**
`data/schema.md` перечисляет 31 канонический столбец, включая `next_action` и
`verified_at`. Дальше:

| | `next_action` | `verified_at` |
|---|---|---|
| canonical CSV | есть | есть |
| `add` (`jobs.ADD_INPUT_FIELDS`, 20 полей) | **нет** | **нет** |
| `verify` (`VERIFY_ALLOWED_ARGS`) | есть | **нет** |
| `set` (`SET_ALLOWED_ARGS`) | есть | **нет** |
| `status` (`STATUS_ALLOWED_ARGS`) | есть | **нет** |

`verified_at` не принимает **ни одна** connector-команда: его вычисляет runner.
Об этом нет ни слова ни в `data/schema.md`, ни в `data/operations/README.md`.
Агент строит `add.args` из схемы — и попадает в 49% падений.

Отдельно: одинаково названные константы имеют разные значения в разных модулях —
`jobs.ADD_APPLICATION_STATUSES = [not_started, reviewing, apply]`, а
`agent_operations.ADD_APPLICATION_STATUSES = {not_started, reviewing}`.

**RC-2. Enum'ы не лежат рядом с контрактом.**
`REMOTE` не содержит значения `Remote`; `LEVELS` не содержит `Lead`. Что агенты
писали фактически:

```text
remote_policy: "Remote"                   ×4 запроса
remote_policy: "Worldwide remote-first"   ×1
level: "Lead"                             ×2
```

`AGENTS.md` при этом целым пунктом обсуждает слово «Remote» («`Remote` сам по
себе не значит global remote») — то есть подталкивает написать именно это слово,
но нигде не говорит, что канонический ответ — `Unclear`.
В `data/operations/README.md` нет ни одного списка допустимых значений.

**RC-3. `duplicate_of` описан на треть.**
Реальное правило (`ADD_DUPLICATE_ARGS`) — только required-поля плюс
source-reference; любое каноническое поле рядом с `duplicate_of` = ошибка.
README говорит лишь «Optional `duplicate_of` attaches the new source reference
to an existing canonical job». Отсюда 3 падения, причём агенты присылали ровно
то, что README показывает в happy-path примере `add`
(`application_status`, `first_party_verified`, `listing_status`, `notes`, `stack`…).

**RC-4. Типы значений не заявлены.**
`first_party_verified` / `apply_verified` — строки `"yes" | "no" | "unknown"`, но
читаются как булевы. Агент прислал `true`. В README все примеры — happy path;
таблицы «поле → тип → допустимые значения» нет.

**RC-5. Двухслойная валидация с разными языками и разной адресацией.**
`agent_operations.py` — 445 строк, сообщения на английском, 0 строк с кириллицей.
`jobs.py` — 238 строк с кириллицей; его сообщения советуют **CLI-флаги**:
`используйте --force …`, `нужен --decision-reason`, `требует --applied-at`.
У connector'а нет CLI. Когда падает второй слой, агент получает совет, который
физически не может исполнить в JSON, ещё и на другом языке, чем контракт.

**RC-6. Request нельзя проверить до отправки.**
Connector не исполняет shell; `jobs.py --help` ему недоступен. Единственный
доступный «линтер» — сам прогон GHA. Отсюда цепочки ретраев из 1.2.

**RC-7. Обязательный `atomic: true` × fuzzy-дедуп = катастрофический откат.**
Порог в `find_duplicate_candidates`: `company ≥ 0.85` **И** `role ≥ 0.75`
(`difflib.SequenceMatcher`). При этом:

- 25 строк имеют placeholder-компанию — `Undisclosed` ×16, `Unknown` ×5,
  `Unknown (TalentMove source)` ×4. Для них company-score = 1.00 против любой
  другой такой же строки, то есть они работают как генератор ложных совпадений
  (конфликт `hirify-refresh-20260816-03` — ровно этот случай: `Undisclosed`
  1.00 / role 0.75);
- **267 из 394 строк имеют пустой `original_url`** — точный URL-путь дедупа
  почти не работает, и всё сваливается во fuzzy;
- агент не может воспроизвести `SequenceMatcher` по 206 КБ CSV в голове.

Итог: 10 из 12 конфликтов — откат целого batch из-за одного child.

**RC-8. Запрет PR есть, но он мягкий.**
Все 6 падений на шаге `Find the one new request` — merge-коммиты PR'ов
(`Merge pull request #13 … #20`), где diff содержит больше одного файла. Правило
в README есть, но узнаёт о нём агент только по факту, из сообщения
`main must add exactly one …`.

**RC-9. Runner не пересобирается перед push.**
Последний шаг — `git push origin HEAD:main` без `pull --rebase`. Два запроса
подряд: второй проходит валидацию, применяется, пишет result — и теряется на
push (`! [rejected] … fetch first`), потому что checkout сделан на старом SHA.
`concurrency` здесь не спасает: она сериализует прогоны, но не обновляет
checkout. Это и объясняет большинство «локально валидных, но безрезультатных»
запросов.

### 1.4 Направления исправления

Сгруппированы по эффекту, не по порядку выполнения.

| # | Мера | Закрывает | Ожидаемый эффект |
|---|---|---|---|
| P1 | Сгенерированная таблица «поле → тип → допустимые значения → в каких командах разрешено» (`add`, `add + duplicate_of`, `verify`, `screen`, `set`, `status`, batch child) | RC-1, RC-3, RC-4 | ~21 из 35 падений |
| P2 | Расширить `tests/test_documentation.py`: каждое поле из каждого allowlist и каждое enum-значение обязано присутствовать в сгенерированной таблице | дрейф доки | защита P1 |
| P3 | Guidance по enum'ам: «источник пишет просто “Remote” без списка стран → `remote_policy=Unclear`»; решить вопрос добавления `Lead` в `LEVELS` | RC-2 | 4 падения |
| P4 | **Всегда писать `results/<id>.json`** — в том числе при провале валидации, со `status: "rejected"` и машинным `error: {code, field, allowed, hint}` | RC-6 | 27 «немых» падений становятся читаемыми; агент видит ошибку тем же каналом, которого и так ждёт |
| P5 | В conflict-result добавлять готовый к отправке JSON-фрагмент («повторите так, с `duplicate_of: job-NNNN`») | RC-7 | ретрай без угадывания |
| P6 | Сделать `atomic` выбором: `atomic: false` применяет успешные children и возвращает per-child статусы. Либо оставить atomic обязательным, но вернуть «примените без children N, M» | RC-7 | 10 конфликтов |
| P7 | Исключить placeholder-компании (`Undisclosed*`, `Unknown*`) из company-сравнения; для них требовать совпадения по URL / `source_job_id` | RC-7 | ложные срабатывания |
| P8 | `fetch + rebase + повторный push` (до N попыток) в runner'е, с перегенерацией tracker после rebase | RC-9 | 2 падения сейчас, больше при росте темпа |
| P9 | Жёсткий запрет PR: валидировать «HEAD-коммит не merge и добавляет ровно один request», плюс отдельный `pull_request`-check, сразу сообщающий «этот путь доставки не поддерживается» | RC-8 | 6 падений |
| P10 | Единый язык сообщений об ошибках в обоих слоях; убрать CLI-флаги из текстов, адресованных connector'у | RC-5 | 2 падения + читаемость |

Приоритет по соотношению «эффект / стоимость»: **P4 → P1 → P6 → P8 → P9 → P3/P7 → P2 → P5 → P10**.
P4 первым потому, что он превращает все остальные ошибки в самообъяснимые и
снимает зависимость от чтения логов GHA.

---

## 2. Стартовый запрос и долгий фетчинг

### 2.1 Сколько это стоит сейчас

Побайтово, по текущему системному промпту:

| Ресурс | Байт | ≈ токенов |
|---|---:|---:|
| `data/jobs.csv` (394 строки) | 206 543 | ~55–60K |
| `data/job_sources.csv` (409 строк) | 44 392 | ~12K |
| `data/schema.md` | 14 633 | ~4K |
| `AGENTS.md` | 14 588 | ~5K |
| `config/profile.md` | 12 765 | ~5K |
| `data/operations/README.md` (нужен для записи) | 10 449 | ~3K |
| 1 playbook `docs/sources/*` (среднее из 23) | ~6 100 | ~2K |
| **Итого** | **~309 КБ** | **~85K** |

Оценка токенов консервативная (≈3.6 байт/токен); для кириллицы в `AGENTS.md` и
`profile.md` реальный расход выше.

### 2.2 Что из этого реально нужно

Поколоночный вес `data/jobs.csv` (192 525 Б в ячейках):

| Колонка | Байт | Доля | Нужна для дедупа? |
|---|---:|---:|---|
| `notes` | 68 651 | **35.7%** | нет |
| `source_url` | 25 216 | 13.1% | как ключ — да, целиком — нет |
| `stack` | 20 961 | 10.9% | нет |
| `role` | 11 552 | 6.0% | да |
| `original_url` | 8 419 | 4.4% | да |
| `location` | 6 179 | 3.2% | нет |
| `decision_reason` | 5 423 | 2.8% | да |
| `company` | 4 544 | 2.4% | да |
| остальные 23 колонки | ~41 580 | 21.6% | частично |

Более чем треть самого дорогого файла — колонка `notes`, не участвующая ни в
дедупе, ни в решении «анализировать заново или нет».

Профиль датасета: **338 из 394 строк (86%) — `not_started`**, из них
`geo_restriction` 154, `seniority_too_high` 56, `closed_before_application` 41,
`role_not_frontend` 23, `stack_mismatch` 20. То есть `jobs.csv` — прежде всего
архив отсева. Агенту про такую строку нужно знать «уже отсеяна, причина X», а не
31 поле.

### 2.3 Замеренные альтернативы

Всё посчитано на реальных данных репозитория:

| Артефакт | Байт | ≈ токенов |
|---|---:|---:|
| дедуп-индекс TSV (`id, company, role, status, listing, reason, original_url`) | 43 430 | ~12K |
| тот же индекс **без URL** | 29 084 | ~8K |
| ключевой индекс `source`/`source_job_id`, сгруппированный по источнику с вырезанным общим префиксом | **12 885** | ~3.6K |
| активный срез (48 строк: `reviewing`/`apply`/`applied`/`interviewing`/`offer` + `not_started` без `decision_reason`), все 31 поле | 30 000 | ~8K |

**Предлагаемый boot-bundle** = дедуп-индекс без URL + ключевой индекс +
активный срез ≈ **42 КБ ≈ 12K токенов** вместо 251 КБ / ~70K на
`jobs.csv` + `job_sources.csv`.

Экономия: **~6× на данных, ~3.5× на всём бутстрапе** (85K → ~24K токенов).

### 2.4 Варианты реализации

| Вариант | Суть | Плюсы | Минусы |
|---|---|---|---|
| **В1** | Генерируемые индексы в репо: `data/index/known.tsv`, `data/index/keys.tsv`, `data/index/active.csv`; обновляются той же командой, что и tracker, тем же runner'ом | connector читает 3 маленьких файла; ноль новых capability; обратно совместимо | +3 генерируемых файла в allowlist и в diff |
| В2 | Один `data/index/boot.md`: дайджест профиля + таблица контракта + индексы | один GET вместо шести | файл 60–80 КБ перезаписывается каждой операцией → шумный diff |
| В3 | Не генерировать, а сузить формулировку промпта («читать только колонки …») | ноль работы | **не работает**: connector отдаёт файл целиком, обрезать нельзя |
| В4 | Вынести архив отсева в `data/screened.csv`, оставить в `jobs.csv` только активное | самый большой выигрыш; дедуп по архиву — отдельный дешёвый файл | ломает «единственный источник истины»; миграция схемы, переписывание валидаторов и 177 тестов |

**Рекомендация: В1 + дайджест профиля** (`config/profile.md` 12.7 КБ → ~3 КБ
машиночитаемого блока: гео, уровень, стек, минимальная компенсация,
work authorization). В4 — только если после В1 бутстрап всё ещё дорог.

Отдельно: `docs/tracker.md` — 82 КБ, перезаписывается каждой операцией. Он
предназначен человеку, но лежит в том же дереве, что агентские данные. Стоит
явно записать в контракт: «tracker — только для человека, агент его не читает и
не включает в request».

### 2.5 Оценка системного промпта

Четыре абзаца, ~1 400 знаков.

**Что работает и надо сохранить:**

- явный запрет подменять Browser на web search / cached results / `Crawled:`
  метаданные — подтверждается контрактом и правильно сформулирован;
- явный запрет отправлять заявки и ставить `applied`;
- preflight-протокол с требованием назвать точное ограничение и остановиться.

**Что стоит поправить:**

1. **`read the full data/jobs.csv … data/job_sources.csv`** — это и есть ~70K
   токенов. Заменить на boot-bundle из 2.4; полный CSV — только по явной
   необходимости.
2. **Ни слова о контракте полей.** Промпт отправляет агента в
   `data/operations/README.md` только на этапе записи
   («Write only through immutable connector requests described in …»). Именно
   поэтому 49% падений — про поля. Нужна инструкция читать таблицу
   «поле × команда» **до** составления request и не передавать поля вне таблицы.
3. **Нет запрета PR и multi-file коммита** — ровно 6 из 35 падений.
4. **Нет правила ожидания результата и ретрая.** Нужно: дождаться
   `results/<operation_id>.json`; при ретрае создавать **новый** `operation_id`,
   а не перезаписывать существующий request (агенты и так делают `-v2`/`-r2`, но
   по наитию).
5. **`record every inspected exact vacancy — even closed, unsuitable, or
   duplicate`** — правило само по себе верное, но в паре с обязательным
   `atomic: true` именно оно генерирует batch'и по 27 элементов, откатывающиеся
   целиком. Либо P6, либо ограничение размера batch в промпте.
6. Нет стоп-листа полей. До внедрения P1 достаточно одной строки про
   `next_action` / `verified_at` — это снимет половину падений немедленно.
7. `the relevant playbook in docs/sources/` — агент не знает, какой релевантен,
   пока не прочитает `docs/sources/README.md`. Стоит назвать этот файл явно.
8. Промпт и `data/operations/README.md` — по-английски, `AGENTS.md` и
   сообщения `jobs.py` — по-русски. См. серую зону G-1.

**Черновик переписанного промпта** (заглушки `<...>` заполняются после P1/В1):

```text
Use @GitHub to open https://github.com/stupidkubik/job-searcher and follow AGENTS.md. Use @Browser—not web search—for every source page, employer careers/ATS listing, and Apply-route check.

Bootstrap by reading exactly these, through GitHub, in this order: data/index/boot.md (candidate digest + field contract), data/index/known.tsv and data/index/keys.tsv (deduplication indexes), data/index/active.csv (open work), docs/sources/README.md and the one playbook it names for the requested source. Do not read data/jobs.csv, data/job_sources.csv, or docs/tracker.md unless an index is insufficient for a specific decision; say why when you do.

Then perform a Browser preflight: open the requested source URL in @Browser and report whether it loaded as an interactive rendered page. If Browser is unavailable, blocked, or cannot load the page, stop and report the exact limitation. Do not silently substitute web search, cached/indexed results, Crawled metadata, or GitHub tools.

Search the requested source using its playbook. Deduplicate against the indexes before analysis, verify every promising job on the employer's current careers/ATS page, check the actual Apply route and geographic eligibility, and record every inspected exact vacancy—even closed, unsuitable, or duplicate.

Write only through immutable connector requests. Before building a request, read the field contract table in <file> and pass only fields it allows for that command—an unlisted field or an off-enum value is rejected by the runner. Commit exactly one new file, data/operations/requests/<operation_id>.json, directly to main; never open a pull request and never touch another file in that commit. Keep a batch at 10 children or fewer. Then wait for data/operations/results/<operation_id>.json and the runner's canonical diff before reporting the operation complete; if a result reports rejected or conflict, fix the cause and submit a NEW operation_id—never rewrite an existing request. Never edit canonical CSV files or docs/tracker.md, never submit applications, and never set a job to applied.
```

---

## 3. Оценка проекта с точки зрения эффективности

### 3.1 Что сделано хорошо

- **Zero-dependency stdlib CLI.** Единственная зависимость (`Telethon`) —
  опциональный Telegram-адаптер.
- **Продуманная trust boundary.** Immutable request/result, optimistic locking
  по `expected`, `apply_dataset_transaction`, changed-path allowlist в runner'е,
  запрет request-provided shell. Для личного трекера это заметно выше среднего.
- **Quality gates.** `validate --strict`, `render-tracker --check` (exact
  freshness), 177 unit-тестов, `dupes` как отчёт, а не автослияние.
- **Дисциплина документации.** `docs/README.md` содержит и карту актуальных
  документов, и «матрицу обновлений» (что править в одном коммите с чем).
  Раздел Historical помечен.
- **Производительность не является проблемой.** Замеры на 394 строках:

  | Команда | Время |
  |---|---:|
  | `todo --format json` | 0.14 с |
  | `stats --format json` | 0.12 с |
  | `validate --strict` | 0.12 с |
  | `dupes --format json` | 0.12 с |
  | `render-tracker --check` | 0.12 с |
  | полный `unittest discover` (177 тестов) | 21.3 с |

  Узкого места в рантайме нет и при 5–10× росте данных не будет. Единственный
  заметный расход — 21 с тестов на каждую агентскую операцию в CI; это
  осознанная плата за гарантию.

### 3.2 Что мешает

| Наблюдение | Замер | Почему важно для агента |
|---|---|---|
| `scripts/jobs.py` — монолит | 3 195 строк / 140 КБ, 136 функций, 6 классов. Длиннейшие: `plan_ingest` 202 стр., `main` 134, `validate_rows` 117, `stats_payload` 116, `apply_status_change` 94 | чтобы узнать контракт `add`, надо прочитать 140 КБ или довериться доке, которая расходится |
| Нет аннотаций типов | **0 из 136** функций `jobs.py` аннотированы | нельзя вывести типы полей ни автоматически, ни глазами |
| Docstring-покрытие | `jobs.py` 32/136; **`agent_operations.py` 0/31** | policy-файл, определяющий, что примет GHA, не описан вообще |
| Плотный стиль `agent_operations.py` | 111 из 445 строк длиннее 100 символов, `;`-конкатенация | именно из него надо генерировать таблицу контракта |
| Нет тулинга | нет `pyproject.toml`, ruff, black, mypy, pre-commit; в `validate.yml` нет lint-шага | каждый агент пишет в своём стиле |
| Возможное дублирование | `import_telegram.py` 790 стр. + `telegram_leads.py` 800 стр. = 1 590 стр. ≈ **26% всего кода** на один опциональный источник | непонятно, оба ли живые |
| Одноразовые миграции в CLI | `migrate-v2`, `repair-himalayas-screening`, `backfill-sources` в основном `--help` | агент видит их наравне с рабочими командами |
| Смешение языков | `jobs.py` — 238 строк с кириллицей, `agent_operations.py` — 0 | см. RC-5 |
| Исторические доки без баннера | 208 КБ из 395 КБ `docs/*.md` — планы и аудиты. Индекс их помечает, но в самих файлах баннера нет | агент, попавший в `setup-plan.md` через grep, прочитает схему с полем `status` и `02-applications.csv`; в `architecture.md` остался мусор вида `fileciteturn1file0` |
| Качество данных | 267 из 394 строк с пустым `original_url`; 25 строк с placeholder-компанией | ломает точный дедуп, кормит fuzzy (RC-7) |
| Мелкий дрейф доки | `docs/agent-operations.md` в одном месте всё ещё говорит «canonical diff/PR», хотя PR-путь отменён | |

**Общий вывод по коду.** Проект не «плохо написан» — он вырос без разбиения.
Архитектурные решения (immutable operations, optimistic lock, transaction,
allowlist) заметно сильнее, чем гигиена реализации (типы, докстринги, размер
модуля, линтер). Для ИИ-агента это ровно та комбинация, которая создаёт
описанные в разделе 1 проблемы: контракт строгий и правильный, но узнать его
можно только из 140 КБ неаннотированного кода либо из доки, которая от кода
отстаёт.

---

## 4. Пул неопределённостей и серых зон

Вопросы, которые я не могу решить из кода — нужно решение владельца.
Рекомендация помечена ✅.

**G-1. Язык машиночитаемых контрактов и сообщений об ошибках.**
Сейчас: `AGENTS.md`, `CLAUDE.md`, сообщения `jobs.py` — русский;
`data/operations/README.md`, `agent_operations.py`, системный промпт — английский.
- A ✅ Всё агентское (контракты + все сообщения об ошибках) — английский; человеческое (`profile.md`, `reports/`) — русский.
- B Всё на русском, включая operations README и промпт.
- C Оставить как есть.

**G-2. Кто источник истины для набора полей команды.**
- A ✅ Таблица генерируется из кода, тест-гвардия проверяет совпадение (single source = код).
- B README остаётся ручным, тест лишь проверяет, что каждое поле из allowlist где-то упомянуто.
- C Ввести отдельный JSON Schema, из которого генерируются и валидатор, и дока (дороже, но убирает двухслойность RC-5).

**G-3. Как агент узнаёт об ошибке.**
- A ✅ Всегда писать `results/<id>.json` со `status: "rejected"` и структурированной ошибкой.
- B Отдельный `workflow_dispatch` `validate-request` (dry-run) — требует проверки, есть ли у connector'а право на dispatch.
- C Оба.
Подвопрос: считать ли `rejected` result immutable и требовать ли новый `operation_id` для ретрая? (Сейчас агенты и так делают `-v2`/`-r2`.)

**G-4. Атомарность batch.**
- A ✅ Разрешить `atomic: false` с per-child результатами для discovery-pass'ов.
- B Оставить atomic обязательным, но ограничить batch 10 children и возвращать «повторить без N, M».
- C Оставить как есть, решать дедуп до отправки (зависит от G-5).

**G-5. Fuzzy-дедуп.**
- A Исключить placeholder-компании из company-сравнения, требовать URL / `source_job_id`.
- B Поднять порог `role` с 0.75 до 0.85.
- C Отдать агенту read-only индекс нормализованных `company`/`role`, чтобы он сверялся сам (совмещается с В1).
- D ✅ A + C (B — только если ложные срабатывания останутся).

**G-6. Формат компактного бутстрапа.** В1 / В2 / В4 из раздела 2.4. ✅ В1.

**G-7. 267 строк с пустым `original_url`.**
- A Требовать `original_url` для каждого нового `add` с `first_party_verified=yes`.
- B Одноразовый backfill: `original_url` из `source_url`, где источник и есть первоисточник (`Company Careers` и подобные).
- C ✅ A + B (A предотвращает рост проблемы, B чистит накопленное).
- D Ничего, полагаться только на `source|source_job_id`.

**G-8. Push race в runner'е.**
- A ✅ `fetch + rebase + retry` (до N попыток) перед push, с перегенерацией tracker после rebase.
- B Сериализовать жёстче: `concurrency` + повторный `workflow_dispatch`.
- C Принять потерю второй операции при быстрой серии.

**G-9. Разбиение `scripts/jobs.py`.**
- A Не трогать; добавить только аннотации публичных функций и docstring'и в `agent_operations.py`.
- B ✅ Разбить на пакет (`schema` / `validate` / `write` / `render` / `ingest` / `cli`) одним рефакторингом под 177 существующими тестами — **но отдельным этапом, после исправления контракта**.
- C Переписать с нуля.

**G-10. Тулинг.**
- A ✅ `pyproject.toml` + ruff (lint + format) + lint-шаг в `validate.yml`; mypy не включать.
- B То же + mypy strict на новом коде.
- C Ничего.

**G-11. Два Telegram-скрипта.** `import_telegram.py` (790) и `telegram_leads.py` (800) — 26% кодовой базы. Живы ли оба? Из кода намерение не восстанавливается.
- A Оставить один, второй архивировать/удалить.
- B ✅ Оставить оба и задокументировать разделение ответственности.

**G-12. Одноразовые миграции в CLI-поверхности** (`migrate-v2`, `repair-himalayas-screening`, `backfill-sources`).
- A ✅ Перенести в `scripts/maintenance/`, убрать из основного `--help`.
- B Оставить.

**G-13. Исторические документы (208 КБ).**
- A ✅ Баннер `> Historical record. Not a contract.` в начало каждого + проверка в тест-гвардии.
- B Перенести в `docs/history/`.
- C Удалить (потеря истории решений).

**G-14. `docs/tracker.md` (82 КБ) в каждом коммите операции.**
- A ✅ Оставить: человеку нужен, шумный diff безвреден; добавить в контракт «агент tracker не читает».
- B Не коммитить, генерировать по требованию — но теряется гарантия «свежий tracker в audited-коммите».

**G-15. Цель по частоте операций.** От неё зависит приоритет P8/G-8 и вообще
разумность 21-секундного тест-прогона на операцию. Сейчас темп ~5–10 операций в
день. Если цель — десятки за проход, push race и atomic batch становятся
блокирующими; ✅ если единицы — можно оставить как есть.
