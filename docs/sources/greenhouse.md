# Greenhouse search playbook

Checked: 2026-08-13

Official references:

- [Job Board API](https://developers.greenhouse.io/job-board.html)
- [Hosted job board URLs](https://support.greenhouse.io/hc/en-us/articles/360020776251-Job-board-URL-for-Greenhouse-hosted-job-board)
- [Careers page integrations](https://support.greenhouse.io/hc/en-us/articles/200721644-Choose-a-careers-page-integration-option)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
Greenhouse-specific правила.

## Роль и доступ

Greenhouse — first-party ATS surface, но не tracker source. При прямом discovery
использовать `source=Company Careers`; если lead пришёл из агрегатора, сохранить
агрегатор в provenance. Публичные Job Board GET endpoints не требуют API key;
application POST не вызывать.

Hosted, embedded и API-driven boards могут находиться на `greenhouse.io` или на
домене работодателя. `board_token` получать из проверенного URL, redirect или
network request, не угадывать по названию компании.

## Routes: narrow → broad

| Pass | Route | Назначение |
|---|---|---|
| Narrow | external search по `job-boards.greenhouse.io`, `job-boards.eu.greenhouse.io`, `boards.greenhouse.io` | найти релевантные boards и exact posts |
| Board | `GET /v1/boards/<board_token>/jobs?content=true` | получить всю текущую board и фильтровать локально |
| Exact | `GET /v1/boards/<board_token>/jobs/<job_post_id>?questions=true&pay_transparency=true` | описание, form fields, dates и metadata |
| Adjacent | current board без title-фильтра | соседние web/product/software roles |

List endpoint не имеет документированного полнотекстового search parameter.
Один раз получить board dataset, затем применить narrow → broad query families
локально. `board` endpoint `/v1/boards/<board_token>` подтверждает организацию.

## Exact identity и URL

Частые exact forms:

```text
https://job-boards.greenhouse.io/<board_token>/jobs/<job_post_id>
https://job-boards.eu.greenhouse.io/<board_token>/jobs/<job_post_id>
https://boards.greenhouse.io/<board_token>/jobs/<job_post_id>
https://careers.example.com/jobs?gh_jid=<job_post_id>
```

| Значение | Правило |
|---|---|
| stable job ID | публичный job post `id`/`gh_jid`, не `internal_job_id` |
| `source_job_id` | `greenhouse:<board_token>:<job_post_id>` внутри общего `Company Careers` namespace |
| `source_url` / `original_url` | verified `absolute_url` или стабильная custom employer card |
| tracking | удалить `gh_src` и другие tracking-only параметры |

`internal_job_id=null` означает prospect post; общую форму «оставьте резюме» не
записывать как exact vacancy. Разные post IDs могут быть отдельными location
forms одной внутренней роли и не объединяются без подтверждения общей
requisition.

## Source status и Apply

| Signal | Доказывает | Не доказывает |
|---|---|---|
| post есть в current list и exact GET | post опубликован в API | client-side Apply работает и кандидат eligible |
| human exact page с тем же ID | карточка доступна кандидату | форма принимает заявку |
| visible exact Apply form | application route доступна | geo/work authorization совместимы |
| post отсутствует из current list / exact endpoint removed | сильный close signal | состояние другой location variant |
| `updated_at` или future deadline | freshness/deadline hint | `posted_at` или open status |

Для `open` нужны current exact post и совпадающая human page; Apply проверяется
отдельно. При конфликте API и UI оставить verification unknown и записать
конкретный следующий шаг.

## Trust и ловушки

- `first_published` можно нормализовать в `posted_at`; `updated_at` им не
  является.
- `location`, offices и metadata помогают discovery, но `Remote`/`Europe`/EMEA
  не доказывают eligibility из Сербии.
- `questions` и `location_questions` часто раскрывают residence, sponsorship,
  student status и work authorization blockers.
- Custom employer URL остаётся first-party, даже если не содержит
  `greenhouse.io`.
- Одинаковый title на нескольких boards или locations не равен одному post.

## Stop rule

Board обработана, когда выгружен текущий список до конца, локально пройдены
narrow и broad families, проверены adjacent roles, а каждый открытый post ID
получил outcome по общему lifecycle.
