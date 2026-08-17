# Hired Valley search playbook

Checked: 2026-08-17

Current references:

- [Hired Valley](https://hiredvalley.com/)
- [Hired Valley Telegram community](https://t.me/hiredvalley)
- [Hired Valley manager](https://t.me/hiredvalleysales)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Hired Valley не
является обычной job board, поэтому этот playbook ограничивает connector вместо
того, чтобы имитировать публичную выдачу.

## Роль и доступ

Hired Valley — карьерная платформа и менторская экосистема, а не работодатель и
не рекрутинговое агентство. На публичной странице нет каталога вакансий,
поисковой формы, exact vacancy cards или открытого Apply route. Сайт продаёт
карьерные продукты: среди заявленных результатов есть индивидуальные подборки
из 20–25 вакансий и расширенные подборки из 40–50 позиций, а AI Camp обещает
практики автоматизации поиска.

Использовать `source=Hired Valley` только для явно полученного lead-а из
сообщества, пользовательской подборки или переписки, если lead можно связать с
конкретной компанией и ролью. Homepage сам по себе не является vacancy
reference. Public Telegram links и manager contact — каналы обнаружения, но
connector не должен писать в Telegram, покупать продукт, создавать аккаунт или
читать приватный контент без переданного пользователем URL/экспорта.

## Routes: narrow → broad

| Pass | Route | Назначение |
|---|---|---|
| Public preflight | `https://hiredvalley.com/` | подтвердить, что это карьерный сервис, а не job board |
| User-supplied lead | exact Telegram message, exported list or supplied URL | обработать только конкретный lead |
| First-party | employer careers/ATS URL | проверить identity, актуальность и Apply |

Не делать циклический crawl homepage, Telegram previews или платных products:
публичного search corpus там не наблюдается. Если lead содержит только описание
без exact URL, сохранить его как `reviewing` с конкретным `next_action`, а не
выдумывать source job ID или first-party URL.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact card | отсутствует на публичном сайте; exact lead — только переданный message/list item |
| stable `source_job_id` | использовать только реальный ID Telegram/message/export, если он виден; не генерировать hash из текста |
| `source_url` | ссылка на конкретное сообщение или user-supplied artifact, не homepage |
| `original_url` | exact employer/ATS listing после независимой проверки |

Один список из Hired Valley может содержать вакансии разных работодателей и
должен раскладываться на отдельные canonical jobs. Совпадение по названию роли
без employer requisition — не duplicate proof.

## Source status и first-party boundary

| Signal | Что он доказывает | Чего он не доказывает |
|---|---|---|
| текст на homepage о подборках | сервис заявляет подбор вакансий | существование конкретной current vacancy |
| Telegram community/manager link | канал получения lead-а | employer identity, open status или Apply |
| продукт/менторская страница | карьерную услугу | найм от имени работодателя |
| user-supplied vacancy item | наличие discovery evidence | first-party ownership, geo или work authorization |

Сайт прямо сообщает, что Hired Valley не трудоустраивает от лица компании.
Поэтому `first_party_verified=yes` и `apply_verified=yes` возможны только после
перехода к exact employer/ATS surface; service contact не считается Apply.

## Trust и ловушки

- География «США / Европа / GCC», remote worldwide, relocation и claimed company
  reach — только контекст карьерной услуги; проверять eligibility в вакансии.
- Не переносить в tracker обещания о количестве вакансий, ATS-проходе или
  результате клиентов как факты конкретной job.
- Не передавать в Telegram CV, контактные данные или другие материалы в рамках
  discovery.
- Если exact employer route не найден, не оставлять lead без исхода: записать
  `reviewing` с `next_action=resolve first-party listing` либо screening outcome,
  когда hard blocker подтверждён из переданного lead-а.

## Stop rule

Public source pass заканчивается после одного preflight homepage и проверки
доступных public references. Для Hired Valley нет самостоятельного narrow/broad
scan. Дальнейшая обработка начинается только от конкретного user-supplied lead-а
и завершается first-party verification, точным unresolved next action или
duplicate reference.
