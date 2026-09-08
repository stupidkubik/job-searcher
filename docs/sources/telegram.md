# Telegram local discovery playbook

Checked: 2026-08-20

Общий lifecycle обязателен и описан в [`README.md`](README.md). Машинная
политика source находится в
[`config/sources.toml`](../../config/sources.toml), а raw inbox contract — в
[`data/inbox/README.md`](../../data/inbox/README.md).

## Роль и trust boundary

`source=Telegram` — локальный discovery-only источник. Telegram-пост
подтверждает только факт находки lead-а; он не доказывает employer
identity, актуальность, географию, work authorization или рабочий
Apply route. В registry источник помечен `aggregator=true`,
`first_party_required=true` и `apply_required=true`.

Значение legacy `Find My Remote / Telegram` остаётся в canonical enum
для исторических записей. Новый adapter всегда проецирует
`source=Telegram`; он не переписывает legacy provenance.

## Безопасная локальная установка

1. Предпочтительно использовать отдельный Telegram account для job
   search, чтобы ограничить объём диалогов и последствия отзыва
   session.
2. Вручную создать Telegram application на `my.telegram.org` и получить
   `api_id`/`api_hash`. Не передавать их агенту, не вставлять в issue,
   chat, tracked `.env` или shell history.
3. Создать virtual environment и локально установить опциональную
   dependency:

   ```bash
   python3 -m venv .venv
   .venv/bin/python -m pip install -r requirements/telegram.txt
   ```

4. Задать `TELEGRAM_API_ID` и `TELEGRAM_API_HASH` только в локальном
   process/secret manager. Для production задать
   `JOB_TRACKER_TELEGRAM_DIR` на защищённый каталог вне checkout. Для
   разового запуска его можно передать как `--data-dir PATH`.
5. До логина запустить локальную диагностику, затем один раз
   выполнить интерактивный login:

   ```bash
   .venv/bin/python scripts/import_telegram.py --format json doctor
   .venv/bin/python scripts/import_telegram.py login
   ```

   Номер телефона, login code и 2FA password вводятся только в
   интерактивные prompts. Не передавать их CLI-аргументами или в
   agent chat. До настройки allowlist успешный `doctor` возвращает
   `status=ok`, `ready_for_pull=false` и `next_action=configure allowlist`:
   базовая установка исправна, но pull пока намеренно не готов.

## Allowlist и bounded pull

`list-dialogs` только показывает доступные broadcast channels,
supergroups и bots. Приватные чаты с людьми не перечисляются.
Выберите каналы вручную и запишите только их numeric peer IDs:

```bash
.venv/bin/python scripts/import_telegram.py --format json list-dialogs
.venv/bin/python scripts/import_telegram.py allowlist set -1001234567890
.venv/bin/python scripts/import_telegram.py allowlist show
```

Username и title — только display metadata; они не дают adapter-у права
на чтение. `pull` без непустого allowlist завершается ошибкой;
режима «читать всё» нет.

Присутствие peer в `list-dialogs` не делает его pullable. `pull`
читает только broadcast channels и supergroups: лишь у них есть
per-message permalink, который требует lead contract и который уходит
в canonical provenance как `source_url`. Bot или приватный чат в
allowlist попадёт в `errors` с `detail`, начинающимся на
`allowlisted peer is not pullable`, и его cursor не сдвинется.

## Read-only preview

`preview` — просмотр без записи: не трогает lead spool, cursor state и
raw inbox, поэтому у него нет обязательства по permalink. Это
единственный способ заглянуть в peer, который lead contract не может
представить, — например в bot chat.

```bash
.venv/bin/python scripts/import_telegram.py --format json preview 7132934089 --limit 300
.venv/bin/python scripts/import_telegram.py --format json preview 7132934089 \
  --limit 300 --keyword frontend --keyword react --no-text
```

`--limit` — count bound (последние N сообщений, новые первыми), а не
date window; default 200. Numeric peer ID вводит человек на каждый
вызов: это более узкая авторизация, чем allowlist, а не обход его.
Приватные чаты с людьми `preview` читать отказывается.

Текст сообщений входит в вывод по умолчанию: для фида вакансий он и есть
полезная нагрузка, а не побочные приватные данные. `--no-text` оставляет
только `text_length`, `matched_terms` и `outbound_urls` — это дешёвый
первый проход, чтобы отобрать `message_id` до чтения текстов. В
`leads show` дефолт обратный: там читается уже сохранённый spool.

Первый pull делайте с малыми границами; например:

```bash
.venv/bin/python scripts/import_telegram.py --format json pull \
  --max-age-days 2 --max-messages-per-peer 100 \
  --keyword frontend --keyword react --keyword typescript
```

