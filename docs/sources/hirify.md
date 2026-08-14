# Hirify search playbook

Checked: 2026-08-13

Current references:

- [Remote jobs](https://hirify.me/en/remote-jobs)
- [Software jobs](https://hirify.me/en/software-remote-jobs)
- [HTML jobs](https://hirify.me/en/html-remote-jobs)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Детерминированная
route matrix находится в
[`hirify-discovery-rules.md`](hirify-discovery-rules.md), наблюдаемая техническая
поверхность и automation boundary — в
[`hirify-technical-discovery.md`](hirify-technical-discovery.md).

## Роль и доступ

Hirify — discovery aggregator. Использовать `source=Hirify`; exact Hirify card
сохранять как provenance, а `original_url` — только после разрешения до
работодателя/ATS. Не обходить gated contacts, paid features или ограничения на
автоматизированный доступ.

## Routes: narrow → broad

| Pass | Routes/filters | Назначение |
|---|---|---|
| Narrow | frontend/React/TypeScript title routes; Global/Europe/Serbia-compatible; newest | высокий сигнал |
| Broad | software, web, UI, product, HTML и adjacent categories | необычные titles |
| Fallback | более широкое age window по правилам route matrix | покрытие stale-looking leads |

Сначала применять sort/role/geo, затем skills и experience. Не использовать
backend terms как глобальные exclusions: вес backend определяется exact
description. Full route order, pagination и повторяемый stop threshold не
дублируются здесь.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | `/jobs/<numeric-id>-<slug>` |
| stable `source_job_id` | numeric ID; slug может меняться |
| `source_url` | exact Hirify card без tracking |
| original route | visible source/contact link → exact employer/ATS requisition |

Telegram post, recruiter contact, generic homepage, category page и другой
aggregator не являются original source. Hidden-company card оставлять unresolved
до уверенного employer match.

## Source status и first-party boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| `This vacancy is archived` | Hirify card archived | employer requisition closed |
| live exact card | source card доступна | employer listing open |
| update/posted label | source freshness hint | first-party freshness |
| gated source/contact | маршрут существует | доступный Apply или first-party verification |

Source archive и canonical employer status записывать раздельно. Если exact
employer listing не разрешён, сохранить discovery outcome с verification
unknown и точным `next_action`.

## Trust и ловушки

- Numeric ID достаточно стабилен для source dedupe; AI score, tags, normalized
  seniority/location — только ranking aids.
- `Remote (Global)` не доказывает allowed countries, payroll или work
  authorization.
- Repost может получить новый Hirify ID и вести к старой requisition.
- Source label может вести на другой агрегатор; цепочку нужно продолжить.
- Networked crawler не реализовывать без документированного разрешения;
  разрешённый offline/manual parser boundary описан в technical note.

## Stop rule

Остановиться по route/age/depth правилам из
[`hirify-discovery-rules.md`](hirify-discovery-rules.md). Общий outcome rule
применить к каждой открытой numeric card, включая archived и unresolved.
