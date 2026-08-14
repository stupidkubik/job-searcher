# We Work Remotely search playbook

Checked: 2026-08-13

Current references:

- [All jobs](https://weworkremotely.com/)
- [Programming jobs](https://weworkremotely.com/categories/remote-programming-jobs)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только We
Work Remotely-specific правила; сокращение `WWR` не меняет tracker value
`source=We Work Remotely`.

## Роль и доступ

WWR — remote-focused job board с собственными exact descriptions и обычно
external Apply. Card остаётся discovery provenance; `original_url` — только
verified employer/ATS listing. Generic email/form требует подтверждения
ownership на employer domain.

## Routes: narrow → broad

| Pass | Routes/filters | Назначение |
|---|---|---|
| Narrow | search + Front End/Programming + country/region + newest | основной сигнал |
| Broad | Full Stack/Software Development + skills | adjacent web roles |
| Fallback | 24-hour, one-week, two-week windows | recency coverage |

Salary/skills использовать как refinements, не обязательные ранние gates.
Featured, boosted и Top 100 меняют видимость, а не status или fit.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | `/remote-jobs/<company>-<slug>` |
| stable `source_job_id` | оставить пустым, если WWR явно не показывает стабильный ID |
| `source_url` | exact `/remote-jobs/...` URL, не home/category/search |
| original route | `Apply now` target → exact employer/ATS job |

Slug может измениться после title edit, repost — получить новый URL. Generic
application form может обслуживать несколько ролей и не годится как единственный
dedupe key.

## Source status и first-party boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| exact card рендерится | WWR record доступна | employer listing open |
| Apply-before date | source deadline hint | route всё ещё принимает заявки |
| `Apply now` | target существует | target exact/first-party/live |
| redirect карточки на homepage | сильный source removal signal | employer requisition closed |
| `Anywhere in the World` | WWR region label | worldwide payroll/eligibility |

External target может сузить geography или уже быть closed; canonical employer
status всегда проверяется отдельно.

## Trust и ловушки

- Read full exact card: React title может скрывать backend-heavy или senior
  scope.
- Country list может быть allowed region или preferred timezone — учитывать
  формулировку.
- Email/Google Form может быть реальным Apply route, но ownership нужно
  corroborate.
- Несколько regional cards могут вести к одной requisition.
- Posted date и видимая button не являются freshness proof.
- Tracked Hook & Ladder card не дала подтвердить свободный application route:
  WWR path упирался в signup/paywall, а official exact form не была найдена.

## Stop rule

Остановиться после category/search narrow pass и 24-hour → one-week → two-week
fallback до заявленной глубины. Каждая открытая exact slug card должна получить
outcome; email/form не отправлять.
