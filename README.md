# Job Search Tracker

Приватный репозиторий для системного поиска frontend-вакансий, отслеживания откликов и устранения дублей между разными job boards и агрегаторами.

Основная задача проекта: создать **единый источник истины** для всего процесса поиска работы.

Вместо повторного анализа одних и тех же вакансий каждый новый поиск должен начинаться с проверки локальной базы.

---

## Goals

Tracker должен помогать:

- не откликаться повторно на одну и ту же вакансию;
- не анализировать повторно уже просмотренные позиции;
- отличать оригинальную вакансию от её копий на агрегаторах;
- помнить причины, по которым вакансия была пропущена;
- отслеживать статусы отправленных заявок;
- хранить информацию об использованной версии CV и cover letter;
- оценивать эффективность разных job boards;
- со временем анализировать, какие типы вакансий дают больше ответов и интервью.

---

# Candidate profile

Основное направление поиска:

**Frontend Developer / Frontend Engineer**

Приоритетный уровень:

- Junior
- Strong Junior
- Graduate
- Associate
- Internship
- Early Middle как stretch application

Основной стек:

- React
- Next.js
- TypeScript
- JavaScript
- HTML / CSS / SCSS
- Tailwind CSS
- Redux Toolkit / RTK Query
- Zustand
- REST API
- Firebase
- Git / GitHub
- CI/CD
- Vitest / Jest
- React Testing Library
- Playwright

Допустимы также Fullstack-вакансии, если frontend остаётся основной частью работы и backend-требования находятся на разумном уровне.

---

# Search priorities

При поиске вакансий приоритет отдаётся следующим вариантам.

## High priority

- Junior Frontend Developer
- Graduate Frontend Developer
- Associate Frontend Engineer
- Frontend Internship
- React Developer Junior
- Next.js Developer Junior
- TypeScript Frontend Developer
- Entry-level Frontend Engineer

## Medium priority

Stretch applications:

- Frontend Developer с требованием 2+ years
- Frontend Engineer с требованием 2–3 years
- Fullstack React / Next.js + Node.js
- product/frontend roles без явно указанного seniority

Такие вакансии рассматриваются, если остальные требования хорошо совпадают с профилем.

## Low priority / skip

По умолчанию не тратить время на:

- Senior / Lead / Staff;
- вакансии с 4–5+ годами обязательного React-production опыта;
- роли, где frontend является небольшой частью backend-позиции;
- вакансии с жёсткой географией, несовместимой с проживанием в Сербии;
- позиции с обязательным local work authorization, если его нет;
- вакансии, уже закрытые на оригинальном сайте.

---

# Geographic preferences

Приоритет:

1. Global Remote
2. Europe Remote
3. EMEA Remote
4. Serbia Remote / Hybrid
5. Belgrade / Novi Sad
6. Remote roles без явно указанного ограничения страны

Отдельно проверять формулировки:

- `Remote`
- `Remote worldwide`
- `Remote Europe`
- `Remote EMEA`
- `Work from anywhere`

Слово `Remote` само по себе **не означает global remote**.

Всегда необходимо проверять ограничения в оригинальном описании вакансии.

---

# Source of truth

Агрегаторы используются только для **поиска вакансий**, но не для определения их актуальности.

Примеры агрегаторов:

- Hirify
- Jaabz
- LinkedIn search
- другие job boards и поисковые сервисы

Перед полноценным анализом вакансии необходимо найти и проверить **original source**:

- careers page компании;
- Greenhouse;
- Lever;
- Ashby;
- Workable;
- SmartRecruiters;
- Teamtailor;
- BambooHR;
- Comeet;
- LinkedIn company job posting;
- другой ATS работодателя.

Если вакансия закрыта на оригинальном источнике, она считается закрытой независимо от статуса на агрегаторе.

---

# Repository structure

Минимальная структура:

```text
job-search-tracker/
├── README.md
├── data/
│   └── jobs.csv
├── resumes/
├── cover-letters/
└── notes/
```

На первом этапе достаточно:

```text
README.md
data/jobs.csv
```

Остальные директории добавляются по мере необходимости.

---

# Main database

Основная база:

