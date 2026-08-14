# YC Work at a Startup search playbook

Checked: 2026-08-14

Current references:

- [YC startup jobs](https://www.ycombinator.com/jobs/)
- [All roles](https://www.ycombinator.com/jobs/role/all)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только YC
Work at a Startup-specific правила.

## Роль и доступ

YC Work at a Startup — native startup discovery/application board. Использовать
`source=YC Work at a Startup`. YC card даёт сильный startup context, но не
заменяет public employer careers/ATS verification.

## Routes: narrow → broad

| Pass | Routes/filters | Назначение |
|---|---|---|
| Narrow | engineering/frontend + remote/Europe + recent | основной startup signal |
| Broad | product, design/UI, full-stack и any-experience | adjacent/new-grad roles |
| Company | `/companies/<company>/jobs` | соседние роли выбранного стартапа |

Компенсацию, experience и visa filters использовать для ranking с отдельным
fallback для missing/ambiguous fields.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | `/companies/<company>/jobs/<opaque-id>-<slug>` |
| stable `source_job_id` | opaque segment перед slug, например `W8Qj6kZ` |
| `source_url` | exact YC card без tracking |
| original route | company website/Apply → exact public employer requisition |

Company slug и title slug не являются job identity. Repost с другим opaque ID
сравнивать по employer requisition и полному scope.

## Source status и first-party boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| live YC exact card | YC listing доступна | employer-side currentness |
| YC Apply/native profile flow | application route на YC | first-party verification |
| Remote/visa/experience fields | YC discovery metadata | Serbia eligibility |
| company jobs page | current YC-listed roles | полноту employer hiring board |

Tracked aSim card показывал Remote, new-grads-ok и visa sponsorship, но не давал
Serbia eligibility. Cogram указывал CET ±5h, однако public first-party listing
также оставалась неподтверждённой.

## Trust и ловушки

- Title, compensation, remote scope, experience, visa и startup context можно
  использовать для ranking и notes.
- Cash и equity сохранять раздельно, если YC показывает оба компонента.
- `Remote` может означать конкретный country set или timezone.
- Native Apply не выставляет `first_party_verified=yes`.
- Company status на YC не доказывает status одной exact requisition.

## Stop rule

Остановиться после narrow engineering pass, broad product/design/full-stack
fallback и проверки adjacent jobs у открытых компаний до заявленной глубины.
Каждая открытая opaque-ID card получает outcome.
