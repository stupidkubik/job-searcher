# План browser-first представления job tracker

Статус: implemented — 2026-08-12

Результат: [`tracker.md`](tracker.md), команда `render-tracker`, freshness gate
в CI и trusted connector runner. Этот план сохранён как specification и record
принятых решений.

Основание: [`tracker-status-audit-2026-08-12.md`](tracker-status-audit-2026-08-12.md)

Целевой интерфейс: [`docs/tracker.md`](tracker.md) в GitHub

Canonical source of truth: [`data/jobs.csv`](../data/jobs.csv)

## 1. Решение

Добавить в репозиторий автоматически генерируемую Markdown-страницу
`docs/tracker.md` и сделать её основным интерфейсом для ежедневной работы в
браузере.

`data/jobs.csv` остаётся единственным структурированным источником истины.
`docs/tracker.md` является только детерминированной read-only проекцией: её
нельзя редактировать вручную, а CI обязан проверять, что она соответствует
canonical данным.

Целевой пользовательский flow:

1. Пользователь держит открытой постоянную GitHub-ссылку на
   `docs/tracker.md` в `main`.
2. Во второй вкладке открывает первоисточник вакансии.
3. Для изменения состояния пишет агенту, например: `job-0088 rejected`.
4. Connector создаёт декларативную operation, trusted runner применяет её.
5. Runner изменяет `data/jobs.csv` и пересобирает `docs/tracker.md` в том же
   commit.
6. После обновления страницы пользователь видит новое состояние без CLI и
   редактора кода.

## 2. Цели и границы

### Цели первой версии

- Быстро понимать состояние каждого кейса без чтения сырой схемы CSV.
- Оставить браузер и GitHub единственным необходимым UI для пользователя.
- Показывать `case_status` как главный статус, а listing verification — как
  отдельное свойство.
- Давать прямые ссылки на вакансию и существующую application card.
- Автоматически обновлять представление после connector operations.
- Не допускать merge canonical изменений с устаревшим `docs/tracker.md`.
- Сохранить существующие validation, provenance и write-path invariants.

### Не входит в первую версию

- GitHub Pages, отдельный frontend, JavaScript-фильтры или сервер.
- Редактирование статусов из самой Markdown-страницы.
- Новый столбец `case_status` в `data/jobs.csv`.
- Изменение enum `listing_status` или массовый backfill `unknown`.
- Отдельная база, кеш или ручная копия tracker data.
- Ежедневная генерация только ради календарной даты.
- CLI `list --view ...`: structured view можно добавить позже поверх тех же
  функций, если он понадобится агентам или локальной аналитике.

## 3. Информационная архитектура страницы

`docs/tracker.md` состоит из пяти блоков.

### 3.1. Заголовок и служебная информация

В начале страницы показываются:

- предупреждение `Generated file — do not edit manually`;
- ссылка на canonical `data/jobs.csv`;
- дата последнего изменения dataset как максимальный непустой `last_update`;
- общее количество вакансий;
- навигация по секциям с их количествами.

Текущая календарная дата в файл не записывается. Иначе неизменившийся dataset
создавал бы новый diff каждый день и делал генерацию недетерминированной.

Пример:

```markdown
# Job tracker

> Generated from [`data/jobs.csv`](../data/jobs.csv). Do not edit manually.

Dataset updated: **2026-08-12** · Jobs: **131**

[Action now (3)](#action-now) · [Applications (17)](#applications) ·
[To verify (10)](#to-verify) · [Archive (101)](#archive)
```

Числа в примере иллюстративны и всегда вычисляются из текущего dataset.

### 3.2. `Action now`

Сюда попадают активные pre-application кейсы, для которых first-party/apply
verification уже достаточно и нет terminal decision:

```text
application_status in {not_started, reviewing, apply}
listing_status == open
decision_reason is empty
first_party_verified == yes
apply_verified == yes
```

`listing_status=unknown` always stays in `To verify` with `Need: Listing`, even
when both verification flags are `yes`. This keeps the sections mutually
exclusive and prevents an unconfirmed listing from appearing as actionable.

Колонки:

