# Source search lifecycle

Этот документ — единственный нормативный playbook для поиска вакансий. Он
описывает общий lifecycle независимо от сайта, ATS, browser flow или adapter.
Файлы `<source>.md` рядом с ним содержат только отличия конкретного источника:
routes, фильтры, identity, stale/archive signals, trust boundaries, ловушки и
stop rule.

## Границы слоёв

| Ответственность | Источник истины |
|---|---|
| профиль, география, уровень и доказанный опыт | [`config/profile.md`](../../config/profile.md) |
| общие query families | [`config/search-queries.md`](../../config/search-queries.md) |
| включённые adapters, cadence и машинная политика | [`config/sources.toml`](../../config/sources.toml) |
| универсальный search lifecycle | этот документ |
| особенности сайта или ATS | `docs/sources/<source>.md` |
| canonical schema и enum | [`data/schema.md`](../../data/schema.md) |
| raw batch contract | [`data/inbox/README.md`](../../data/inbox/README.md) |
| разрешённые записи | [`AGENTS.md`](../../AGENTS.md) и [`data/operations/README.md`](../../data/operations/README.md) |

Source-playbook не копирует профиль, lifecycle, CSV schema, команды записи или
общий checklist. При конфликте source-side данных с работодателем canonical
status определяет first-party источник.

## Термины и инварианты

**Exact vacancy** — одна конкретная вакансия, которую можно идентифицировать
exact URL или стабильным source/requisition ID. Search page, category, company
profile и generic careers page не являются exact vacancy.

**Discovery source status** — состояние карточки на площадке: live, archived,
removed, stale или unknown. Это provenance-сигнал, а не автоматически
`listing_status`.

**Canonical employer status** — состояние exact вакансии на текущей публичной
careers/ATS surface работодателя и её Apply route. Именно оно определяет
`listing_status`, `first_party_verified` и `apply_verified`.

Общие инварианты:

- discovery source сохраняется в `source`/source reference; ATS-хост не
  подменяет provenance;
- один canonical job может иметь несколько source references;
- каждая exact vacancy, которую открыли и оценили, должна закончиться записью:
  новой строкой или reference к подтверждённому дублю;
- агрегатор, сниппет, future expiry date, badge или `Remote` не доказывают
  актуальность, global eligibility или работоспособность Apply;
- агент не отправляет заявку и не выводит lifecycle-событие `applied`.

## Выбор инструмента: Parallel Search → Browser

Для публичного discovery и первичного скрининга по умолчанию использовать
Parallel Search. Browser подключать для сложных случаев и проверки текущей
employer/ATS listing и Apply route перед полным анализом и решением `apply`.
Разрешённый source adapter/API остаётся допустимым маршрутом по своему playbook.

| Задача | Инструмент и границы |
|---|---|
| Найти exact вакансии и возможные employer/ATS URL | Parallel `web_search`: конкретная цель и 2–3 связанных запроса из query families |
| Прочитать требования для первичного скрининга | Parallel `web_fetch` exact URL: `allow_live_fetch=true`; `full_content=true`, когда нужны полное описание и все ограничения |
| Разрешить неполный текст, конфликт, неясные geo/work authorization | Browser: exact card, описание и при необходимости форма |
| Пройти авторизованную выдачу, интерактивные фильтры, пагинацию или редиректы | Browser по source playbook |
| Подтвердить текущую exact employer listing и работающий Apply route | Browser либо явно разрешённый API с доказательствами, требуемыми playbook |

`web_search` выдержки пригодны для выбора кандидатов на чтение, но не для
окончательного отсева по title, сниппету или отсутствию информации. Для
screening decision получить полное описание exact вакансии, установить её
identity и сохранить URL плюс конкретное требование в `notes`. Явный hard
blocker из этого текста позволяет закончить скрининг без Browser и без
утверждений о first-party verification. Неясность, неполное описание,
противоречие между источниками или признаки stale-текста требуют Browser;
если проверка недоступна, сохранить `reviewing` и точную причину.

