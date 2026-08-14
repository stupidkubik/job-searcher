# LinkedIn search playbook

Checked: 2026-08-13

Official references:

- [Filter and sort job search results](https://www.linkedin.com/help/linkedin/answer/a507441)
- [Apply for jobs on LinkedIn](https://www.linkedin.com/help/linkedin/answer/a512388)
- [Easy Apply limits](https://www.linkedin.com/help/linkedin/answer/a512348)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
LinkedIn-specific правила.

## Роль и доступ

LinkedIn — personalized signed-in discovery surface. Использовать только
видимый UI и `source=LinkedIn`; не вызывать private endpoints, не обходить
access controls и не автоматизировать отправку. Save, Follow, Message и Submit
— external writes.

## Routes: narrow → broad

| Pass | Filters | Назначение |
|---|---|---|
| Narrow | role family + Serbia/Europe/compatible remote + recent | свежие exact cards |
| Broad | adjacent titles + one-week/month fallback | расширение покрытия |
| Separate | Easy Apply, company/network, applicant-count signals | дополнительный route/ranking, не universal filter |

Результаты персонализированы и ограничены, поэтому одна выдача не считается
исчерпывающей. Варьировать keywords и сохранять exact identity до перехода в
recommendations/company pages.

Email alerts — дополнительный режим LinkedIn discovery, а не отдельный tracker
source. Lead из alert нормализуется к тому же numeric exact URL.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | `/jobs/view/<numeric-id>/` |
| stable `source_job_id` | numeric LinkedIn job ID |
| `source_url` | `https://www.linkedin.com/jobs/view/<id>/` без tracking |
| original route | external `Apply` → exact employer/ATS requisition |

Poster, staffing intermediary и company profile не обязательно являются
работодателем/original source. Несколько LinkedIn IDs одной employer requisition
— source references; location-specific requisitions не объединять по title.

## Source status и Apply boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| live LinkedIn card | card доступна | employer job open |
| `Apply` | внешний route | exact/live first-party listing |
| `Easy Apply` | native LinkedIn form | first-party verification |
| promoted/reposted label | distribution event | employer freshness |
| applicant count | LinkedIn ranking signal | fit или шанс отклика |

Native Easy Apply можно открыть только для чтения полей и остановиться до
Submit. Если exact employer listing не найдена, verification остаётся unknown;
LinkedIn card не становится `original_url`.

## Trust и ловушки

- `Remote` обычно ограничен рынком карточки, а не означает worldwide.
- Recruiter/poster может скрывать actual hiring employer.
- Старый ID может исчезнуть при новом repost той же requisition.
- Текущая LinkedIn card может вести на закрытую ATS form; first-party wins.
- Experience badges, applicant counts и recommendations пригодны для ranking,
  не для hard-blocker facts.

## Stop rule

Остановиться после recent narrow searches, one-week/month broad fallback и
заявленной глубины результатов для каждой query/geo family. Каждая открытая
numeric card получает immutable outcome; Save/Easy Apply submission не
выполняются.