| Колонка | Значение |
|---|---|
| `Status` | display label вычисляемого `case_status` |
| `Vacancy` | company + role, ссылка на первоисточник |
| `Match` | `match_score` или `—` |
| `Next action` | действие и дата одной строкой |
| `Listing` | `Open`, `Closed` или `Not checked` |
| `Card` | ссылка на `applications/<job-id>-*.md`, если card существует |

Сортировка:

1. `apply`;
2. `reviewing`;
3. `not_started`;
4. заполненная `next_action_date` по возрастанию;
5. `match_score` по убыванию;
6. `id` по возрастанию.

### 3.3. `Applications`

Сюда попадают все кейсы после отправки заявки, включая завершённые:

```text
application_status in {
  applied, interviewing, offer, rejected, ghosted, withdrawn
}
```

`Rejected`, `Ghosted` и `Withdrawn` остаются в истории откликов, а не
переносятся в общий pre-application archive. Это сохраняет понятную картину
воронки.

Колонки:

| Колонка | Значение |
|---|---|
| `Status` | `Applied`, `Interviewing`, `Offer`, `Rejected`, `Ghosted`, `Withdrawn` |
| `Vacancy` | company + role со ссылкой |
| `Stage` | `stage_reached` или `—` |
| `Applied` | `applied_at` или `—` |
| `Next action` | действие и дата либо `—` |
| `Card` | application card, если существует |

Сортировка:

1. `offer`;
2. `interviewing`;
3. `applied`;
4. `rejected`;
5. `ghosted`;
6. `withdrawn`;
7. внутри группы — `next_action_date`, затем `last_update` по убыванию и `id`.

Так активные процессы всегда находятся выше исторических исходов.

### 3.4. `To verify`

Сюда попадает оставшаяся активная pre-application очередь, которой не хватает
first-party или Apply verification:

```text
application_status in {not_started, reviewing, apply}
listing_status != closed
decision_reason is empty
and at least one condition is true:
  listing_status == unknown
  first_party_verified != yes
  apply_verified != yes
```

Секция взаимоисключающая с `Action now`: одна вакансия не дублируется в обеих
таблицах. После успешной `verify` operation строка автоматически переходит из
`To verify` в `Action now` либо в `Archive`, если обнаружен blocker/closure.

Колонки:

| Колонка | Значение |
|---|---|
| `Status` | текущий display case status |
| `Vacancy` | company + role со ссылкой |
| `Need` | `First party`, `Apply`, `Listing` или их комбинация |
| `Match` | `match_score` или `—` |
| `Next action` | действие и дата либо `verify first-party` |
| `Last checked` | `verified_at` или `Never` |

Сортировка:

1. `apply`;
2. `reviewing`;
3. `not_started`;
4. `match_score` по убыванию;
5. `found_at` по убыванию;
6. `id` по возрастанию.

### 3.5. `Archive`

Сюда попадают только pre-application terminal decisions:

```text
derived_state is Closed, Duplicate or starts with "Skipped:"
```

Секция оборачивается в `<details>` и по умолчанию свёрнута, чтобы десятки
исторических строк не заслоняли активную работу. Полный архив остаётся на той
же странице и доступен без отдельного поиска.

Колонки:

| Колонка | Значение |
|---|---|
| `Status` | `Closed`, `Duplicate` или display label причины skip |
| `Vacancy` | company + role со ссылкой |
| `Decision` | человекочитаемый `decision_reason` |
| `Listing` | display listing status |
| `Updated` | `last_update` |

Сортировка: `last_update` по убыванию, затем numeric job ID по убыванию.

## 4. Правила отображения

### 4.1. Основной статус

Доменным источником остаётся существующая функция `derived_state(row)`. Для
Markdown добавляется только display mapping, не влияющий на schema:

| Domain value | Display value |
|---|---|
| `Not started` | `Not started` |
| `Reviewing` | `Reviewing` |
| `Apply` | `Ready to apply` |
| `Skipped: geo_restriction` | `Skipped: geo restriction` |
| `Skipped: seniority_too_high` | `Skipped: seniority too high` |
| остальные `Skipped: <reason>` | underscore заменяется пробелом |
| остальные состояния | без изменения |

Не добавлять emoji и цветовые маркеры в первую версию: текст должен оставаться
однозначным, хорошо искаться через browser find и не зависеть от темы GitHub.