`allow_live_fetch=true` разрешает свежую загрузку, а не гарантирует её.
Успешный `web_fetch`, дата публикации и `Crawled:` metadata не доказывают
актуальность; cached/indexed results не подтверждают canonical open/closed
status, `first_party_verified=yes` или `apply_verified=yes`. Непроверенные
поля оставить unknown; в `notes` различать extracted screening evidence и
фактически выполненную Browser/API verification.

Parallel Search не является новым tracker `source`: provenance сохраняет
реальную площадку и её exact URL/ID. Он не подтверждает полную выдачу,
пагинацию, отсутствие новых вакансий или выполнение source-specific stop rule.
Отсутствие результатов не означает, что вакансий нет. Для заявленной route
coverage использовать Browser/adapter по playbook, а непроверенные routes
обозначать incomplete. Каждая exact vacancy, прочитанная и оценённая через
Parallel, также получает immutable outcome или duplicate reference.

Ограничения доступа из source playbook действуют и для Parallel: нельзя
заменять запрещённый fetch/crawler вызовом `web_fetch`, обходить login/paywall
или отправлять приватные данные источника в сервис. При недоступности Parallel
явно сообщить причину и использовать Browser либо разрешённый adapter/API;
если недоступен Browser, продолжать только независимые разрешённые discovery
и screening steps, оставляя требующую Browser проверку незавершённой.

