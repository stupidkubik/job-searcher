# GitHub job-tracker landscape: inspiration analysis

Дата среза: 2026-09-22
Статус: исследование и предложение, не implementation plan и не контракт.

## Зачем нужен этот документ

В документе собран первый проход по открытым GitHub-проектам для поиска работы:
трекерам откликов, локальным job-search workspace, AI-помощникам, почтовым
классификаторам и инструментам browser-assisted apply.

Цель прохода — не выбрать проект для клонирования и не зафиксировать готовый
roadmap, а найти сильные продуктовые и архитектурные идеи, сравнить их с текущим
состоянием этого репозитория и сузить темы для отдельного этапа проектирования.

Текущими источниками истины проекта остаются [`data/jobs.csv`](../data/jobs.csv),
[`data/job_sources.csv`](../data/job_sources.csv),
[`config/profile.md`](../config/profile.md) и контракты, перечисленные в
[`docs/README.md`](README.md). Этот анализ их не изменяет.

## Методика и ограничения

Поиск проводился по GitHub и публичному GitHub API по сочетаниям тем:

- job application tracker;
- job search CRM;
- local-first/self-hosted job search;
- AI job assistant;
- Gmail/inbox application tracker;
- browser extension и assisted apply;
- evidence-based resume matching.

Из широкой выдачи были исключены учебные CRUD-проекты без отличительной
продуктовой модели, чистые списки вакансий, закрытые SaaS и инструменты только
для работодателей. Для углублённого просмотра отбирались проекты хотя бы с одной
интересной идеей в data model, trust boundary, workflow, аналитике или UX.

Для каждого выбранного проекта проверялись README, структура репозитория,
лицензия, публичная активность и заявленные ограничения. Число stars используется
только как слабый сигнал распространённости, а не как оценка качества.

Ограничения этого прохода:

- это review документации и публичных метаданных, а не аудит исходного кода;
- проекты не устанавливались и не запускались;
- заявления авторов о privacy, correctness и поддержке источников не были
  независимо проверены;
- активность и популярность — снимок на дату документа;
- многие проекты появились в 2026 году и ещё не доказали устойчивость.

## Контекст текущего трекера

Текущая архитектура описана в
[`current-architecture.md`](current-architecture.md). Её сильные стороны уже
заметно превосходят большинство рассмотренных personal trackers:

- canonical CSV отделён от generated views и raw discovery;
- provenance поддерживает many-to-one связь источников с вакансией;
- discovery отделён от first-party verification;
- listing lifecycle отделён от application lifecycle;
- canonical write path валидируется и оставляет Git audit trail;
- неоднозначные дубли не объединяются автоматически;
- агент не может самостоятельно заявить фактическую отправку отклика;
- профиль кандидата служит ограниченным источником подтверждённых фактов.

Read-only снимок `jobs.py stats` на 2026-09-22:

| Метрика | Значение |
|---|---:|
| Всего canonical вакансий | 425 |
| `applied` | 34 |
| `rejected` | 8 |
| `reviewing` | 24 |
| Активные кандидаты | 59 |
| Stale active records | 59 |
| Fully verified active records | 20 |
| Verification coverage | 33.9% |
| Зафиксированные interview/offer stages | 0 |

Последняя строка не доказывает отсутствие интервью: она показывает, что
post-apply lifecycle и его evidence сейчас почти не представлены в данных.
Поэтому наиболее перспективный резерв находится не только в расширении
discovery, но и в замыкании feedback loop после отклика.

## Карта рассмотренных проектов

### 1. Зрелые универсальные workspace

#### [Gsync/jobsync](https://github.com/Gsync/jobsync)

Снимок: около 1,300 stars, 223 forks, MIT, активное обновление 2026-09-22.

Интересные идеи:

- общая модель вакансий, компаний, контактов, задач, activity/time tracking,
  резюме и interview question bank;
- контакт связывается с несколькими вакансиями через роль в каждой связи;
- компания получает собственную страницу, careers URL и watch state;
- AI показывает confirmation card до записи разобранного объявления;
- description сохраняется как исходный текст, а не только как summary;
- встроенный MCP имеет ограниченную область видимости и approval boundary;
- posting рассматривается как untrusted text, чтобы скрытые инструкции не
  могли управлять данными;