### 4.2. Listing status

| Canonical | Display |
|---|---|
| `unknown` | `Not checked` |
| `open` | `Open` |
| `closed` | `Closed` |

`unknown` никогда не преобразуется в canonical данных. Verification detail
показывается отдельно в `To verify`; в остальных таблицах listing остаётся
коротким вторичным свойством.

### 4.3. Ссылки

Для ссылки на вакансию используется первый доступный URL:

1. `original_url`;
2. canonical `source_url`;
3. primary reference из `data/job_sources.csv`;
4. если URL нет, показывается обычный текст без ссылки.

Application card определяется по единственному файлу
`applications/<job-id>-*.md`. Ноль файлов допустим; больше одного для одного ID
считается ошибкой генерации и должно быть исправлено до публикации.

Все относительные ссылки строятся от `docs/tracker.md`. Внешними считаются
только уже прошедшие canonical validation URL со схемой `http` или `https`.

### 4.4. Безопасный Markdown

Значения из dataset рассматриваются как данные, а не как готовый Markdown.
Renderer обязан экранировать как минимум `\\`, `|`, `<`, `>`, backticks и
квадратные скобки. URL нельзя вставлять как raw HTML. Новые строки всё равно
запрещены canonical schema, но renderer не должен полагаться только на это
ограничение.

Пустая секция выводит `No jobs.` вместо пустой таблицы.

## 5. Контракт генератора

Добавить read-only команду:

```bash
python3 scripts/jobs.py render-tracker
python3 scripts/jobs.py render-tracker --check
python3 scripts/jobs.py render-tracker --check --format json
```

Поведение:

- без `--check` атомарно записывает `docs/tracker.md`;
- `--check` ничего не пишет и завершается с кодом `1`, если committed artifact
  отсутствует или отличается от ожидаемого;
- `--format json` возвращает один object с `ok`, `command`, `path`, `up_to_date`
  и counts четырёх секций;
- повторный запуск на одинаковых входных bytes даёт идентичный результат;
- команда не меняет `data/jobs.csv`, `data/job_sources.csv` и application cards;
- до рендера выполняется dataset validation; invalid canonical state не может
  породить новый dashboard;
- запись идёт через временный файл рядом с target и `os.replace`, чтобы
  прерванный процесс не оставил частичный Markdown.

Путь `docs/tracker.md` фиксируется константой относительно `ROOT`. Произвольный
`--output` в первой версии не нужен: один canonical artifact упрощает CI и не
позволяет плодить конкурирующие представления.

## 6. Внутренняя структура кода

В `scripts/jobs.py` добавить небольшие чистые функции:

```text
tracker_section(row)
    → action_now | applications | to_verify | archive

tracker_item(row, source_references, application_cards)
    → structured display object without Markdown

tracker_payload(rows, source_references, application_cards)
    → counts + deterministically sorted section items

render_tracker_markdown(payload)
    → complete UTF-8 Markdown string ending with one newline

write_or_check_tracker(markdown, check)
    → atomic write or exact-byte comparison
```

Классификацию не размещать непосредственно внутри `cmd_render_tracker`: она
понадобится тестам и возможному будущему `list --view`/HTML renderer.

`tracker_section` должен гарантировать ровно одну primary section для каждой
canonical строки. Если новая комбинация schema полей не классифицируется,
генерация завершается ошибкой, а не молча скрывает вакансию.

В JSON payload хранить domain values и отдельные display labels. Это не даст
presentation mapping случайно превратиться в новый доменный контракт.

## 7. Автоматическое обновление

### 7.1. Trusted connector runner

В `.github/workflows/agent-operations.yml` после успешного применения operation
и strict validation выполнить:

```bash
python3 scripts/jobs.py render-tracker
python3 scripts/jobs.py render-tracker --check
```

Затем:

- добавить `docs/tracker.md` в changed-file allowlist;
- добавить его в явный `git add` шага audited result;
- оставить request/result/application/canonical ограничения без изменений;
- не требовать обязательного diff `docs/tracker.md`: операция может изменить
  поле, которое не влияет на view, и exact check всё равно подтвердит
  актуальность файла;
