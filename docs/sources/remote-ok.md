# Remote OK search playbook

Checked: 2026-08-17

Current references:

- [Remote OK](https://remoteok.com/)
- [Remote React jobs](https://remoteok.com/remote-react-jobs)
- [Remote Front End jobs](https://remoteok.com/remote-front-end-jobs)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
Remote OK-specific правила.

## Роль и доступ

Remote OK — большая public remote job board. На rendered UI доступны Search,
Location, salary/benefits controls, Sort (`Latest jobs`, `Highest paid`,
`Most viewed`, `Most applied`, `Hottest`, `Most benefits`) и category links.
Search активируется Enter и отражается в URL как `?search=<term>`. `/remote-react-jobs`
показал отдельную React-выдачу с source-side counter `500 results`.

В Browser проверка `https://remoteok.com/api` завершилась
`ERR_BLOCKED_BY_CLIENT`; registry поэтому не обещает API/fetch adapter. До новой
отдельной валидации connector использует только rendered UI.

## Routes: narrow → broad

| Pass | Route/filters | Назначение |
|---|---|---|
| Narrow | `/remote-react-jobs`, `/remote-front-end-jobs`, `/remote-javascript-jobs`, `/remote-junior-jobs` | highest-signal frontend routes |
| Narrow query | root Search: `react`, `frontend`, `front end`, `javascript`, `typescript`, `next.js`; press Enter | title/company/description/tag discovery |
| Broad | category/search for `web developer`, `ui engineer`, `creative developer`, `product engineer`, `software engineer`, `design engineer` | adjacent roles |
| Ranking | use visible Sort and salary/benefits controls only for prioritization | не терять cards без salary |

Exclude ad rows, Premium upsells and health-insurance promotions before treating
anything as a job. Query results can match body/tags, so read the exact title and
description rather than trusting a React tag alone. Use the registry age window;
do not attempt to crawl the entire 500-result category in one pass.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | `/remote-jobs/<slug>-<numeric-id>` |
| stable `source_job_id` | final numeric ID, e.g. `1136299` |
| `source_url` | exact Remote OK detail URL, not `/`, category, company or `/l/` |
| Apply route | `/l/<numeric-id>` tracking route; keep as evidence only |
| `original_url` | exact employer/ATS requisition after independent verification |

On the inspected Lemon.io card, `Apply now` and `Apply for this job` both used
`/l/1136299` with `target=_blank`. Opening the route in Browser returned to the
same Remote OK detail page and did not expose a first-party application form.
That behavior is a route limitation, not `apply_verified=yes`.

## Source status и first-party boundary

| Signal | Что он доказывает | Чего он не доказывает |
|---|---|---|
| fresh age (`7h`, `1d`, `10d`) | source-side recency | employer listing is open |
| `Worldwide`/country flags/`Probably worldwide` | board metadata | Serbia/global hiring, payroll or authorization |
| salary label | source-advertised compensation hint | currency period, guaranteed pay or current offer |
| `verified` badge | Remote OK says the source is verified | employer ATS identity or current requisition |
| `/l/<id>` | candidate redirect/tracking path exists | working first-party Apply route |
| card disappears | source removal | canonical closure without employer check |

Remote OK may combine several countries with a `Worldwide` label. Treat country
allow-list as a hard screening signal when explicit, but do not infer global
eligibility from a missing country. Company website links on cards are useful for
resolution only; a generic company homepage is not `original_url`.

## Trust и ловушки

- Search is broad and can return non-frontend jobs containing `React`; inspect
  the full description and seniority before screening.
- Sponsored/promotional rows are not vacancy records and must not create jobs.
- Source salary can be hidden behind Premium; use `Unknown`, never guess.
- Do not open the blocked API by substituting web search or an unverified endpoint.
- Do not click Apply repeatedly; one read-only route check is enough, and no form
  or external employer page was verified in the observed flow.

## Stop rule

Finish after the recent narrow category/query pass, one broad fallback, visible
pagination/scroll within the registry age window and dedupe by numeric source ID.
Every opened exact card must end as a first-party verified outcome, unresolved
route with next action, screening decision or duplicate reference.