При первом pull adapter передаёт Telegram границу `max_age_days` и начинает
чтение с неё, а не с самого старого сообщения за всю историю канала. После
появления cursor последующие запуски читают только ещё не обработанный хвост.

Adapter пишет immutable lead batch, затем атомарно обновляет cursor.
Повторный fetch после сбоя допустим; stable identity
`telegram:<peer_id>:<message_id>` предотвращает повторную запись lead-а.
`FLOOD_WAIT` не обходится агрессивным retry: остановите pass и
дождитесь указанного Telegram времени.

Summary содержит `peers.backlog` и `backlog_peers`. Если backlog не пуст,
повторяйте bounded pull: adapter читает сообщения от старых к новым и после
каждого успешного batch безопасно продвигает cursor только по обработанной
части. `backlog=0` означает, что на момент запуска весь доступный хвост в
заданных границах разобран.

Отказ на отдельном сообщении не прерывает канал. Такое сообщение попадает в
`skipped_messages` с `peer_id`, `message_id` и безопасным `detail`, а cursor
продвигается за него: иначе весь хвост канала после него стал бы недостижим
навсегда. Ошибка провайдера сообщается только по типу — её текст не выводится.
Непустой `skipped` даёт `status=partial` и exit code 2, то есть требует ручного
разбора: откройте `https://t.me/<username>/<message_id>` (или
`t.me/c/<internal_id>/<message_id>` для приватного канала) и при необходимости
нормализуйте lead вручную. Отказ на уровне peer (`errors`) cursor не двигает —
там повторный pull безопасен и уместен.

## Подтверждение lead-а и ingest

Сначала просмотрите найденные identities. Обычные `list` и `show` не выводят
полный текст сообщения:

```bash
.venv/bin/python scripts/import_telegram.py --format json leads list --limit 100
.venv/bin/python scripts/import_telegram.py --format json leads show \
  telegram:-1001234567890:42
```

Если для ручной проверки нужен исходный текст, его можно вывести только явным
локальным opt-in. Не копируйте этот вывод в agent chat или облачные логи:

```bash
.venv/bin/python scripts/import_telegram.py --format json leads show \
  telegram:-1001234567890:42 --include-text
```

В raw inbox можно спроецировать только один точно выбранный lead
после ручного подтверждения `company`, `role`, `application_url` и
`raw_location`. Не пытайтесь выводить неоднозначные факты из
текста. Команда по identity лида создаёт новый immutable batch
и в JSON summary возвращает `status`, `identity`, `source_job_id` и
`inbox_batch`:

```bash
.venv/bin/python scripts/import_telegram.py --format json normalize \
  telegram:-1001234567890:42 \
  --company "Example Co" \
  --role "Frontend Developer" \
  --application-url "https://careers.example.test/jobs/frontend" \
  --raw-location "Serbia or remote"
```

Если один пост содержит несколько вакансий, запустите `normalize` отдельно для
каждой подтверждённой пары role/application URL. У записей сохранится общий
Telegram `source_url`, но будут разные устойчивые `source_job_id`; ingest
создаст отдельные вакансии и не примет общий URL поста за автоматический дубль.

По умолчанию batch пишется в repository `data/inbox/`; для изолированной
проверки можно явно передать `--inbox-dir PATH`. В следующих
командах используйте exact `inbox_batch` из summary, а не шаблон имени.

Созданный `data/inbox/telegram-*.jsonl` не редактируется. Он не
содержит полный Telegram text, credentials или session material. Далее:

```bash
python3 scripts/inbox.py validate data/inbox/telegram-<timestamp>-<id>.jsonl
python3 scripts/jobs.py ingest data/inbox/telegram-<timestamp>-<id>.jsonl \
  --dry-run --format json
```

Dry-run должен оставить `first_party_verified=unknown`,
`apply_verified=unknown` и `next_action=verify first-party`. Затем человек
открывает exact employer/ATS listing по общему lifecycle и проверяет
актуальность, eligibility и Apply. Только `jobs.py` имеет право на
canonical write; Telegram adapter и normalizer никогда не пишут напрямую в
`jobs.csv` или `job_sources.csv`.

## Приватность, retention и kill switch

- Session, cursor, allowlist, raw lead batches, полный текст, номер
  телефона и `api_hash` остаются вне Git и repository artifacts.
- Сырой Telegram text не передаётся в LLM, agent chat или cloud
  services. Исключение — только явный локальный вывод команды `leads show` с
  флагом `--include-text`, которым управляет пользователь. Классификация и
  projection детерминированы.
