# TalentMove search playbook

Checked: 2026-08-17

Current references:

- [TalentMove](https://talent-move.ru/)
- [TalentMove development category](https://talent-move.ru/job-category/dev/)
- [TalentMove React search](https://talent-move.ru/?s=React)
- [TalentMove fully remote jobs](https://talent-move.ru/format/fully-remote/)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
TalentMove-specific правила.

## Роль и доступ

TalentMove — публичный русскоязычный агрегатор с большой автоматически собранной
базой. На проверке homepage показывал 125k+ вакансий и дневной прирост; раздел
`dev` — date buttons (`Сегодня`, `7 дней`, `30 дней`), format/level/employment
facets, skills combobox и pagination. Search `/?s=React` показал 1014 results и
видимые role/location/format/tags.

Exact card доступна без login, но сайт прямо предупреждает: объявления собираются
автоматически и не проверяются/не подтверждаются. На проверенной карточке
`Перейти к вакансии` имела `href="#"` и `data-src="#popup-signup"`, то есть
открывала signup popup вместо видимого source/apply URL. Connector не
регистрируется и не использует Premium/закрытые features.

## Routes: narrow → broad

| Pass | Route/filters | Назначение |
|---|---|---|
| Narrow | `/job-category/dev/` + `Сегодня`/`7 дней`, search `React`, `Frontend`, `JavaScript`, `TypeScript`, `Next.js` | primary frontend discovery |
| Narrow geo | `/format/fully-remote/`, `/location/evropa/`, `/location/sng/`; inspect Serbia/Georgia/US/EU text manually | reduce obvious geo mismatch |
| Narrow level | `/seniority/junior/`, `/seniority/middle/` | target profile alignment |
| Broad | `Web Developer`, `UI Engineer`, `Creative Developer`, `Product Engineer`, `Software Engineer` | adjacent frontend roles |
| Pagination | follow `Загрузить ещё` and visible page buttons only inside the age window | avoid crawling the full 125k archive |

The category page also exposes skill selectors and faceted counts. Use them for
ranking/coverage, not as proof that every card in the facet is current or
frontend-primary.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | `/jobs/<slug>-<numeric-id>/` |
| stable `source_job_id` | final numeric suffix, e.g. `254948` |
| `source_url` | normalized exact TalentMove card URL; preserve the card URL even if source later changes |
| original route | only employer/ATS URL independently resolved after registration-free/public evidence permits it |

The slug contains title/company/date hints but is not a safe identity by itself;
use the exposed numeric ID. `company`, salary shorthand, source date, synthetic
`Оценка вакансии` and tags are all discovery fields. The Telegram preview/curated
channel is not an exact card unless a concrete message URL is available.

## Source status и first-party boundary

| Signal | Что он доказывает | Чего он не доказывает |
|---|---|---|
| card visible | TalentMove has an aggregated record | employer listing is current |
| `Оценка вакансии` | TalentMove's source-side score | candidate fit or employer decision |
| salary `K`/remote/location | extracted display metadata | currency/period, Serbia eligibility, payroll or authorization |
| publication age / today facet | source freshness hint | exact employer posting date or open status |
| `Перейти к вакансии` signup popup | TalentMove gates source route | employer/ATS Apply route |
| disappearance | aggregator removal | canonical closure without first-party check |

Canonical status always comes from employer/ATS. If the source route is gated and
no employer page can be resolved from public evidence, keep `original_url` empty,
verification unknown and set a precise `next_action`; do not claim that the
aggregator card itself is first-party.

## Trust и ловушки

- The feed is dominated by Russia/CIS roles and many remote labels are
  country-specific; inspect full role text before applying the profile's geo
  policy.
- Broad query results include mobile, backend, QA and full-stack roles; read the
  actual scope and stack before scoring.
- TalentMove's score and tags may be generated/normalized; do not copy them as
  candidate facts or canonical match score without analysis.
- Premium, AI resume and CareerFix links are products, not job-source routes.
- Never submit personal data through the signup popup. The registry intentionally
  remains discovery-only until a first-party route is independently available.

## Stop rule

Complete `dev` category + React/Frontend/JavaScript/TypeScript/Next.js narrow
passes, remote/Europe/Serbia-compatible routes and Junior/Middle facets within the
7-day window, then one 30-day broad fallback. Stop after visible pagination/load
more is exhausted for those bounded routes. Every opened exact card must receive
an immutable first-party outcome, unresolved next action, screening decision or
duplicate reference.
