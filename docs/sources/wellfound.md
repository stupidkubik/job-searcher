# Wellfound search playbook

Checked: 2026-08-13

Official/current references:

- [Set up a job search](https://help.wellfound.com/article/777-setting-up-a-search)
- [Apply to a job](https://help.wellfound.com/article/769-how-do-i-apply-to-a-job)
- [Frontend Engineer jobs](https://wellfound.com/role/r/frontend-engineer)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
Wellfound-specific правила.

## Роль и доступ

Wellfound — startup discovery board и native application surface. Использовать
`source=Wellfound`; native card/form не является first-party employer listing.
Не отправлять application note, не сохранять job и не менять account state.

## Routes: narrow → broad

| Pass | Filters | Назначение |
|---|---|---|
| Narrow | roles + Serbia/Europe/remote-compatible locations + recent | основной поиск |
| Broad | adjacent roles + experience + job type | необычные startup titles |
| Ranking | compensation/equity + company stage/size | приоритизация |
| Missing-data | без salary filter | jobs без disclosed range |

Cash salary и equity — разные поля. Company activity, response rate и similar
badges влияют на ranking, но не на exact-job status.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | `/jobs/<numeric-id>-<slug>` |
| stable `source_job_id` | numeric ID из path |
| `source_url` | exact card, не role search/company/recommendations page |
| original route | external redirect → exact employer/ATS job |

Если доступен только native Apply, `original_url` остаётся пустым, verification
unknown, а form route сохраняется в evidence/notes. Repost может получить новый
Wellfound ID; stealth/similar company names требуют особенно строгого match.

## Source status и Apply boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| exact card loads | Wellfound card существует | employer role current |
| native Apply form | platform принимает application | first-party verification |
| external Apply | redirect существует | exact/live employer form |
| posting age/activity badge | source activity hint | current employer intent |
| `Remote only · Everywhere` | сильный discovery label | payroll/work authorization worldwide |

Native form можно открыть для чтения обязательных полей и остановиться до
`Send Application`. Старый card с Apply button всё ещё требует employer check.

## Trust и ловушки

- `Remote · <city>` обычно содержит location constraint.
- Visa, sponsorship, salary period/currency и allowed regions читать полностью,
  не выводить из badge.
- Несколько location variants могут иметь одинаковое описание, но разную
  eligibility.
- Native и external cards могут описывать одну requisition; numeric ID один не
  определяет canonical duplicate across sources.

## Stop rule

Остановиться после narrow role/geo passes, broad experience/type fallback и
отдельного no-salary pass до заявленной date/depth границы. Каждая открытая
numeric card получает outcome; `Send Application` не нажимается.
