# Welcome to the Jungle search playbook

Checked: 2026-08-13

Current references:

- [Jobs](https://www.welcometothejungle.com/en/jobs)
- [Welcome to the Jungle](https://www.welcometothejungle.com/)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
Welcome to the Jungle-specific правила; `WTTJ` ниже — сокращение, tracker value
остаётся `source=Welcome to the Jungle`.

## Роль и доступ

WTTJ объединяет European discovery, employer profiles и native/external Apply.
Search/recommendations могут зависеть от профиля. Native form остаётся
platform-side application route и не заменяет employer verification.

## Routes: narrow → broad

| Pass | Filters/routes | Назначение |
|---|---|---|
| Narrow | role + location + remote level + recent | основной поиск |
| Broad | adjacent titles + contract type + wider date window | расширение покрытия |
| Locale | relevant locale/language variants | локализованные titles |
| Adjacent | employer `View all jobs` | соседние current roles |

Salary использовать как ranking field, оставляя отдельный проход для вакансий
без диапазона. Recommendations — дополнительный lead source, не полный dataset.

## Exact identity и original source

| Значение | Правило |
|---|---|
| public exact card | `/<locale>/companies/<company>/jobs/<slug>` |
| preferred `source_job_id` | opaque ID из `app.welcometothejungle.com/jobs/<id>`, если доступен |
| fallback identity | normalized public exact URL; не выдумывать ID из slug |
| original route | external Apply → exact employer/ATS listing |

Locale и `app.` variants могут быть одной WTTJ job. Similar office cards
объединять только после подтверждения общей requisition.

## Source status и Apply boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| public card/profile рендерится | WTTJ content доступен | employer job current |
| native form принимает exact role | WTTJ application route live | first-party verification |
| external Apply | redirect существует | target exact/live |
| old card → 404/410 ATS | first-party route removed | состояние возможного repost |
| `Fully remote` | work arrangement label | allowed countries |

Native form можно инспектировать без финальной отправки. `apply_verified=yes`
требует first-party evidence по общей schema, поэтому один native WTTJ flow
недостаточен.

## Trust и ловушки

- Localized page не доказывает eligibility в этом locale.
- Remote level, office location и residence/payroll constraints могут
  расходиться.
- Salary, start date и recruitment process полезны для screening, но stale card
  может сохранять их после удаления ATS job.
- `app.` и localized URLs нужно сохранять как references одной job, когда
  identity подтверждена.

## Stop rule

Остановиться после narrow, broad и relevant-locale passes плюс adjacent company
jobs до заявленной date/depth границы. Каждая открытая exact card получает
outcome, native/external form не отправляется.
