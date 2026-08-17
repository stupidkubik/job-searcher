# Geekjob search playbook

Checked: 2026-08-17

Current references:

- [Geekjob vacancies](https://geekjob.ru/vacancies)
- [Geekjob](https://geekjob.ru/)
- [Geekjob Telegram channel](https://t.me/geekjobs)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
Geekjob-specific правила.

## Роль и доступ

Geekjob — русскоязычная IT/Digital board с публичным browse/search. На странице
`/vacancies` видны query field, `Только с ЗП`, `Релокация`, `Удаленная работа`,
`Частичная занятость`, `Работа в офисе`, `Прямой работодатель`, tags (включая
React, JavaScript, Frontend) и сортировка по релевантности, дате и деньгам.

Exact card доступна без login. На проверенной карточке `Middle Frontend Engineer
(React + MobX)` ссылка `Откликнуться` ведёт к internal response box, а сам quick
apply предлагает регистрацию/login и OAuth. Connector не регистрируется,
не вводит personal data и не отправляет response.

## Routes: narrow → broad

| Pass | Route/filters | Назначение |
|---|---|---|
| Narrow | `/vacancies?qs=React`, `/vacancies?qs=Frontend`, `/vacancies?qs=JavaScript`, `/vacancies?qs=TypeScript` | direct frontend query |
| Narrow filters | `Удаленная работа` + `Прямой работодатель`; `Релокация` как отдельный pass | приоритет remote/direct leads без потери relocation roles |
| Broad | `UI`, `Creative Developer`, `Product Engineer`, `Software Engineer`, `Game Developer` | adjacent titles and playable/creative roles |
| Ranking | `По дате`, затем `По деньгам`; salary filter only as prioritization | не скрывать jobs without salary |
| Pagination | follow `/vacancies/2` … visible next page group until no unseen cards | source shows page groups; do not stop at first five links |

Use Russian and English query variants. The board contains Russia/CIS, Europe and
relocation labels in the same feed, so query relevance is not geo eligibility.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | `/vacancy/<24-character-token>` |
| stable `source_job_id` | exposed 24-character token, e.g. `6a606f93dad157500a004e67` |
| `source_url` | exact vacancy URL, not `/vacancies`, company or tag page |
| original route | company/ATS link from card or independent first-party resolution |

The token is the observed stable card identity. Do not derive it from title,
position or query URL. Company profile and external company domain on the card can
be generic. Different agency/company posts with similar titles are different
cards until a first-party requisition match proves a duplicate.

## Source status и first-party boundary

| Signal | Что он доказывает | Чего он не доказывает |
|---|---|---|
| card visible + publication date | source record exists and its board date | employer requisition remains open |
| `remote`/`relocate` | board work-mode hint | Serbia/global eligibility or permit |
| salary in RUB/EUR/USD | source-advertised range | net/gross period or cross-border contract |
| `Прямой работодатель` | board classification | employer ATS identity or active Apply |
| `агентство` label | agency poster clue | vacancy is closed or invalid |
| internal `Откликнуться` | Geekjob response route | first-party employer form |

The card's full description is useful for role, stack, seniority, language and
work mode. Canonical status still comes from employer/ATS. Do not set
`first_party_verified=yes` from a direct-employer badge or company email shown in
the board card.

## Trust и ловушки

- Many roles are Russia-specific even when tagged remote; read country, contract,
  authorization and timezone text.
- Agency postings and reposts need strict company/role/first-party dedupe.
- Board counts and recommendations are discovery aids, not complete coverage
  proofs.
- Telegram `@geekjobs` is an alert channel, not an additional exact card source;
  preserve a concrete message URL only when the lead came from a message.
- Avoid OAuth/login and do not let connector create an anonymous CV or profile.

## Stop rule

Complete all narrow query + remote/direct-employer passes, then broad adjacent
queries and all visible pagination in the registry age window. Every exact card
opened gets a canonical first-party outcome, an unresolved next action, a
screening decision or a duplicate reference.
