# HiringCafe search playbook

Checked: 2026-08-13

Current references:

- [HiringCafe job search](https://hiringcafe.com/)
- [Frontend Engineer jobs](https://hiringcafe.com/jobs/frontend-engineer)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
HiringCafe-specific правила.

## Роль и доступ

HiringCafe — агрегатор с нормализованными filters и summaries. Использовать
`source=HiringCafe`; карточка и кнопка `Job Posting` остаются discovery evidence,
пока redirect не разрешён до exact employer/ATS listing.

## Routes: narrow → broad

| Pass | Filters | Назначение |
|---|---|---|
| Narrow | recent + Job Titles & Keywords + location | релевантные exact cards |
| Broad | Departments, Experience, Commitment, Apply Process | adjacent roles и формы занятости |
| Ranking | salary, benefits, company/industry/stage/size | приоритизация без раннего отсева |

`Exclude Jobs` применять только после broad pass. SEO landing/search pages не
сохранять как reference одной вакансии. Проход без salary filter обязателен,
чтобы не потерять jobs без опубликованного диапазона.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | отдельная HiringCafe job detail surface |
| stable `source_job_id` | только явно exposed opaque ID; не выводить из query/slug |
| `source_url` | exact card после нормализации `hiring.cafe` → current domain redirect |
| original route | `Job Posting` redirect до exact employer/ATS requisition |

Generic careers/search page или другой агрегатор означает незавершённое
resolution. Несколько location cards, ведущих к одной requisition, становятся
references; разные requisitions не объединять по одинаковому title.

## Source status и first-party boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| live detailed card | HiringCafe record доступна | employer job open |
| recent date | aggregator freshness hint | first-party publication/currentness |
| `Job Posting` button | внешний route есть | route exact, first-party или live |
| Apply Process label | классификация площадки | длина или работоспособность формы |

Окончательный статус всегда берётся с employer listing/form. Старый card может
пережить удалённую requisition; legacy-domain redirect может изменить URL shape.

## Trust и ловушки

- Title/company помогают identity, но normalized experience, skills, salary,
  work environment и AI summary проверяются по original text.
- `Remote` не означает global; country, payroll, authorization и timezone могут
  расходиться с агрегаторным label.
- Exact card может индексироваться по нескольким URL.
- Filters иногда скрывают missing metadata, поэтому narrow проход дополняется
  unfiltered broad fallback.

## Stop rule

Остановиться после recent narrow pass, broad fallback и просмотра заявленной
пагинации/age window; каждый открытый exact card должен иметь разрешённый
employer route, unresolved next action или duplicate reference.