Справка по инструментам и кешированию:
[Search MCP](https://docs.parallel.ai/integrations/mcp/search-mcp),
[Extract fetch policy](https://docs.parallel.ai/extract/advanced-extract-settings).

## Универсальный lifecycle

### 1. Preflight

До первого запроса:

1. прочитать `config/profile-digest.md`, `data/index/known.tsv`,
   `data/index/keys.tsv` и `data/index/active.csv` в порядке из `AGENTS.md`;
2. прочитать playbook выбранного источника; при наличии adapter сверить
   `config/sources.toml` и его contract;
3. выбрать разрешённый маршрут по разделу выше и проверить доступность
   Parallel Search, если он используется;
4. перед browser pass явно вызвать установленный Browser plugin и открыть
   нужный source/ATS URL как интерактивную rendered page.

Полные CSV и профиль читать только когда индексов/дайджеста недостаточно для
конкретного решения; объяснить эту необходимость в отчёте об операции.

GitHub connector не удовлетворяет Browser preflight: он обслуживает repository read/write
path, а не навигацию по source/ATS. Web search, snippets и `Crawled:` metadata
могут дать lead, но не доказывают current source state. Если Browser отсутствует,
страница blocked, требует недоступную авторизацию, показывает CAPTCHA или не
загружается, остановить browser pass с точным incomplete reason. Не заявлять
route coverage и не подменять Browser verification индексированным поиском;
использовать adapter/API можно только когда это прямо разрешено source playbook.
Независимый Parallel discovery/скрининг продолжать можно в границах раздела
выбора инструмента; Browser preflight не является условием такого прохода.

`applied` и `rejected` не обрабатывать повторно. `listing_status=closed` без
отклика пропустить. Для `not_started`, `reviewing` и `apply` продолжить с
сохранённого шага, а не начинать анализ заново.

### 2. Narrow → broad discovery

Сначала пройти узкие role/geo/recency routes с высоким сигналом, затем широкие
семейства и adjacent titles. Фильтры зарплаты, seniority и exact technology не
должны преждевременно скрывать вакансии без структурированных метаданных.

Результат списка — только lead. До анализа открыть exact card и зафиксировать
её identity. После полезной или закрытой карточки проверить current company
board на соседние роли, не анализируя уже известные записи повторно.

### 3. Exact identity и dedupe до анализа

Сразу после открытия карточки получить стабильный source job ID, exact source
URL и, если уже виден, requisition ID. Затем проверять в порядке:

1. `source + source_job_id` в `data/index/keys.tsv`;
2. нормализованный exact source URL;
3. exact first-party URL или requisition ID;
4. нормализованные `company + role` в `data/index/known.tsv`, затем location
   и fuzzy candidates при необходимости уточнения.

Совпадение не даёт права молча объединять строки. Подтверждённый дубль
добавляется через `--duplicate-of` или эквивалентный immutable request. Разные
source IDs, ведущие к одной requisition, — references одной canonical job;
разные requisitions с похожим title не объединяются автоматически.

### 4. Первичный скрининг через Parallel Search

После dedupe получить полное описание exact вакансии и применить hard blockers
из профиля. Подтверждённый текстом blocker позволяет сразу записать outcome
без полного анализа и без Browser verification, сохранив URL и конкретное
требование в `notes`. Для новой такой записи использовать
`application_status=not_started` и подходящий `decision_reason`; для
существующей — `screen`. Непроверенные status/verification оставить unknown,
а уже подтверждённые значения существующей записи не сбрасывать.

При неопределённости выполнить Browser-проверку. Если она недоступна, записать
`reviewing` с точным unresolved reason, а не предполагаемый blocker. Сообщение
о закрытии в извлечённом/кешированном тексте также требует first-party
verification до canonical `closed`.

### 5. First-party verification

Для прошедшей первичный скрининг или требующей уточнения exact vacancy через
Browser либо явно разрешённый source API по его playbook:

1. определить реального работодателя, а не poster или intermediary;
2. разрешить цепочку редиректов до exact employer careers/ATS listing;
3. сопоставить title, company, location, description и requisition ID;
4. проверить exact job на текущей публичной board;
5. открыть видимую кандидату Apply route и убедиться, что она относится к той
   же вакансии и принимает заявки;
6. прочитать описание и форму на geo, residency, work authorization,
   sponsorship, timezone и office requirements;
7. записать дату проверки.

Generic homepage, search results, company profile, другой агрегатор или
доступная только после оплаты/contact reveal ссылка не являются first-party
verification. При неполных или конфликтующих доказательствах оставить
неподтверждённые verification/status unknown и записать unresolved reason в
`notes`; `next_action` вычисляет runner, его не передавать в request.

### 6. Screening и полный анализ

После first-party проверки применить hard blockers из профиля. Подтверждённая
несовместимая география, обязательная work authorization, закрытая requisition
или явно недостижимый scope позволяют остановиться до полного анализа.

Неясная география, необычный title или мягкое расхождение не превращаются в
hard blocker автоматически: оставить `reviewing` и конкретный следующий шаг.
Только прошедшая screening вакансия получает полный анализ, `match_score`,
application card и решение `apply`/вычисляемый `Skipped`.

**Ручной screening против `ingest`-предфильтра.** `scripts/ingestion.py`
(`TOO_SENIOR_SIGNALS`) — это только грубый pre-filter по ключевым словам в
title для batch-ingest (`senior`, `lead`, `staff`, `principal`, …); он не
видит требования из тела вакансии и не проверяет годы опыта. Ручной или
connector-driven screening по этому lifecycle читает полное описание и может
законно поставить `decision_reason=seniority_too_high` для роли, чей title
не содержит ни одного из этих слов (например `Middle`-роль, реально
требующая больше коммерческого опыта, чем зафиксировано в
`config/profile.md`) — противоречия с `TOO_SENIOR_SIGNALS` здесь нет, у ручного
прохода просто больше evidence. Одинаковый `role`/`level` в двух разных
записях может законно получить разный `decision_reason`, если это две разные
exact vacancy (разные source ID) с разными формулировками требований в
описании — сравнивать нужно по `notes`/evidence, а не по строке `role`.
Каждое такое решение обязано называть конкретное требование в `notes`
(например точное число лет опыта), а не полагаться на title.

### 7. Зафиксировать outcome

Каждая exact vacancy, которую открыли, получает один из исходов:

| Evidence | Canonical outcome |
|---|---|
| exact first-party job закрыта или удалена | `listing_status=closed`, `decision_reason=closed_before_application` |
| подтверждён hard blocker | структурированный `screen`/`decision_reason`, без полного анализа |
| evidence недостаточно или требуется ручная проверка | `reviewing` + конкретный `next_action` |
| screening пройден и first-party/Apply проверены | полный анализ и решение `apply` либо вычисляемый `Skipped` |
| это существующая canonical job | добавить source reference, новую строку не создавать |

Source-side archive сохраняется как evidence в notes/provenance. Он становится
canonical `closed` только после first-party проверки либо однозначного
исчезновения exact employer requisition; живой first-party listing имеет
приоритет над stale/archived карточкой агрегатора.

### 8. Immutable write path и validation

Локальная запись выполняется только через `scripts/jobs.py`. Raw batches
immutable и сначала проходят validate + ingest dry-run. GitHub connector
создаёт один immutable request и ждёт canonical result от trusted runner.
Прямое редактирование `data/jobs.csv`, `data/job_sources.csv` и generated
`docs/tracker.md` запрещено.

После canonical write выполнить strict validation, просмотреть fuzzy duplicate
report, обновить tracker view и проверить generated result — точные команды
заданы в [`AGENTS.md`](../../AGENTS.md).

### 9. Общий stop rule

Поиск по одному источнику завершён, когда:

- выполнены narrow routes, затем предусмотренный broad fallback;
- просмотрена заявленная глубина/recency window и сработал source-specific stop
  rule;
- у каждой открытой exact vacancy есть immutable outcome или duplicate
  reference;
- нет незаписанных карточек и необъяснённых fuzzy candidates;
- все canonical writes подтверждены validation/result, а не только созданным
  request или raw batch.

## Доступные source-playbooks

| Source | Специфика |
|---|---|
| [Greenhouse](greenhouse.md) | first-party ATS board, board token и job post ID |
| [Himalayas](himalayas.md) | API-backed remote discovery и fetch-only adapter |
| [Hirify](hirify.md) | aggregator routes, archive/stale signals и source-resolution boundary |
| [HiringCafe](hiringcafe.md) | normalized filters и внешний `Job Posting` |
| [Jaabz](jaabz.md) | visa/relocation/remote routes и агрегаторные labels |
| [LinkedIn](linkedin.md) | personalized signed-in search, numeric ID и Easy Apply |
| [HelloWorld.rs](helloworld-rs.md) | небольшая Serbian board и numeric URL suffix |
| [Startit Jobs](startit-jobs.md) | небольшая Serbian board с пока невалидированной identity |
| [Hired Valley](hired-valley.md) | карьерный сервис без публичной job board; только user-supplied/manual leads |
| [Relocate.me](relocate-me.md) | international relocation board, public discovery и account-gated Apply |
| [Remote OK](remote-ok.md) | крупная remote board с rendered UI, category routes и tracking Apply |
| [Geekjob](geekjob.md) | русскоязычная IT board с query/tag/geo filters и internal quick apply |
| [TalentMove](talent-move.md) | auto-aggregated Russian-language board с broad filters и signup-gated source link |
| [YC Work at a Startup](yc-work-at-a-startup.md) | native startup board и opaque job ID |
| [Hacker News — Who is Hiring?](hacker-news-who-is-hiring.md) | message identity, допускающая несколько вакансий |
| [Reactiflux Discord](reactiflux-discord.md) | Discord message tuple и email/form boundary |
| [We Work Remotely](we-work-remotely.md) | remote category routes и external Apply |
| [Welcome to the Jungle](welcome-to-the-jungle.md) | locale routes и native/external Apply |
| [Wellfound](wellfound.md) | startup filters, numeric ID и native application flow |

## Контракт нового playbook

Скопировать [`_template.md`](_template.md) и описать только:

- role/access model и routes для narrow/broad проходов;
- стабильный ID и нормализацию exact URL;
- как найти original source и отличить exact vacancy от generic page;
- source-side live/archive/stale сигналы и их ограничения;
- trustworthy/untrustworthy fields, geo/remote quirks и известные ловушки;
- source-specific stop rule.

Если фрагмент одинаков для нескольких площадок, он относится сюда, а не в
несколько playbooks. Markdown-файл сам по себе не включает adapter: машинная
политика отдельно регистрируется в `config/sources.toml`.