- result operation остаётся immutable; dashboard не включается в operation
  request и не считается canonical side effect.

При direct operation в `main` CSV и tracker page попадут в один bot commit. При
review mode оба изменения попадут в operation PR и будут видны до merge.

### 7.2. Обычный pull request CI

В `.github/workflows/validate.yml` после strict dataset validation добавить:

```bash
python3 scripts/jobs.py render-tracker --check
```

Это покрывает изменения через локальный CLI, миграции, maintenance scripts и
ручные PR. Если contributor изменил canonical dataset, но не пересобрал view,
CI сообщает точную команду исправления.

Не добавлять отдельный bot workflow, который исправляет чужой PR после push:
проверка должна быть предсказуемой, а автоматическая запись остаётся только в
trusted connector workflow.

### 7.3. Правила репозитория

Обновить `AGENTS.md`:

- после canonical write выполнять strict validation, затем `render-tracker` и
  freshness check;
- запрещено вручную редактировать `docs/tracker.md`;
- connector runner коммитит view вместе с результатом operation.

Обновить `README.md`:

- первой ссылкой для ежедневной работы сделать `docs/tracker.md`;
- `data/jobs.csv` описать как canonical storage, а не основной UI;
- оставить ссылки на schema и CLI для maintenance.

## 8. Изменяемые файлы

| Файл | Изменение |
|---|---|
| `scripts/jobs.py` | классификация, payload, Markdown renderer, CLI command |
| `tests/test_jobs.py` | unit/CLI/golden assertions для view и `--check` |
| `docs/tracker.md` | первый generated artifact на текущем dataset |
| `.github/workflows/agent-operations.yml` | render, allowlist и commit generated file |
| `.github/workflows/validate.yml` | freshness check |
| `AGENTS.md` | новое правило generated view |
| `README.md` | browser-first entry point |
| `docs/jobs-cli.md` | контракт `render-tracker` |
| `docs/agent-operations.md` | generated view как side effect trusted runner |

`data/schema.md`, `data/jobs.csv` и `data/job_sources.csv` для реализации менять
не требуется.

## 9. Тестовый план

### 9.1. Классификация

Покрыть отдельными строками:

- fully verified `not_started`, `reviewing`, `apply` → `Action now`;
- непроверенные `not_started`, `reviewing`, `apply` → `To verify`;
- `applied`, `interviewing`, `offer`, `rejected`, `ghosted`, `withdrawn` →
  `Applications`;
- `closed_before_application`, любой screening reason и `duplicate_listing` →
  `Archive`;
- closed listing после отправки остаётся в `Applications`;
- все строки входят ровно в одну primary section;
- сумма section counts равна количеству canonical jobs.

### 9.2. Presentation

Проверить:

- `unknown` отображается как `Not checked`;
- `Apply` отображается как `Ready to apply`;
- underscore в skip reason не показывается пользователю;
- пустые значения становятся `—`;
- source и application links относительные/абсолютные и кликабельные;
- special Markdown characters в company/role не ломают таблицу;
- archive действительно находится внутри закрытого `<details>`;
- порядок секций и строк стабилен.

### 9.3. Детерминизм и freshness

Проверить:

- два render запуска без изменения входа дают одинаковые bytes;
- первый write создаёт файл атомарно;
- `--check` успешен для свежего файла;
- `--check` падает для отсутствующего или изменённого файла и ничего не пишет;
- изменение отображаемого canonical поля делает `--check` красным;
- invalid dataset не перезаписывает существующий tracker;
- JSON output является одним валидным object без смешанного text output.

### 9.4. Workflow contract

Расширить существующие workflow-тесты assertions:

- agent runner вызывает `render-tracker` после apply;
- `docs/tracker.md` разрешён changed-file allowlist;
- `git add` включает `docs/tracker.md`;
- обычный validation workflow выполняет `render-tracker --check`;
- остальные ограничения operation gateway не ослаблены.

### 9.5. Полная проверка

Перед публикацией выполнить:

```bash
python3 scripts/jobs.py render-tracker
python3 scripts/jobs.py render-tracker --check --format json
python3 scripts/jobs.py validate --strict --format json
python3 -m unittest discover -s tests -v
git diff --check
```