- backup/restore исключает credentials и делает snapshot перед импортом.

Что полезно здесь: не интерфейс целиком, а нормализация `company`, `contact`,
`question` и подтверждаемая запись из agent/chat surface.

Риск для нашего проекта: перенос всей продуктовой поверхности потребует БД,
auth и постоянного web UI, хотя многие идеи можно реализовать независимо.

#### [offercontext/offerPilot](https://github.com/offercontext/offerPilot)

Снимок: около 730 stars, 100 forks, AGPL-3.0, обновление 2026-09-10.

Интересные идеи:

- application board не заканчивается на `applied`;
- отдельные контуры interview preparation, mock interview и post-interview
  review;
- interview practice привязана к конкретным JD и версии резюме;
- offer comparison хранит compensation, benefits, response deadline и
  пользовательские критерии;
- salary negotiation рассматривается как следующий workflow, а не как заметка.

Что полезно здесь: предметная область после отправки заявки. В текущем трекере
она представлена значительно слабее discovery и screening.

Риск: AGPL и широкая функциональность; проект следует использовать как каталог
use cases, а не как реализацию для переноса.

#### [saeedkolivand/ai-job-hunter-app](https://github.com/saeedkolivand/ai-job-hunter-app)

Снимок: около 57 stars, Apache-2.0, активное обновление 2026-09-22.

Интересные идеи:

- scheduled search workflows с явными query/location/filter settings;
- `New` и `Applied` выводятся из сохранённой истории генераций;
- каждый отклик хранится как один document/activity record: резюме, cover
  letter, ответы, brief, source и дата;
- extension сначала пытается захватить rendered DOM, затем деградирует до URL;
- assisted autofill выключен по умолчанию;
- email-confirmation watcher opt-in, а credentials лежат в OS keychain;
- внешние вызовы и telemetry описаны явно и раздельно.

Что полезно здесь: единый application packet и явная карта data egress.

Риск: очень широкая desktop-платформа; большая часть UI и scraping поверхности
не нужна Git-first трекеру.

### 2. Trust, evidence и безопасная автоматизация

#### [ebarti/JobCtrl](https://github.com/ebarti/JobCtrl)

Снимок: около 82 stars, AGPL-3.0, активное обновление 2026-09-22.

Интересные идеи:

- match представлен per-requirement evidence ledger, а не одним числом;
- каждый resume bullet должен трассироваться до профиля;
- fabrication gates работают fail-closed;
- long-running pipeline `discover → enrich → score → tailor → review → apply`
  crash-resumable;
- предусмотрен daily spend ceiling;
- browser automation может репетировать форму, но не выполняет final submit;
- email submission допускается только после approval, привязанного к точному
  recipient и attachment candidate;
- replay, изменение URL и повторный отклик по тому же canonical opening
  блокируются;
- materially equivalent role у того же работодателя требует отдельного
  reasoned confirmation.

Что полезно здесь: наиболее проработанный референс trust boundary для будущего
assisted apply и для evidence-backed материалов.

Риск: сложность и AGPL. Копировать следует принципы — exact approval binding,
idempotency и evidence ledger — а не код.

#### [applypack/applypack](https://github.com/applypack/applypack)

Снимок: около 18 stars, MIT, активное обновление 2026-09-21.

Интересные идеи:

- отдельная проверка «вакансия реальна?» с evidence links;
- liveness check предшествует более дорогой проверке;
- модель размечает факты, но score считает детерминированный код;
- отсутствие core-stack overlap ограничивает итоговый балл;
- неизвестное превращается в вопрос, а не в предположение;
- cover letter проходит fact gate против posting, resume и подтверждённых фактов;
- пользовательские изменения coverage пересчитываются без нового LLM call;
- board напоминает о двух неделях тишины;
- source monitor сигнализирует, если целая доска перестала возвращать вакансии;
- job descriptions явно помечаются как untrusted model input.

Что полезно здесь: сочетание дешёвых deterministic checks, evidence и
неразрушающих напоминаний.

Риск: проект новый, а часть обещаний пока подтверждена главным образом очень
подробной документацией.

#### [wihlarkop/applykit](https://github.com/wihlarkop/applykit)

