# Hacker News — Who is Hiring? search playbook

Checked: 2026-08-14

Current references:

- [Hacker News](https://news.ycombinator.com/)
- [Ask HN submissions](https://news.ycombinator.com/ask)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
`Hacker News — Who is Hiring?`-specific правила.

## Роль и доступ

Monthly Who is Hiring threads are message-based startup discovery. Один comment
может описывать несколько roles или вести к нескольким exact employer jobs.
Использовать `source=Hacker News — Who is Hiring?`; HN message сохраняется как
provenance, не как canonical vacancy identity.

## Routes: narrow → broad

| Pass | Terms | Назначение |
|---|---|---|
| Narrow | frontend, React, TypeScript, JavaScript, web | основной signal |
| Broad | product engineer, design/UI, full-stack, support/solutions | необычные startup roles |
| Geo | remote, worldwide, Europe, EMEA, CET | discovery-only geo filtering |

Искать в текущем monthly thread, затем в ещё релевантном предыдущем thread по
выбранному age window. Читать целый comment: title и geography часто находятся
в разных строках.

## Exact identity и original source

| Значение | Правило |
|---|---|
| source message | exact `item?id=<hn-item-id>` permalink |
| stable `source_job_id` | оставить пустым: item ID идентифицирует message, не vacancy |
| `source_url` | exact comment permalink; один URL допустим у нескольких canonical jobs |
| canonical identity | exact employer URL/requisition для каждой отдельной роли |

Не namespace-ить HN item ID как job ID без дополнительного role/requisition
identity. В tracker один `item?id=48747976` уже является provenance для SerpApi
и Orbit — двух разных canonical opportunities.

## Source status и first-party boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| comment доступен | source message существует | каждая упомянутая роль open |
| `REMOTE`/timezone text | author-stated discovery scope | payroll/authorization eligibility |
| employer link | candidate original route | exact requisition или current form |
| deleted/dead comment | source message unavailable | employer job closed |

Каждую роль внутри message разрешать и записывать отдельно. Generic company
homepage без exact listing оставляет verification unknown.

## Trust и ловушки

- HN особенно полезен для Product Engineer и необычных startup titles.
- Один comment может перечислять несколько locations, roles и Apply routes.
- Author/recruiter statements полезны как direct source evidence, но current
  employer board имеет приоритет для listing status.
- Email application может быть реальным route, но не автоматически first-party
  verified exact vacancy.
- Никогда не публиковать reply и не отправлять email из discovery flow.

## Stop rule

Источник обработан после narrow и broad keyword scans всего выбранного monthly
thread window. Каждый открытый employer opportunity внутри matched comments
получает отдельный canonical outcome или duplicate reference.
