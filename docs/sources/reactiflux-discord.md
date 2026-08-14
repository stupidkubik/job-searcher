# Reactiflux Discord search playbook

Checked: 2026-08-14

Current reference:

- [Reactiflux](https://www.reactiflux.com/)

Общий lifecycle обязателен и описан в [`README.md`](README.md). Здесь только
Reactiflux Discord-specific правила.

## Роль и доступ

Reactiflux Discord — signed-in, message-based React/community discovery source.
Использовать `source=Reactiflux Discord`. Работать только с видимой history и
search UI; не отправлять messages, reactions, emails или applications.

## Routes: narrow → broad

| Pass | Search terms in jobs channel | Назначение |
|---|---|---|
| Narrow | frontend, React, Next.js, JavaScript, TypeScript | основной signal |
| Broad | Product, Support, Full-stack, UI, web | adjacent roles |
| Recency | newest messages, затем выбранное fallback window | контролируемая глубина |

Читать message целиком и проверять replies/thread context, если там уточняются
location, closure или application instructions.

## Exact identity и original source

| Значение | Правило |
|---|---|
| exact message | `discord.com/channels/<server>/<channel>/<message>` |
| stable `source_job_id` | `<server_id>:<channel_id>:<message_id>` |
| `source_url` | exact message permalink |
| original route | employer careers/form/link из message → exact public vacancy |

Message ID без server/channel context недостаточен для portable provenance.
Repost message может вести к той же employer requisition и тогда добавляется как
ещё один source reference.

## Source status и first-party boundary

| Signal | Доказывает | Не доказывает |
|---|---|---|
| message доступно | source post существует | vacancy всё ещё open |
| direct hiring email | stated application route | public first-party vacancy |
| official careers/form link | candidate employer route | form exact/live до проверки |
| reply об update/closure | source-side status evidence | canonical status без employer check |

Tracked variants: World Anvil имел direct post + email без public first-party
vacancy; ArtWod разрешился в живую official careers form; Starlet — в official
company careers page.

## Trust и ловушки

- Email может быть валидным application route, но сам по себе не выставляет
  `first_party_verified=yes`.
- Discord message может сохраниться после закрытия или редактироваться.
- Poster identity и server membership не заменяют employer ownership check.
- Search должен включать Support/Product/Full-stack: релевантный frontend scope
  часто скрыт в adjacent title.
- Агент не отправляет email даже при явном адресе в post.

## Stop rule

Остановиться после narrow и broad scans jobs channel за выбранное recency window
и проверки relevant reply context. Каждое открытое exact message с конкретной
ролью получает outcome или duplicate reference.