Снимок: около 22 stars, MIT, обновление 2026-08-06.

Ключевая идея — разделять три вопроса:

1. `evidence match`: насколько профиль подтверждает требования;
2. `confidence`: насколько полны и непротиворечивы evidence;
3. `eligibility`: work authorization, location, license и действительно
   необходимый язык.

При недостатке данных проект возвращает `needs review`, а не выдуманный score.
Пользователь может исправить priority требования или evidence link; исправление
создаёт новую immutable analysis version.

Что полезно здесь: наиболее ясная модель замены непрозрачного единственного
`match_score`.

#### [DeibyGS/applyr](https://github.com/DeibyGS/applyr)

Снимок: около 4 stars, MIT, обновление 2026-09-09.

Интересные идеи:

- CLI специально позиционируется как storage layer для coding agent;
- веса scoring сохраняются snapshot'ом на каждой вакансии, поэтому изменение
  конфигурации не переписывает смысл исторического результата;
- отдельные `Strong` / `Partial` / `Missing` по критериям;
- deterministic CV verification проверяет технологии, компании и метрики
  против master CV;
- проверка возвращает блокирующий exit code и список unsupported claims;
- можно сравнивать версии CV по ATS и keyword coverage delta.

Что полезно здесь: versioned scoring inputs и agent-friendly deterministic
gates хорошо соответствуют существующему CLI проекта.

#### [5h1vmani/matchbox](https://github.com/5h1vmani/matchbox)

Снимок: ранний проект без заметного распространения, MIT, обновление
2026-09-06.

Главная идея: генератор CV может выбирать и переформулировать только факты,
заранее подтверждённые пользователем. Даже если конкретная реализация не станет
референсом, формулировка `verified fact base → constrained generation` точно
совпадает с запретом проекта на выдумывание фактов о кандидате.

### 3. Opportunity identity, timeline и дедупликация

#### [Muatasim-Aswad/job-tracker](https://github.com/Muatasim-Aswad/job-tracker)

Снимок: около 10 stars, MIT, активное обновление 2026-09-20.

Главная формулировка проекта: `track the opportunity, not the URL`.

Интересные идеи:

- одна opportunity содержит несколько listing URLs, notes, decisions, events,
  materials и status changes;
- repost определяется как suggested match;
- genuine repost объединяется только после подтверждения;
- история уже известной возможности сохраняется при появлении нового URL;
- timeline корректируемый: событие можно датировать реальным временем, а не
  только временем ввода;
- browser extension позволяет действовать в контексте объявления;
- Gmail integration отправляет только структурированное событие, а не полный
  текст письма;
- optional private adapters не требуют менять core model.

Что полезно здесь: это почти точное продуктовое выражение уже существующей
связи `jobs.csv ← job_sources.csv`. Следующий шаг для нашего проекта может быть
не новая модель, а более явная opportunity-oriented семантика и event history.

#### [kaylaehman/jobtrail](https://github.com/kaylaehman/jobtrail)

Снимок: около 3 stars, MIT, последнее обновление 2026-06-16.

Интересные идеи:

- unified activity feed объединяет notes и status changes;
- status change автоматически создаёт событие `old → new`;
- отдельно моделируются interview rounds: тип, статус, время, длительность,
  interviewer и notes;
- deadline показан как вычисляемый countdown badge;
- source import upsert'ит по `(source, sourceJobId)`;
- повторный импорт обновляет URL, salary, location и description, но не
  перезаписывает status или notes пользователя;
- company enrichment имеет состояния auto, confirmed и rejected.

Что полезно здесь: разделение импортируемых facts и user-owned lifecycle state,
а также компактная модель interview rounds.

#### [tcpsyn/CareerPulse](https://github.com/tcpsyn/CareerPulse)

Снимок: около 20 stars, лицензия не определена, последнее обновление
2026-04-15.

Интересные идеи:

- `last_seen_at` обновляется на каждом discovery cycle;
- stale presentation отделена от текущего application state;
- activity timeline автоматически фиксирует status changes, подготовку и
  downloads;
- custom answer bank сохраняет повторно используемые ответы на формы;
- extension после заполнения предлагает сохранить новые ответы назад;
- drag-and-drop pipeline имеет доступный click fallback.

