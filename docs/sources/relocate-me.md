# Relocate.me search playbook

Checked: 2026-08-17

Current references:

- [Relocate.me international jobs](https://relocate.me/international-jobs)
- [Relocate.me Front End category](https://relocate.me/international-jobs/frontend)
- [Relocate.me Remote category](https://relocate.me/international-jobs/remote)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
Relocate.me-specific правила.

## Роль и доступ

Relocate.me — public international tech job board, ориентированный на
релокацию. Browse/search карточек доступен без входа. На проверенной карточке
HENNGE кнопка `Apply` открыла dialog `Jobseeker Login` с login/register и
Google/LinkedIn OAuth; connector не регистрируется и не применяет от имени
кандидата.

## Routes: narrow → broad

| Pass | Route/filters | Назначение |
|---|---|---|
| Narrow | `/international-jobs?query=frontend`, `?query=react`, `?query=typescript`, `?query=javascript`, category `frontend`, `reactjs`, `web-developer` | direct frontend signal |
| Narrow geo | UI filters `Europe`, `Remote`; country field only when a country is explicitly relevant | отсечь очевидно несовместимые локации, не считать filter proof |
| Broad | `?query=software engineer`, `?query=product engineer`, `?query=ui engineer`, `?query=design engineer`, `?query=full stack` | adjacent frontend-leaning roles |
| Pagination | follow visible `Next`/page links until no unseen exact IDs in the bounded window | не полагаться только на counter; query results могут менять pagination |

На `/international-jobs` источник показывает текущий counter и обычную
pagination. После каждого query сохранять query URL как discovery reference, но
в tracker использовать exact card URL. Фильтры `Remote` и `Europe` являются
сигналами выдачи, а не разрешением работать из Сербии.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | `/country/city/company/slug-<numeric-id>` |
| stable `source_job_id` | последний numeric suffix, например `10264` |
| `source_url` | normalized exact Relocate.me card URL; не search/category/company page |
| `original_url` | exact employer careers/ATS requisition после проверки |

Карточка содержит title, company, location, description, salary/relocation
details и related jobs. Ссылка на company profile, article, SpeakerDeck или
country guide не является exact employer vacancy. Если один employer публикует
location variants, сравнить numeric source ID и requisition evidence; не
объединять только по title.

## Source status и first-party boundary

| Signal | Что он доказывает | Чего он не доказывает |
|---|---|---|
| visible exact card | карточка существует на board | requisition всё ещё open у работодателя |
| `Advanced relocation package` | source заявляет flight/language/visa support | фактический visa sponsorship для кандидата |
| `Remote`/country/location | discovery geography | Serbia eligibility, payroll или work authorization |
| Apply dialog | Relocate account-gated candidate route | доступность employer/ATS form и возможность подать заявку |
| card absent/old | source-side removal/staleness | canonical closure без first-party check |

Публичного employer Apply URL на наблюдаемой карточке не было видно до login.
Не ставить `original_url` по догадке и не считать Relocate.me first-party.
Canonical `listing_status`, `first_party_verified` и `apply_verified` определяет
employer/ATS surface.

## Trust и ловушки

- Source ориентирован на международную мобильность, но большая часть jobs
  onsite/country-specific; «international» не равно global remote.
- Прочитать full description: visa, relocation, city, language, office days,
  country of employment и exact years of experience важнее badge.
- Salary и relocation package полезны для приоритизации; currency/period и
  eligibility всё равно перепроверять.
- Premium newsletter (~100 jobs weekly) — отдельный платный product, не часть
  public discovery pass; не подписываться и не извлекать его как источник.
- Не отправлять OAuth/login и не создавать Jobseeker account во время поиска.

## Stop rule

Завершить источник после полного narrow pass по frontend/React/TypeScript/remote
routes, bounded broad pass и visible pagination в age window из registry. Каждая
открытая exact card должна иметь first-party outcome, конкретный unresolved
next action или duplicate reference.