- Не бэкапить session в Git, CI artifacts или общие cloud drives. Raw lead
  batches удалять после короткого pilot/retention window, когда они больше
  не нужны для дедупликации и аудита.
- Kill switch: остановить все локальные запуски, завершить session
  в Telegram **Settings → Devices**, после чего удалить локальный session файл
  из data directory. Это делает пользователь; adapter не отзывает
  Telegram devices автоматически.

## Реализация: два файла, одна ответственность каждый

docs/agent-write-path-plan-2026-09-07.md, Э9/G-11. `scripts/import_telegram.py`
(790 строк) и `scripts/telegram_leads.py` (800 строк) вместе — 26% кодовой базы
`scripts/`, но это не дублирование одной ответственности, а два разных слоя,
разделённые ровно по Telethon-границе:

- `scripts/import_telegram.py` — CLI и Telethon adapter. Всё, что говорит по
  сети (`doctor`, `login`, `list-dialogs`, `preview`, `pull`), парсит
  аргументы командной строки и печатает `--format json`/`text` вывод, живёт
  здесь. Telethon импортируется только внутри команд, которым он нужен, чтобы
  остальная кодовая база не получила рантайм-зависимость от него.
- `scripts/telegram_leads.py` — чистый domain-модуль без Telethon-зависимости:
  схема lead-а, приватное локальное хранилище (`leads/`, cursor, allowlist),
  normalize в `data/inbox/*.jsonl` и связанная валидация. Его можно
  импортировать и тестировать без установленного Telethon и без сети — так
  и устроены unit-тесты этого модуля.

Оба файла остаются: слияние вернуло бы Telethon-зависимость в код, который
сейчас можно тестировать оффлайн, а разделение по ответственности (сеть и
CLI vs. чистый domain/storage) не даёт того же дублирования, которое было бы
у двух похожих модулей одного слоя. `import_telegram.py` — единственная
командная точка входа; `leads`-подкоманды в примерах выше — это тонкая
CLI-обвязка над `telegram_leads.py`, а не отдельный параллельный интерфейс.

## Troubleshooting

| Симптом | Действие |
|---|---|
| `doctor` вернул `permissions.ok=false` | В `paths` перечислены относительные пути внутри data directory, которые доступны не только владельцу. Проверка обходит всё дерево, включая `leads/` с полным текстом сообщений. Вернуть `chmod 700` каталогам и `chmod 600` файлам; symlink внутри приватного каталога удалить, а не исправлять права. |
| Telethon не найден | Активировать нужный venv и повторить install из `requirements/telegram.txt`; обычные tracker CLI/tests не требуют Telethon. |
| 2FA не принят | Повторить `login` локально; password вводить только в hidden prompt. |
| Session revoked/expired | Остановить pull, удалить только точный local session после отзыва device, затем повторить interactive login. |
| Username/title изменился | Проверить dialog, но не менять allowlist только из-за display metadata: authority — numeric peer ID. |
| `FLOOD_WAIT` | Не retry-loop: остановиться на указанный интервал, затем запустить bounded pull. |
| Пост удалён | Сохранённый lead остаётся discovery evidence; first-party status всё равно проверяется отдельно. |
| `skipped` > 0 | Сообщение не проецируется детерминированно (например удалённый пост без даты). Cursor уже прошёл за него; разобрать по `message_id` из `skipped_messages` вручную, повторный pull его не вернёт. |
| Один peer постоянно в `errors` | Cursor этого peer намеренно не двигается. Проверить, что numeric peer ID всё ещё доступен и является broadcast channel/supergroup; `detail` присутствует только для собственных ошибок adapter-а. |
| Bot виден в `list-dialogs`, но `pull` его не читает | Ожидаемо: у bot chat нет per-message permalink, поэтому lead contract его не принимает. Не подставлять `t.me/<bot_username>` вместо permalink — это ссылка на чат, а не на сообщение, и она попала бы в canonical provenance как ложный `source_url`. |
| Private permalink не открывается | Не считать его first-party URL. При normalize `t.me/c/...` и numeric peer/message IDs попадут в canonical provenance в Git; если это неприемлемо, не нормализовать такой lead либо хранить весь repository только в подходящей приватной trust boundary. Для заявки использовать employer/ATS URL. |

## Stop rule первой поставки

Проход завершён, когда bounded pull обработал только allowlisted peers,
каждый выбранный lead получил immutable local outcome, а каждая
спроецированная vacancy прошла inbox validation и ingest dry-run.
Daemon, live listener, edit/delete reconciliation, Bot API, global search,
media/OCR, LLM-classification, automatic verification и application submission в
первую поставку не входят.