Что полезно здесь: observation freshness и learning loop для form answers.

Риски: scraper-heavy архитектура, автоматический dismiss после 30 дней и
неопределённая лицензия. Для нашего проекта отсутствие вакансии в sweep не
может автоматически означать `closed` или удаление.

### 4. Почта как feedback loop

#### [michaelxu-dev/inbox-job-tracker](https://github.com/michaelxu-dev/inbox-job-tracker)

Снимок: около 4 stars, MIT, активное обновление 2026-09-19.

Интересные идеи:

- deterministic rules разбирают очевидные письма;
- AI agent вызывается только для неоднозначных случаев;
- classifier анализирует negation, hypothetical wording, preconditions и
  third-person process descriptions;
- каждая найденная ошибка превращается в regression fixture;
- результат хранит ссылку на исходное письмо и фразу-evidence;
- поддерживается rotating audit даже уверенных классификаций;
- инструмент способен работать без AI только на правилах.

Что полезно здесь: оптимальный кандидат для отдельного исследования read-only
email ingestion. Каноническое изменение должно происходить только через
`proposed event → human confirmation → authorized write path`.

#### [Tomiwajin/CareerSync](https://github.com/Tomiwajin/CareerSync)

Снимок: около 10 stars, MIT, последнее обновление 2026-03-30.

Интересные идеи:

- read-only Gmail access;
- bulk filtering отделяет job-board spam и promotional mail;
- статус, компания и роль извлекаются из почты;
- analytics показывает response rate, conversion и activity over time;
- проект декларирует stateless processing без внешнего хранения email body.

Что полезно здесь: минимальная Gmail-powered read model и понятная privacy
граница.

Риск: README сочетает обещание stateless/zero storage с deployment через Vercel
и token cookies; threat model нуждается в отдельной проверке до заимствования
идеи.

#### [adamrangwala/Job-Application-Tracker](https://github.com/adamrangwala/Job-Application-Tracker)

Снимок: около 20 stars, MIT, последнее обновление 2025-05-03.

Интересные идеи:

- ежедневный Google Apps Script scan Gmail;
- категории receipt, assessment, interview, offer и rejection;
- activity timeline, funnel, seniority и day-of-week analytics;
- drafts для follow-up после rejection, которые человек просматривает перед
  отправкой.

Что полезно здесь: дешёвый прототип полезности email feedback loop.

Риск: keyword/rule extraction заметно проще контекстного подхода Inbox Job
Tracker и может ошибочно повышать стадию.

### 5. Networking и поиск через отношения

#### [esaba12/recruiting-tool](https://github.com/esaba12/recruiting-tool)

Снимок: ранний MIT-проект без заметного распространения, активное обновление
2026-09-22.

Интересные идеи:

- contact CRM с status, urgency и follow-up date;
- self-relation `referred by`;
- таблица, карточки и force-directed graph связей;
- interaction ledger для call, LinkedIn, meeting, email и других каналов;
- `Keep in Touch` queue с reconnect cadence;
- referral coverage gaps относительно target-company list;
- Gmail pipeline upsert'ит contact и application, а interview email может
  создать calendar event;
- discovery контактов отделено от scraping/logging-in to LinkedIn.

Что полезно здесь: job search представлен не только как pipeline объявлений,
но и как relationship graph.

#### [ouverz/ai-job-tracker](https://github.com/ouverz/ai-job-tracker)

Снимок: около 1 star, MIT, проект 2026 года.

Интересные идеи:

- контакты и outreach привязаны к конкретным jobs;
- генерируются поисковые ссылки для нахождения recruiter/hiring manager;
- weekly activity log хранит targets и actuals для applications, outreach,
  posts, interviews и GitHub activity;
- некоторые actuals выводятся автоматически из application/contact data;
- gap analysis агрегирует повторяющиеся strengths и skill gaps по вакансиям.

Что полезно здесь: различать outcome metrics и controllable activity metrics.
Число офферов не контролируется напрямую, а weekly applications, outreach и
follow-ups — контролируются.

### 6. Browser capture и assisted apply

#### [arafa-dev/ai-job-application-automation](https://github.com/arafa-dev/ai-job-application-automation)