```text
data/jobs.csv
```

Одна строка = одна уникальная вакансия.

Рекомендуемая схема:

```text
id
company
role
original_url
source_url
source
location
remote_policy
level
stack
salary
posted_at
found_at
match_score
status
decision_reason
applied_at
response_at
cv_version
cover_letter
notes
```

---

# Field definitions

## id

Стабильный идентификатор вакансии.

Предпочтительная структура:

```text
normalized-company|normalized-role
```

Например:

```text
exequt|front-end-software-developer
```

или:

```text
coinspaid|frontend-developer
```

ID не должен зависеть от агрегатора.

---

## company

Название компании.

Пример:

```text
ExeQut
```

---

## role

Название вакансии в оригинальном источнике.

Пример:

```text
Front-End Software Developer
```

---

## original_url

Ссылка на оригинальную вакансию.

Например:

```text
https://company.com/careers/job/123
```

Это основной URL записи.

---

## source_url

URL страницы, через которую вакансия была найдена.

Например:

```text
https://jaabz.com/jobs/123
```

или:

```text
https://hirify.me/jobs/123
```

---

## source

Источник обнаружения.

Примеры:

```text
Jaabz
Hirify
LinkedIn
Company Careers
Referral
Manual
```

---

## location

Локация, указанная работодателем.

Примеры:

```text
Remote
Serbia
Belgrade
Europe
Cairo, Egypt
London, UK
```

---

## remote_policy

Нормализованная политика remote.

Рекомендуемые значения:

```text
Global
Europe
EMEA
Serbia
Country-specific
Hybrid
On-site
Unclear
```

---

## level

Рекомендуемые значения:

```text
Intern
Graduate
Junior
Associate
Junior/Middle
Middle
Senior
Unknown
```

---

## stack

Короткий список ключевых технологий.

Например:

```text
React; Next.js; TypeScript; REST; Jest
```

Не нужно копировать сюда весь job description.

---

## salary

Зарплата или вилка, если она известна.

Примеры:

```text
€1500-2000
$30-50/hour
Unknown
```

---

## posted_at

Дата публикации вакансии, если её удалось определить.

Формат:

```text
YYYY-MM-DD
```

---

## found_at

Дата, когда вакансия впервые появилась в нашем процессе поиска.

Формат:

```text
YYYY-MM-DD
```

---

## match_score

Субъективная оценка соответствия профилю.

Шкала:

```text
1-10
```

Ориентиры:

- `9-10` — практически идеальный match;
- `7-8` — хороший отклик;
- `5-6` — stretch;
- `<5` — обычно skip.

Match score не является автоматическим решением об отклике.

---

# Statuses

Рекомендуемый lifecycle:

```text
New
Reviewing
Apply
Applied
Interview
Rejected
Offer
Skipped
Closed
Duplicate
Withdrawn
```

## New

Вакансия найдена, но ещё не анализировалась.

## Reviewing

Идёт проверка оригинального источника и требований.

## Apply

Решено отправить заявку, но она ещё не отправлена.

## Applied

Заявка отправлена.

## Interview

Компания ответила и процесс перешёл к интервью / screening / test assignment.

## Rejected

Получен отказ.

## Offer

Получен оффер.

## Skipped

Вакансия была рассмотрена, но принято решение не откликаться.

## Closed

Вакансия закрылась до отправки заявки либо обнаружена уже закрытой.

## Duplicate

Эта карточка оказалась копией вакансии, которая уже есть в базе.

## Withdrawn

Заявка была отозвана кандидатом.

---

# Decision reasons

Для `Skipped`, `Closed` и похожих статусов важно сохранять причину.

Лучше использовать короткие стандартизированные значения.

Примеры:

```text
geo_restriction
seniority_too_high
stack_mismatch
salary_too_low
company_not_interesting
role_not_frontend
work_authorization
closed_before_application
already_applied
duplicate_listing
```

При необходимости можно добавить пояснение в `notes`.

---

# Deduplication

Это одна из главных функций tracker.

Одна и та же вакансия может одновременно существовать как:

```text
Hirify
↓
Jaabz
↓
LinkedIn
↓
Company careers page
```