После генерации вручную открыть `docs/tracker.md` на GitHub preview и проверить:

- все таблицы читаются без горизонтального хаоса на обычной ширине окна;
- ссылки на несколько внешних вакансий и application cards работают;
- archive сворачивается;
- browser find по job ID, company и status находит ожидаемые строки.

## 10. Порядок реализации

### Этап 0. Предусловие

Сначала merge PR с аудитом и connector `status`, затем начать новую ветку от
актуального `main`. Это не смешивает уже проверенную lifecycle-функциональность
с новым generated UI.

### Этап 1. Pure view model

1. Зафиксировать classification и sorting tests.
2. Реализовать `tracker_section`, display mapping и structured payload.
3. Проверить полное покрытие текущего dataset без скрытых строк.

Результат: доменная проекция существует независимо от Markdown.

### Этап 2. Markdown renderer

1. Реализовать escaping и link resolution.
2. Реализовать четыре секции и collapsed archive.
3. Добавить atomic write и `--check`.
4. Сгенерировать первый `docs/tracker.md`.

Результат: готовая постоянная GitHub-страница, которую уже можно использовать
вручную.

### Этап 3. Automation и freshness gate

1. Встроить render в trusted operation workflow.
2. Расширить changed-file allowlist и commit paths.
3. Добавить `render-tracker --check` в обычный CI.
4. Добавить workflow regression tests.

Результат: connector operation и dashboard больше не могут разойтись незаметно.

### Этап 4. Browser-first handoff

1. Обновить `README.md`, `AGENTS.md` и CLI/operation docs.
2. Запустить полный test/validation набор.
3. Проверить Markdown в реальном GitHub preview.
4. После merge заменить постоянную рабочую вкладку с `data/jobs.csv` на
   `docs/tracker.md` в `main`.

## 11. Логичные коммиты

Рекомендуемое разделение:

```text
jobs: add generated browser tracker view
ci: keep browser tracker synchronized
docs: make browser tracker the default human view
```

Первый commit включает generator, тесты и первый generated artifact. Второй —
workflow integration и workflow assertions. Третий — только human/agent
documentation. Такое разделение позволяет отдельно проверить renderer,
automation policy и изменение рабочего процесса.

## 12. Критерии готовности

Реализация считается завершённой, когда одновременно выполнено следующее:

- В `main` есть постоянная кликабельная страница `docs/tracker.md`.
- Каждая canonical вакансия находится ровно в одной primary section.
- Главный статус строки вычисляется из `derived_state`, а `unknown` показан как
  `Not checked`.
- Пользователь может открыть вакансию и application card из таблицы.
- Archive не мешает активной работе и доступен на той же странице.
- Connector operation, меняющая отображаемые данные, обновляет Markdown в том
  же audited commit/PR.
- CI блокирует stale или вручную изменённый `docs/tracker.md`.
- Повторный render идемпотентен и не создаёт diff.
- Canonical schema и существующий write-path не расширены обходным способом.
- Strict validation и полный test suite проходят.
- Для ежедневного browser flow не нужен открытый editor или terminal.

## 13. Риски и меры

| Риск | Мера |
|---|---|
| Generated Markdown станет второй ручной базой | warning в файле + exact CI check + запрет ручной правки |
| Dashboard устареет после connector operation | render и commit внутри trusted workflow |
| Строка исчезнет из всех views | exhaustive classifier + invariant `sum(counts) == jobs_total` |
| `unknown` снова будет восприниматься как неизвестный outcome | display `Not checked`, отдельно от `case_status` |
| Большой archive ухудшит чтение | collapsed `<details>` и сортировка по свежести |
| External text сломает Markdown | обязательное escaping и link-scheme validation |
| Изменение времени создаёт diff без данных | не использовать wall-clock time при генерации |
| Изменение workflow ослабит gateway | отдельные assertions на allowlist и неизменность policy |

## 14. Rollback

Generated view не участвует в canonical логике, поэтому rollback безопасен:

1. убрать freshness check и render step из workflows;
2. удалить `docs/tracker.md` и CLI command;
3. вернуть ссылку README на `data/jobs.csv`.

Canonical CSV, operation history и application cards при этом не меняются.
