# Greenhouse search playbook

Checked: 2026-08-13

Official references:

- [Greenhouse Job Board API](https://developers.greenhouse.io/job-board.html)
- [Greenhouse-hosted job board URL](https://support.greenhouse.io/hc/en-us/articles/360020776251-Job-board-URL-for-Greenhouse-hosted-job-board)
- [Careers page integration options](https://support.greenhouse.io/hc/en-us/articles/200721644-Choose-a-careers-page-integration-option)

Общий lifecycle, provenance semantics и write paths описаны в
[`README.md`](README.md). Здесь зафиксировано только Greenhouse-specific
поведение.

## Роль Greenhouse в поиске

Использовать Greenhouse как широкую поверхность first-party discovery, а не как
поиск только по заранее известным названиям вакансий. На discovery-этапе лучше
допустить шум, чем потерять подходящую роль с необычным title; hard filters
применять только после открытия живой exact job.

Greenhouse является ATS-хостом, а не отдельным значением tracker `source`.
Прямо найденные вакансии записываются как `source=Company Careers`; вакансии,
найденные через агрегатор, сохраняют этот агрегатор в provenance.

## Как распознать Greenhouse

Частые first-party URL forms:

```text
https://job-boards.greenhouse.io/<board_token>/jobs/<job_post_id>
https://job-boards.eu.greenhouse.io/<board_token>/jobs/<job_post_id>
https://boards.greenhouse.io/<board_token>/jobs/<job_post_id>
https://careers.example.com/jobs?gh_jid=<job_post_id>
```

Greenhouse поддерживает hosted, embedded и API-driven careers pages, поэтому
официальная карточка не обязана находиться на домене `greenhouse.io`. Признаки
custom integration: `gh_jid`, переход Apply на Greenhouse или запросы к Job
Board API.

`board_token` — идентификатор публичной board. Для hosted URL это сегмент после
домена. Для custom careers page получить token из Greenhouse URL/redirect или
сетевого запроса к API. Не угадывать token по названию компании: у организации
может быть несколько boards, а token может быть кастомным.

## Discovery strategy

### Query families

Не требовать React/TypeScript, junior title или `0–2 years` во всех запросах и
не использовать seniority terms как глобальные negative keywords. Запускать
несколько небольших query families и дедуплицировать результаты локально.

Основные направления:

- `frontend`, `front end`, `React`, `TypeScript`, `JavaScript`, `Next.js`;
- `web developer`, `web engineer`, `UI engineer`;
- `software engineer`, `product engineer`, `design engineer`;
- `creative developer`, `design systems`, `accessibility`;
- `CMS`, `content`, `commerce`, `marketing engineer`;
- `support engineer`, `solutions engineer`, `implementation engineer`,
  `technical consultant`, если роль может содержать существенный web scope.

Примеры внешнего discovery:

```text
site:job-boards.greenhouse.io React
site:job-boards.eu.greenhouse.io TypeScript
site:boards.greenhouse.io "web developer"
site:job-boards.greenhouse.io "product engineer" Europe
site:job-boards.eu.greenhouse.io "software engineer" EMEA
site:job-boards.greenhouse.io "design system"
site:job-boards.greenhouse.io "implementation engineer" web
```

Повторять полезные families для всех трёх host patterns. Поисковый индекс —
только discovery: сниппет и дата в выдаче не доказывают актуальность.

### Geography discovery

Использовать широкие terms: `Serbia`, `Balkans`, `Central Europe`, `Eastern
Europe`, `Europe`, `EMEA`, `CET`, `Remote`, `Worldwide`, `Global`. Вакансию без
географии тоже можно открыть для проверки.

Различать:

- discovery geography — широкий сигнал, по которому карточку открывают;
- actionable geography — ограничение, подтверждённое полным описанием и
  Apply-формой относительно `config/profile.md`.

### Adjacent roles

После релевантной или закрытой exact job получить всю текущую board и проверить
соседние frontend, web, software, product, internship и смежные technical roles.
Не анализировать повторно уже существующие tracker entries. Каждую новую
конкретную вакансию, выбранную для оценки, записать независимо от результата.

## Публичный Job Board API

GET endpoints публичны и не требуют API key:

```text
GET https://boards-api.greenhouse.io/v1/boards/<board_token>
GET https://boards-api.greenhouse.io/v1/boards/<board_token>/jobs?content=true
GET https://boards-api.greenhouse.io/v1/boards/<board_token>/jobs/<job_post_id>?questions=true&pay_transparency=true
```

Использовать их в таком порядке:

1. board endpoint подтверждает token и возвращает имя организации;
2. list endpoint возвращает полный текущий набор опубликованных job posts;
3. exact-job endpoint возвращает полное описание, `first_published`, deadline,
   metadata и, по запросу, application questions/pay ranges;
4. human-facing `absolute_url` или employer careers page используется для
   отдельной проверки Apply.

У list-jobs endpoint нет документированного текстового search parameter.
Получить текущий board dataset один раз, затем фильтровать локально по title,
content, department, office и location. `content=true` добавляет описание,
departments и offices.

`id` — идентификатор опубликованного job post и target application form.
`internal_job_id` — внутренний job identifier; `null` обозначает prospect post.
Для tracker dedupe использовать именно job post `id`, потому что один internal
job может иметь разные опубликованные posts и формы.

## Идентификаторы и URL

| Значение | Правило |
|---|---|
| `board_token` | Брать из проверенного hosted URL, redirect или API request; не угадывать. |
| `job_post_id` | Поле `id` Job Board API или значение `gh_jid`. |
| `source_job_id` при прямом discovery | `greenhouse:<board_token>:<job_post_id>`; prefix защищает общий `Company Careers` namespace от коллизий между ATS. |
| canonical first-party URL | Предпочитать `absolute_url`, ведущий на employer careers page или публичный Greenhouse post. |
| tracking parameters | `gh_src` и другие tracking-only параметры не являются частью identity; не использовать их для dedupe. |

До записи URL нормализовать штатным tracker write path. Не переписывать custom
employer URL в hosted Greenhouse URL, если custom URL является стабильной
официальной карточкой и содержит работающий Apply.

## Проверка актуальности и Apply

Проверять listing и application route независимо.

### `listing_status=open`

Нужны оба сигнала:

1. exact `job_post_id` присутствует в текущем list endpoint и exact-job GET
   успешно возвращает эту роль;
2. human-facing exact page открывается и показывает ту же вакансию.

### `apply_verified=yes`

Открыть путь кандидата и подтвердить, что Apply button/form доступен для этой
exact job. `questions=true` полезен для просмотра application fields, но один
API response не заменяет проверку отображаемой формы и переходов.

Никогда не вызывать application POST: агент не отправляет заявки. API key для
поиска и проверки GET endpoints не нужен.

### Закрытая карточка

Если exact job отсутствует в текущем board list, exact endpoint не существует
или human page сообщает о закрытии, записать закрытую вакансию согласно общему
workflow. Затем просмотреть current board; закрытый search result может быть
входом к новой adjacent role, но не доказательством её существования.

При противоречии сигналов не ставить `yes`: сохранить `unknown`, описать
расхождение в `notes` и задать конкретный `next_action`.

## Geography и hard blockers

Проверять вместе, не полагаясь только на `location.name`:

- `location`, offices и metadata из API;
- полный текст job description;
- перечисление допустимых стран/регионов и time zones;
- office/hybrid attendance requirements;
- application questions о residence, work authorization, sponsorship и student
  status.

`Remote`, `Europe` или `EMEA` без списка допустимых стран не означает, что найм
из Сербии возможен. При отсутствии доказательства использовать
`remote_policy=Unclear`, а не выводить eligibility из общего лейбла.

Настоящие ранние blockers: несовместимая обязательная страна проживания или
work authorization, обязательный офис вне допустимой географии, mandatory
student status, явно senior/staff scope, backend-heavy роль с малой frontend
частью, закрытая карточка или недоступный Apply.

Не считать автоматическим blocker необычный title, `3–4 years`, internal level,
frontend-heavy full-stack scope или неясную географию. Такие вакансии оставлять
в `reviewing`, если остальная часть выглядит достижимой.

## Поля и нормализация

| Greenhouse field | Tracker use |
|---|---|
| board `name` / exact `company_name` | проверить `company`; при расхождении использовать имя работодателя с first-party page |
| `id` | `job_post_id`, часть namespaced `source_job_id` |
| `title` | `role` как в first-party post |
| `absolute_url` | candidate `original_url`; подтверждается human-facing проверкой |
| `location.name`, `offices`, exposed `metadata` | evidence для `location` и `remote_policy`, но не автоматический eligibility verdict |
| `content` | stack, experience, scope и hard-blocker analysis |
| `first_published` | `posted_at`, преобразовать в `YYYY-MM-DD` |
| `updated_at` | freshness signal; не подменять им `posted_at` |
| `application_deadline` | дополнительный stale/deadline signal; не заменяет live/Apply verification |
| `questions`, `location_questions` | evidence из Apply-формы для eligibility checks |
| `pay_input_ranges` | salary evidence, если exposed |

Не выдумывать `posted_at`, если `first_published` отсутствует, и не вычислять
зарплату или допустимую географию из неполных labels.

Для будущего fetch adapter raw record должен соответствовать
`data/inbox/README.md`, хранить исходный объект под `payload.greenhouse` и не
записывать `original_url` до verification. Перед реализацией adapter Greenhouse
нужно отдельно добавить в `config/sources.toml`; этот playbook сам по себе его не
включает.

## Типичные ловушки

- `internal_job_id=null` означает prospect post, а не конкретную вакансию. Не
  создавать для общей формы «оставьте резюме» job row.
- Одинаковый title в нескольких локациях может означать разные job posts и Apply
  forms. Сначала сравнить `job_post_id`, полный scope и географию, затем решать,
  являются ли они дублями.
- Custom careers page может оставаться официальным first-party URL, даже если её
  домен не содержит `greenhouse.io`.
- `updated_at`, поисковая дата и deadline не являются заменой
  `first_published` или текущей проверки listing.
- Успешный exact-job GET не доказывает, что кандидат из Сербии проходит
  screening questions или что client-side Apply flow работает.

## Итоговый workflow

```text
broad web discovery
        ↓
exact Greenhouse result → preflight dedupe
        ↓
resolve and verify board_token
        ↓
fetch current board + exact job
        ↓
inspect adjacent roles
        ↓
open human page and Apply
        ↓
read geography, form questions and actual scope
        ↓
record CLOSED / SCREENED / REVIEWING / APPLY via allowed write path
```

## Checklist

- [ ] `data/jobs.csv`, `data/job_sources.csv` и profile прочитаны до поиска;
- [ ] discovery source не подменён словом Greenhouse;
- [ ] `board_token` и `job_post_id` получены, а не угаданы;
- [ ] exact job проверена в current board/API;
- [ ] human-facing page и Apply проверены отдельно;
- [ ] `first_published` не спутан с `updated_at`;
- [ ] geography и screening questions проверены относительно profile;
- [ ] adjacent roles просмотрены без повторного анализа известных jobs;
- [ ] каждая оценённая вакансия записана через разрешённый write path;
- [ ] после canonical write выполнены обязательные проверки.