URL у всех страниц будут разными.

Поэтому нельзя использовать URL как единственный способ определения дубля.

---

## Deduplication hierarchy

Перед добавлением вакансии проверять:

### 1. Original URL

Если оригинальный URL уже существует:

```text
duplicate = true
```

### 2. Company + role

Если совпадают:

```text
normalized_company
+
normalized_role
```

проверить существующую запись.

### 3. Similar role at same company

Например:

```text
Frontend Developer
Frontend Engineer
React Frontend Developer
Software Engineer, Frontend
```

могут оказаться одной вакансией с разными названиями на агрегаторах.

При совпадении компании и сильном сходстве описания необходимо вручную проверить оригинальный источник.

---

# Normalization

Для dedup рекомендуется приводить значения к простой форме.

Например:

```text
ExeQut
EXEQUT
exequt
```

→

```text
exequt
```

А:

```text
Front-End Software Developer
Frontend Software Developer
Frontend Developer
```

могут иметь разные нормализованные значения, но должны попадать в similarity check.

---

# Search workflow

Каждый новый поиск вакансий должен проходить следующим образом.

## Step 1 — Search

Найти потенциально подходящие вакансии на:

- Hirify;
- Jaabz;
- LinkedIn;
- карьерных страницах;
- других источниках.

---

## Step 2 — Dedup check

Перед подробным анализом проверить `jobs.csv`.

Если вакансия уже есть:

- `Applied` → не анализировать повторно;
- `Skipped` → проверить причину;
- `Closed` → не тратить время;
- `Rejected` → не отправлять повторный отклик без серьёзной причины;
- `New / Reviewing` → продолжить предыдущий анализ.

---

## Step 3 — Original source verification

Для новой вакансии обязательно открыть первоисточник.

Проверить:

- вакансия всё ещё существует;
- Apply работает;
- нет сообщения `No longer accepting applications`;
- локация;
- remote restrictions;
- seniority;
- work authorization;
- основные требования.

---

## Step 4 — Preliminary filtering

Если присутствует очевидный hard blocker:

```text
geo restriction
closed
seniority
work authorization
```

полный анализ вакансии не проводится.

Запись всё равно добавляется в базу.

Например:

```text
status = Skipped
decision_reason = geo_restriction
```

Это предотвращает повторное обнаружение той же вакансии.

---

## Step 5 — Match analysis

Для прошедших первичный фильтр вакансий оценить:

- stack match;
- experience match;
- product/domain match;
- geography;
- English;
- education;
- portfolio relevance;
- возможные ATS blockers.

Результат:

```text
match_score = 1-10
```

---

## Step 6 — Decision

Одно из решений:

```text
Apply
Skip
Closed
```

---

## Step 7 — Application preparation

Если:

```text
status = Apply
```

при необходимости подготовить:

- адаптированное summary;
- CV version;
- cover letter;
- ответы на application questions;
- salary expectations;
- recruiter message.

---

## Step 8 — Application

После фактической отправки:

```text
status = Applied
applied_at = YYYY-MM-DD
```

Важно менять статус только после реальной отправки.

---

# Resume tracking

Полезно сохранять версию CV, использованную для заявки.

Например:

```text
frontend-v4
markup-focused-v2
frontend-fintech-v1
```

В дальнейшем это позволит анализировать:

- какая версия CV даёт больше ответов;
- какие summary работают лучше;
- насколько помогает адаптация CV под конкретную вакансию.

---

# Cover letter tracking

Поле `cover_letter` может содержать:

```text
yes
no
```

или путь:

```text
cover-letters/exequt.md
```

Если cover letter сильно кастомизирован под компанию, его имеет смысл сохранять отдельно.

---

# Example record

```csv
id,company,role,original_url,source_url,source,location,remote_policy,level,stack,salary,posted_at,found_at,match_score,status,decision_reason,applied_at,response_at,cv_version,cover_letter,notes
exequt|front-end-software-developer,ExeQut,Front-End Software Developer,https://www.careers-page.com/exequt/job/RYR3YR7X,https://jaabz.com/jobs/253411-front-end-software-developer,Jaabz,Remote,Unclear,Junior/Middle,"Next.js; TypeScript; REST; CI/CD",Unknown,,2026-08-08,7.5,Applied,,2026-08-08,,frontend-v4,cover-letters/exequt.md,"2+ years requested; strong stack match"
```

