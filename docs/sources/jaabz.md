# Jaabz search playbook

Checked: 2026-08-14

Current references:

- [All jobs](https://jaabz.com/jobs)
- [Remote jobs](https://jaabz.com/jobs/remote)
- [Visa sponsorship jobs](https://jaabz.com/jobs/visasponsorship)
- [Relocation jobs](https://jaabz.com/jobs/relocation)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
Jaabz-specific правила.

## Роль и доступ

Jaabz прямо описывает себя как job board, собирающий вакансии других
работодателей; это aggregator discovery source. Использовать `source=Jaabz`.
Free exact cards читаются публично, часть premium details требует sign-in; не
авторизовываться и не менять account state ради discovery без явной команды.

Источник имеет повышенный stale-risk: first-party resolution начинать сразу
после открытия exact card, до полного анализа и ranking refinement.

## Routes: narrow → broad

| Pass | Routes/filters | Назначение |
|---|---|---|
| Narrow | `/jobs` + title/skill/company, Serbia/Europe/EMEA, recent | основной поиск |
| Mobility | `/jobs/remote`, `/jobs/visasponsorship`, `/jobs/relocation` | отдельные remote/visa/relocation leads |
| Broad | `/jobs/programming/remote` и adjacent category routes без строгого experience filter | необычные titles и missing metadata |

Visa, relocation и remote routes пересекаются; exact cards дедуплицировать до
анализа. `Not Applied Jobs`, premium и другие account-aware filters не считать
полной историей tracker.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | `/jobs/<numeric-id>-<slug>` |
| stable `source_job_id` | numeric ID из path |
| `source_url` | exact card без tracking; slug не использовать отдельно |
| original route | `Apply` redirect, затем exact employer/ATS resolution |

Apply может вести в LinkedIn или другой посредник. Продолжать цепочку до
работодателя; intermediary URL не записывать как `original_url`. Repost с новым
Jaabz ID сравнивать по окончательной requisition.

## Source status и first-party boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| live exact card | Jaabz card доступна | employer requisition open |
| `Apply` button | внешний route существует | route first-party, exact или рабочий |
| posted-ago label | время на площадке | employer publication date |
| Visa/Relocation/Remote badges | source classification | sponsorship, package или global eligibility |
| premium lock | детали недоступны без account | job закрыта |

Если card удалена или Apply сломан, всё равно искать exact employer requisition;
source-side absence не заменяет canonical employer status.

## Trust и ловушки

- Numeric path ID пригоден для source dedupe; title/slug может меняться.
- `AI Summary`, experience level, job type и mobility badges — preliminary
  extracted data, не hard-blocker evidence.
- Одна карточка может одновременно иметь Visa, Relocation и Remote labels; это
  не доказывает, что все три опции относятся к кандидату из Сербии.
- Remote card может быть привязана к одной стране, а employer form — ещё уже.
- В tracked pass четыре привлекательные early-career cards (Pixel Systems,
  Alpine Business Consulting и две Bavarian Capital) оказались закрыты
  downstream; часть цепочек закончилась LinkedIn с disabled applications.
- `Save`, `Mark Applied`, sign-in и финальная Apply submission являются
  внешними writes и не используются в read-only search.

## Stop rule

Остановиться после narrow recent pass, отдельных remote/visa/relocation passes
и broad programming fallback до выбранной age/depth границы. Каждая открытая
numeric card должна получить outcome по общему lifecycle.