Снимок: очень ранний MIT-прототип, без заметного распространения, опубликован
2026-05-19.

Интересные идеи:

- application packet создаётся до перехода в ATS;
- extension получает one-use packet token;
- известные поля и attachments заполняются автоматически;
- неизвестные поля подсвечиваются человеку;
- final Submit никогда не нажимается расширением;
- все AI responses, пересекающие trust boundary, schema-validated;
- description считается untrusted prompt input;
- validators запрещают неизвестные bullet IDs и крупные factual changes.

Что полезно здесь: чёткий handoff `prepared packet → browser assist → manual
completion`, совместимый с текущим запретом на самостоятельный отклик агента.

#### [BowennCAI/claude-job-slayer](https://github.com/BowennCAI/claude-job-slayer)

Снимок: около 4 stars, лицензия не определена, одноразовый ранний выпуск
2026-04-25.

Интересная идея: перед каждым Submit показывается screenshot, и workflow ждёт
подтверждения. После подтверждения результат и confirmation screenshot
добавляются в tracker.

Что полезно здесь: visual confirmation artifact.

Что не подходит: агент всё же выполняет финальный Submit после текстового `ok`.
Это шире текущего правила проекта, согласно которому заявку фактически
отправляет человек.

### 7. Аналитика и визуализация

#### [zichengalexzhao/job-app-tracker](https://github.com/zichengalexzhao/job-app-tracker)

Снимок: около 6 stars, лицензия не указана, активное обновление 2026-09-22.

Проект классифицирует Gmail, удаляет дубли и генерирует Markdown-таблицу и
Sankey chart по стадиям через GitHub Actions.

Что полезно здесь: Sankey хорошо показывает переходы и места потерь, но только
если данные представлены событиями с реальными переходами. Построение диаграммы
из одного current status создаёт ложное впечатление о полном lifecycle.

## Сводка повторяющихся сильных паттернов

### Opportunity важнее listing

Устойчивая сущность — возможность/роль, а URL является только наблюдением из
конкретного источника. Один job может иметь:

- несколько listing URLs;
- историю first-party checks;
- несколько email messages;
- несколько версий материалов;
- несколько application/interview events;
- подтверждённый canonical identity.

В текущем проекте фундамент уже существует через `jobs.csv` и
`job_sources.csv`. Необходимо решить, требуется ли только лучшее представление
этой модели или отдельный event store.

### Snapshot и events нужны одновременно

CSV-row удобен для текущего состояния и аналитики. Append-only события нужны
для ответа на вопросы:

- когда статус изменился;
- что послужило evidence;
- кто подтвердил изменение;
- сколько длился этап;
- какое письмо или действие привело к переходу;
- можно ли безопасно исправить историческую дату;
- какой state был известен агенту в момент решения.

Возможная концептуальная модель:

```text
Opportunity
├── listing observations
├── verification events
├── screening decisions
├── application events
├── communications
├── interview rounds
├── material manifests
└── follow-up commitments
```

Это не рекомендация немедленно менять schema. Сначала следует определить
минимальный набор событий и способ построения текущего snapshot.

### Почта должна предлагать события, а не переписывать истину

Предпочтительная граница:

```text
mailbox read
  → deterministic rules
  → ambiguous classifier
  → proposed event with evidence
  → review queue
  → explicit human confirmation
  → existing authorized write path
```

Такой поток сохраняет пользу автоматизации и не нарушает правило, что lifecycle
события `applied`, `interviewing`, `offer`, `rejected`, `ghosted` и `withdrawn`
не выводятся агентом самостоятельно.

### Match следует разложить на независимые оси

Предлагаемые понятия для следующего исследования:

| Ось | Вопрос |
|---|---|
| eligibility | кандидат вообще может принять эту работу? |
| requirement evidence | какие требования подтверждены профилем? |
| confidence | достаточно ли полны и надёжны исходные данные? |
| preference/priority | насколько кандидат хочет эту работу? |
| recommendation | какое действие выбрано после учёта всех осей? |

Hard blockers не должны растворяться внутри среднего score. Unknown не должен
неявно считаться ни match, ни mismatch.

### Application packet должен быть версионированным объектом

Минимальная смысловая модель packet:

```text
job_id
profile revision
CV source/version/hash
cover letter version
custom answers
generated claims and evidence links
prepared_at
reviewed_at
submission confirmation
```

Это позволяет точно отвечать, какой CV и какие утверждения были использованы,
не полагаясь только на имя файла. Существующие `applications/job-*.md` и Git
могут остаться физическим storage; сначала важен manifest и его инварианты.

### Контакты образуют отдельный граф

Контакт может быть связан с несколькими jobs и компаниями, иметь разные роли и
историю взаимодействий. Поэтому contact data не следует встраивать одной строкой
в vacancy record.

Минимальные понятия:

- contact;
- company affiliation;
- job-contact role;
- interaction;
- referral relation;
- follow-up/reconnect commitment.

До добавления схемы нужно проверить, возникла ли реальная потребность на
текущих откликах и outreach.

### Source observation и listing status — разные факты

Отдельно полезно хранить:

- `last_seen_at` в discovery source;
- время последней first-party verification;
- результат Apply-route check;
- health самого source adapter;
- исчезновение одной вакансии из выдачи;
- явное закрытие на first-party page.

Отсутствие записи в следующем scrape не доказывает закрытие. Автоматическое
удаление или закрытие противоречило бы текущему trust model.

### Analytics должна поддерживать решения

Полезные представления:

- funnel/Sankey по подтверждённым событиям;
- время между этапами;
- response rate по source, CV version и role family;
- reasons for rejection/skip с known/unknown confidence;
- weekly controllable actions против outcomes;
- follow-up debt и age distribution;
- recurring skill gaps только по хорошо подтверждённым analyses;
- source health и verification coverage.

Неполезно создавать большое число графиков без решения, которое пользователь
может принять на их основе.

## Gap matrix относительно текущей архитектуры

| Область | Текущее состояние | Найденный паттерн | Предварительная ценность |
|---|---|---|---|
| Provenance и дедуп | Сильная canonical модель | opportunity + multiple listings + confirmed merge | Высокая, но база уже есть |
| First-party verification | Сильная policy и отдельные поля | liveness evidence и source-health monitoring | Высокая |
| Application lifecycle | Current snapshot, слабая event history | append-only timeline и interview rounds | Очень высокая |
| Email feedback | Нет системного ingest | deterministic-first proposed events | Очень высокая |
| Matching | Один итоговый score + reasons | eligibility/evidence/confidence/versioning | Очень высокая |
| Materials | CV version и application markdown | packet manifest + claim evidence | Высокая |
| Contacts/outreach | Почти отсутствует | relationship CRM и reconnect queue | Средняя/высокая |
| Interview prep | Почти отсутствует | round-specific preparation/debrief | Средняя, возрастёт после первого интервью |
| Offer comparison | Отсутствует | structured offer and negotiation workspace | Низкая сейчас, высокая при первом offer |
| Browser capture | Manual/browser workflows | extension capture и assisted autofill | Средняя; дорогая поддержка |
| Analytics | Stats, reports, todo/stale | event funnel, pacing, time-to-stage | Высокая после появления events |
| Full interactive UI | Generated Markdown | local dashboard/Kanban | Низкая до подтверждённой потребности |

## Что сознательно не стоит перенимать

### Полный auto-apply

Он повышает риск:

- повторного отклика;
- отправки неподтверждённых claims;
- неверных ответов на eligibility-вопросы;
- нарушения platform terms;
- ложного `applied` без человеческой проверки;
- необратимого действия при устаревшем контексте.

Безопасная автоматизация заканчивается на подготовке, заполнении известных
полей, подсветке неизвестного и сохранении evidence. Финальное действие остаётся
за человеком.

### Один «AI ATS score»

Score без requirement ledger, eligibility и confidence скрывает hard blockers
и создаёт ложную точность. LLM может извлекать требования и предлагать evidence,
но арифметика, caps и invariants должны быть детерминированными и версионированными.

### Автоматическое закрытие, удаление или архивирование

Не найдено в sweep ≠ closed. Старо ≠ бесполезно. Любой automatic cleanup должен
менять presentation/attention state, но не стирать canonical memory и не
утверждать first-party факт.

### Scraping как центральная архитектура