---

# Search analytics

После накопления данных tracker можно использовать для аналитики.

Полезные показатели:

## Funnel

```text
Jobs found
→ Jobs relevant
→ Applications
→ Responses
→ Screens
→ Interviews
→ Offers
```

---

## Source performance

Например:

```text
Hirify
40 reviewed
8 applied
2 replies

Jaabz
25 reviewed
6 applied
2 replies

LinkedIn
50 reviewed
10 applied
1 reply
```

Это позволит понять, какие площадки дают наиболее качественные вакансии.

---

## Match score performance

Можно сравнивать:

```text
9-10 match → response rate
7-8 match → response rate
5-6 stretch → response rate
```

Это особенно важно для проверки гипотезы о stretch applications.

Например, может оказаться, что вакансии с требованием:

```text
2+ years
```

дают достаточно ответов и не должны автоматически отбрасываться.

---

## Rejection reasons

Можно анализировать частоту:

```text
geo restriction
seniority
stack mismatch
work authorization
salary
```

Это позволит постепенно улучшать поисковые запросы и меньше собирать заведомо неподходящих вакансий.

---

# Future automation

На первом этапе tracker остаётся обычным CSV.

Не нужно сразу строить сложную систему.

В дальнейшем можно добавить автоматизацию.

## Stage 1

```text
CSV + Git
```

Ручное обновление.

---

## Stage 2

Python / Node script для:

- добавления вакансии;
- генерации ID;
- нормализации company / role;
- поиска дублей;
- проверки обязательных полей.

Например:

```bash
npm run job:add
```

---

## Stage 3

Автоматический dedup:

```text
company similarity
+
role similarity
+
original URL
```

---

## Stage 4

GitHub Actions:

- проверка CSV;
- поиск дублей;
- генерация статистики;
- обновление dashboard.

---

## Stage 5

Optional web UI.

Например небольшой Next.js dashboard:

```text
Dashboard
Jobs
Applications
Interviews
Analytics
```

С Kanban:

```text
New
→ Reviewing
→ Apply
→ Applied
→ Interview
→ Rejected / Offer
```

Такой инструмент также потенциально может стать отдельным portfolio project.

---

# Operating principle

Главное правило проекта:

> **Ни одна найденная вакансия не должна исчезать бесследно.**

Даже если вакансия:

- закрыта;
- не подходит;
- ограничена другой страной;
- слишком senior;
- уже была просмотрена;

она всё равно должна получить запись.

Именно это превращает список заявок в память поисковой системы.

---

# Before every new job search

Перед началом нового поиска:

1. открыть актуальный `jobs.csv`;
2. считать уже известные компании и вакансии;
3. искать новые позиции;
4. проверять потенциальные совпадения;
5. не проводить повторный анализ известных вакансий без причины;
6. добавлять новые найденные вакансии независимо от финального решения.

---

# Current search strategy

Основной принцип:

```text
Aggregator
↓
Dedup check
↓
Original source
↓
Availability check
↓
Hard blockers
↓
Match analysis
↓
Application decision
↓
Tracker update
```

Не:

```text
Aggregator
↓
20 minutes analysis
↓
Original source
↓
Vacancy closed
```

Цель tracker именно в том, чтобы первый сценарий стал стандартным.

---

# Philosophy

Job search здесь рассматривается не как серия независимых откликов, а как накопление данных.

Каждый найденный job posting делает следующие поиски немного умнее.

Со временем tracker должен отвечать не только на вопрос:

> «Откликался ли я сюда?»

но и на более важные:

> «Какие вакансии действительно подходят моему профилю?»

> «На какие роли компании чаще отвечают?»

> «Какие требования можно считать soft blockers, а какие действительно закрывают путь?»

> «Какие источники приносят лучшие вакансии?»

> «Какая версия моего позиционирования работает лучше всего?»

Именно поэтому этот repository является не архивом заявок, а **данными для оптимизации всего job search процесса**.