HTML selectors быстро ломаются, authenticated pages создают privacy/ToS риски,
а aggregator state не подтверждает current listing. Existing source playbooks,
API adapters и first-party verification надёжнее использовать как основу.

### Немедленный переход на БД и SPA

SQLite/Postgres и React дают удобный interaction layer, но добавляют migrations,
backup, auth, hosting и второй operational surface. Сначала стоит подтвердить
потребность в features, которые невозможно выразить через CSV, append-only
artifacts и generated views.

### Автоматический lifecycle из одного письма

Фразы о будущем процессе, напоминания, conditional wording и отказ с выражением
`move forward` легко дают ложный stage. Нужны evidence, ambiguity state и review.

## Предварительные направления для следующего этапа

Это порядок дальнейшего исследования, а не утверждённый roadmap.

### A. Application event ledger

Разобрать модели JobCtrl, Muatasim Job Tracker и JobTrail. Ответить:

- какие типы событий нужны минимум;
- где хранить source evidence;
- как исправлять ошибочную дату без переписывания истории;
- как current CSV snapshot соотносится с events;
- какие события требуют `confirmed_by_user`;
- можно ли начать с read-only derived timeline из уже имеющихся данных.

### B. Read-only inbox reconciliation

Разобрать Inbox Job Tracker глубже. Спроектировать только ingestion/review
контур, без canonical writes:

- локальный доступ к Gmail/IMAP;
- минимизация и redaction;
- deterministic rules;
- ambiguous queue;
- message identity и dedup;
- evidence excerpt/link;
- proposed operation format;
- regression fixtures.

### C. Evidence-backed match model

Сравнить ApplyKit, JobCtrl, ApplyPack и applyr:

- atomic requirements;
- hard blockers;
- evidence links в `config/profile.md`;
- confidence и unknown;
- versioned weights/prompts;
- deterministic score caps;
- human overrides и audit trail.

### D. Application packet manifest

Определить минимальный manifest поверх существующих application files:

- profile revision;
- CV hash/version;
- cover letter и answers;
- claim-evidence mapping;
- prepared/reviewed/submitted boundaries;
- связь с human-confirmed `status applied`.

### E. Contacts и outreach

До изменения schema провести inventory реальных use cases:

- сколько контактов уже связано с активными jobs;
- повторяются ли recruiters между ролями;
- нужны ли referral chains;
- какие follow-ups действительно выполняются;
- можно ли начать с отдельного локального ledger без изменения jobs schema.

### F. Event-based analytics

Проектировать только после A. Возможные outputs:

- Sankey подтверждённых переходов;
- time-to-response/time-in-stage;
- weekly actions versus outcomes;
- follow-up debt;
- response rate по CV/source без смешивания current и historical populations.

## Рекомендуемый shortlist для глубокого архитектурного review

| Приоритет | Проект | Зачем читать глубже |
|---:|---|---|
| 1 | JobCtrl | evidence, approvals, repeat protection, resumable workflow |
| 2 | Muatasim Job Tracker | opportunity identity, reposts, event timeline |
| 3 | Inbox Job Tracker | deterministic-first email reconciliation |
| 4 | ApplyKit + applyr | decomposed and versioned matching |
| 5 | Recruiting OS | contacts, interaction ledger, referral graph |
| 6 | OfferPilot | interview and offer lifecycle |
| 7 | ApplyPack | liveness, fact gates, source health, nudges |

## Итоговая гипотеза

Текущий проект уже не нуждается в замене на generic Kanban tracker. Его
отличительная основа — локальная canonical memory, provenance, verification и
audited agent operations.

Наиболее перспективная эволюция — локальная evidence-based job-search operating
system, где:

- vacancy discovery остаётся отдельным, проверяемым слоем;
- opportunity объединяет все источники и историю;
- lifecycle представлен подтверждёнными событиями;
- email и browser surfaces предлагают изменения, но не присваивают факты;
- matching объясняется требованиями и evidence;
- каждый application packet воспроизводим;
- contacts и follow-ups образуют второй, relationship-oriented pipeline;
- аналитика помогает выбирать следующее действие, а не просто визуализирует
  накопленные строки.

Эта гипотеза должна быть проверена отдельными design notes по направлениям A–F
до каких-либо изменений canonical schema или появления нового UI.
