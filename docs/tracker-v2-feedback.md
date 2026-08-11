# Tracker v2 — обратная связь и план улучшений

Дата: 2026-08-11

> Этот файл сохранён как исходная обратная связь. Проанализированная спецификация,
> принятые решения, порядок работ и конкретные артефакты находятся в
> [`tracker-v2-plan.md`](tracker-v2-plan.md).

## Контекст

Текущая версия репозитория уже хорошо работает как операционная система поиска работы, а не просто как список вакансий:

- `data/jobs.csv` выступает единым структурированным источником истины;
- `applications/<id>.md` хранит длинный контекст по отдельной вакансии;
- `config/profile.md` задаёт профиль кандидата и ограничения;
- `AGENTS.md` фиксирует правила, которые защищают от повторных откликов, неверной географии и фантазирования фактов;
- Git даёт прозрачную историю изменений и решений.

Главная рекомендация для следующей версии: **не строить веб-интерфейс раньше времени**. Слой `CSV + Markdown + scripts + Git` остаётся очень удачным: он прозрачен, легко читается человеком и агентом, хорошо версионируется и не прячет логику за UI.

Следующий этап лучше посвятить качеству модели данных и автоматизации ingestion pipeline.

---

# P0 — три главных изменения

## 1. Разделить состояние вакансии и состояние отклика

### Проблема

Текущее поле `status` отвечает сразу на два разных вопроса:

1. Что происходит с самой вакансией?
2. Что происходит с нашей заявкой?

Это создаёт неоднозначность. Например, пользователь уже откликнулся, но работодатель позже закрыл вакансию. Одно поле не может корректно одновременно хранить `Applied` и `Closed`.

### Предложение

Разделить состояние на два независимых поля.

```text
listing_status:
  open
  closed
  unknown

application_status:
  not_started
  reviewing
  apply
  applied
  interviewing
  offer
  rejected
  ghosted
  withdrawn
```

Пример:

```text
listing_status=closed
application_status=applied
```

### Польза

- состояние объявления перестаёт затирать историю отклика;
- становится проще анализировать конверсию;
- можно отдельно перепроверять открытость вакансий;
- исчезают спорные переходы вроде `Applied -> Closed`.

### Миграция

Можно мигрировать текущие значения примерно так:

| Старый `status` | `listing_status` | `application_status` |
|---|---|---|
| New | unknown/open | not_started |
| Reviewing | open | reviewing |
| Apply | open | apply |
| Applied | unknown/open | applied |
| Interviewing | unknown/open | interviewing |
| Offer | unknown/open | offer |
| Rejected | unknown | rejected |
| Ghosted | unknown | ghosted |
| Skipped | unknown/open | not_started |
| Closed | closed | not_started |
| Withdrawn | unknown | withdrawn |

Не все старые значения позволяют достоверно восстановить `listing_status`, поэтому лучше использовать `unknown`, если первоисточник не перепроверен.

---

## 2. Добавить явные поля проверки первоисточника

### Проблема

Сейчас критическая информация о качестве вакансии часто прячется в `notes`.

Пример реального кейса с Himalayas:

```text
Aggregator card is live, but official careers page does not contain the role.
```

Это не комментарий, а структурированное состояние данных.

### Предложение

Добавить:

```text
verified_at
first_party_verified
apply_verified
listing_status
```

Возможный формат:

```text
verified_at=2026-08-11
first_party_verified=yes
apply_verified=no
listing_status=closed
```

Для boolean-полей можно использовать enum:

```text
yes
no
unknown
```

### Значение полей

`verified_at`
: когда последний раз открывался первоисточник.

`first_party_verified`
: подтверждено ли, что найден официальный careers/ATS источник работодателя.

`apply_verified`
: проверено ли, что форма/кнопка Apply действительно принимает заявки.

`listing_status`
: открыто ли само объявление на момент последней проверки.

### Польза

Появляются запросы уровня:

```text
show Reviewing jobs not verified for 3 days
```

или:

```text
show jobs where apply_verified != yes
```

без парсинга свободного текста в `notes`.

### Дополнительная идея

Добавить команду:

```bash
python3 scripts/jobs.py stale --days 3
```

которая показывает вакансии, нуждающиеся в повторной проверке.

---

## 3. Сделать inbox / ingestion layer между источниками и `jobs.csv`

### Проблема

По мере подключения API, email alerts и агрегаторов опасно разрешать каждому источнику напрямую писать в главный CSV.

Автоматический импорт должен сначала попадать в промежуточный слой, где можно:

- нормализовать данные;
- дедуплицировать;
- проверить фильтры;
- подтвердить первоисточник;
- только потом создать запись в `jobs.csv`.

### Предлагаемая архитектура

```text
Himalayas API
LinkedIn email alerts
HiringCafe
Wellfound
other sources
      ↓
data/inbox/
      ↓
normalization
      ↓
filtering
      ↓
dedupe
      ↓
first-party verification
      ↓
jobs.py ingest
      ↓
data/jobs.csv
```

Пример файлов:

```text
data/inbox/himalayas.jsonl
data/inbox/linkedin.jsonl
data/inbox/hiringcafe.jsonl
```

### Минимальный raw record

```json
{
  "source": "Himalayas",
  "source_id": "...",
  "company": "Example",
  "title": "Frontend Developer",
  "source_url": "...",
  "application_url": "...",
  "published_at": "2026-08-11",
  "raw_location": "Worldwide",
  "discovered_at": "2026-08-11"
}
```

### Команда

```bash
python3 scripts/jobs.py ingest data/inbox/himalayas.jsonl
```

Желаемый результат:

```text
42 fetched
31 rejected by filters
6 duplicates
3 stale
2 candidates for review
```

### Важное правило

Importer **не должен автоматически считать агрегаторную карточку живой вакансией**.

Проверка careers/ATS остаётся обязательным gate перед переводом вакансии в нормальный `Reviewing`/`apply` pipeline.

---

# P1 — следующие улучшения

## 4. Усилить дедупликацию

### Проблема

Одна и та же вакансия может одновременно приехать из:

- Himalayas;
- HiringCafe;
- LinkedIn;
- Hirify;
- Wellfound;
- careers page.

При этом все URL могут отличаться.

Текущее правило `original_url -> company + role` хорошо для ручного режима, но станет недостаточным при автоматическом ingestion.

### Предложение

Ввести нормализованный fingerprint:

```text
normalized_company + normalized_role + normalized_location
```

Дополнительно учитывать:

- first-party ATS URL;
- company careers slug;
- source-specific job ID;
- publication window;
- remote geography.

### Правильная модель

Логически лучше считать, что одна вакансия имеет несколько source references:

```text
job-0083
  ├── Himalayas URL
  ├── LinkedIn URL
  ├── HiringCafe URL
  └── Greenhouse URL
```

а не создавать четыре `job-*`.

### Без большой миграции

Необязательно сразу менять CSV на реляционную модель.

Первый этап: дедупликацию реализовать внутри `jobs.py`, а список дополнительных источников хранить в application markdown или отдельном auxiliary-файле.

Позже можно добавить таблицу:

```text
data/job_sources.csv
```

с полями:

```text
job_id,source,source_url,source_job_id,found_at
```

---

## 5. Создать registry источников

### Проблема

Сейчас поведение разных источников распределено между:

- `config/profile.md`;
- `AGENTS.md`;
- отдельными docs;
- инструкциями проекта.

Когда источников станет 15–20, это будет трудно поддерживать.

### Предложение

Создать:

```text
config/sources.yml
```

Пример:

```yaml
himalayas:
  enabled: true
  type: api
  cadence:
    narrow: daily
    broad: "mon,wed,fri"

  geo:
    - Serbia
    - Worldwide

  max_age_days:
    narrow: 7
    fallback: 30

  verify_first_party: true
  verify_apply: true

wellfound:
  enabled: true
  type: web
  verify_remote_text: true
  verify_apply: true

hiringcafe:
  enabled: true
  type: web
  verify_first_party: true
```

### Что можно хранить в registry

- `enabled`;
- тип интеграции: API / email / web / manual;
- cadence;
- geo strategy;
- max age;
- narrow queries;
- broad queries;
- обязательные проверки;
- источник считается aggregator или first-party;
- известные caveats.

Это позволит future importers работать из общей конфигурации вместо hardcoded значений.

---

## 6. Научить `jobs.py` принимать структурированный JSON

### Проблема

CLI с десятками flags удобен для человека, но не очень удобен для автоматических импортёров и AI-агентов.

Главная запись всё равно должна проходить через `jobs.py`, потому что именно там должны жить:

- validation;
- ID allocation;
- duplicate detection;
- enum checking;
- application file creation.

### Предложение

Поддержать:

```bash
python3 scripts/jobs.py add --json job.json
```

и/или:

```bash
cat job.json | python3 scripts/jobs.py add --stdin
```

Пример input:

```json
{
  "company": "Example",
  "role": "Frontend Developer",
  "source": "Himalayas",
  "status": "Reviewing",
  "original_url": "https://...",
  "source_url": "https://..."
}
```

### Желаемое поведение

`jobs.py` сам:

1. валидирует поля;
2. нормализует значения;
3. проверяет дубль;
4. выдаёт следующий `job-NNNN`;
5. создаёт application markdown при необходимости;
6. записывает CSV;
7. запускает validation.

Это сильно снижает риск повреждения CSV при автоматизации.

---

# P2 — качество поиска и ежедневный UX

## 7. Сделать `match_score` объяснимым

### Проблема

Число вроде `8.5` полезно в момент анализа, но спустя месяц трудно понять, почему одна вакансия получила 8.5, а другая 7.5.

### Не надо делать

Не стоит строить сложную псевдонаучную scoring machine с десятками весов.

### Достаточная модель

Хранить несколько простых составляющих:

```text
match_stack
match_level
match_geo
match_domain
match_experience
```

Например, 0–2 балла каждая:

```text
stack       2
level       1
geo         2
domain      2
experience  1
----------------
score       8/10
```

### Польза

Позже можно анализировать:

- что чаще всего мешает отклику;
- какие вакансии реально доходят до Applied;
- где слишком часто делаются stretch applications;
- какие сигналы лучше всего коррелируют с ответами работодателей.

### Альтернатива без изменения CSV

Пока можно хранить breakdown в `applications/<id>.md`, а агрегированный `match_score` оставить в CSV.

---

## 8. Сделать нормальную очередь действий

Поле `next_action` уже есть и является хорошей основой.

### Предложение

Добавить:

```bash
python3 scripts/jobs.py todo
```

Пример:

```text
TODAY

job-0065  Kodees Labs       review application
job-0067  Costy             review application

FOLLOW UPS

job-0055  ElevenLabs        2026-08-17
job-0056  Nortal            2026-08-17
job-0064  TransPerfect      2026-08-17

STALE REVIEW

job-0022  Canonical         reviewing for 4 days
```

### Возможные секции

- overdue;
- today;
- follow-ups;
- reviewing too long;
- Apply but not submitted;
- awaiting response;
- stale verification;
- tests/interviews due soon.

Для ежедневной работы эта команда, вероятно, полезнее раннего dashboard.

---

# Рекомендуемая архитектура v2

```text
                    config/profile.md
                    config/sources.yml
                           │
                           ▼
External sources ──> data/inbox/*.jsonl
                           │
                           ▼
                  source normalizers
                           │
                           ▼
                   filtering engine
                           │
                           ▼
                      deduplication
                           │
                           ▼
                first-party verification
                           │
                           ▼
                     scripts/jobs.py
                           │
               ┌───────────┴───────────┐
               ▼                       ▼
        data/jobs.csv          applications/*.md
               │
               ▼
      todo / reports / analytics
```

Ключевой принцип: **сырой внешний сигнал никогда не становится автоматически подтверждённой вакансией**.

---

# Предлагаемая последовательность реализации

## Phase 1 — data model

1. Добавить `listing_status`.
2. Переименовать/разделить текущий application status.
3. Добавить `verified_at`.
4. Добавить `first_party_verified`.
5. Добавить `apply_verified`.
6. Обновить `data/schema.md`.
7. Обновить validation в `scripts/jobs.py`.
8. Написать migration текущего CSV.
9. Добавить tests на новые invariants.

После Phase 1 tracker уже станет существенно устойчивее.

## Phase 2 — structured writes

1. Добавить `jobs.py add --json`.
2. Добавить `jobs.py add --stdin`.
3. Убедиться, что существующий CLI использует тот же внутренний code path.
4. Добавить automatic validation после записи.
5. Добавить machine-readable output (`--format json`) для агентов и scripts.

## Phase 3 — ingestion

1. Создать `data/inbox/`.
2. Определить canonical raw record schema.
3. Добавить `jobs.py ingest`.
4. Добавить dry-run.
5. Добавить duplicate reporting.
6. Подключить первым Himalayas importer.
7. После нескольких ручных прогонов подключать остальные источники.

## Phase 4 — source registry

1. Добавить `config/sources.yml`.
2. Перенести туда cadence и source-specific caveats.
3. Использовать registry в importers.
4. Не переносить туда факты о кандидате: они остаются в `config/profile.md`.

## Phase 5 — daily UX

1. `jobs.py todo`.
2. `jobs.py stale`.
3. `jobs.py stats`.
4. weekly report generation.
5. match-score breakdown при необходимости.

---

# Минимальные invariants v2

Рекомендуемые правила:

1. `application_status=applied|interviewing|offer|rejected|ghosted|withdrawn` требует `applied_at`.
2. `application_status=interviewing|offer|rejected` требует `response_at`.
3. `listing_status=closed` не должен автоматически менять `application_status`.
4. `first_party_verified=yes` требует непустой `original_url`.
5. `apply_verified=yes` требует `first_party_verified=yes` либо явного исключения для first-party source.
6. `verified_at` должен обновляться при изменении любого verification field.
7. Aggregator source не может сам по себе выставлять `first_party_verified=yes`.
8. Все записи из automated import сначала проходят dedupe.
9. `Applied` выставляется только после фактической отправки человеком.
10. Никакая автоматизация не должна переписывать подтверждённые пользовательские факты из `config/profile.md`.

---

# Что пока не делать

## Веб-интерфейс

Пока не нужен.

Причины:

- Git уже даёт историю;
- CSV удобен для аналитики;
- Markdown удобен для длинного контекста;
- CLI проще автоматизировать;
- UI добавит дополнительный слой состояния и синхронизации.

К UI стоит возвращаться, когда появится реальная боль от ежедневного CLI, а не просто желание сделать tracker красивее.

## База данных

SQLite/Postgres сейчас тоже не обязательны.

Переход имеет смысл, если появятся:

- тысячи вакансий;
- сложные relations source <-> job;
- параллельные процессы записи;
- отдельное приложение/API;
- заметные ограничения CSV при аналитике.

До этого CSV остаётся хорошим canonical storage.

## Полностью автоматический Apply

Не является целью tracker v2.

Автоматизировать стоит discovery, dedupe, verification queue и подготовку данных. Фактический отклик лучше оставлять осознанным действием пользователя.

---

# Definition of Done для хорошей v2

Версия v2 уже достаточно хороша, если выполняется следующий сценарий:

```text
1. Источник отдаёт 50 вакансий.
2. Они сохраняются в inbox.
3. Importer нормализует данные.
4. 35 вакансий автоматически отбрасываются по hard filters.
5. 10 распознаются как уже известные.
6. 5 попадают в verification queue.
7. После проверки первоисточника 3 оказываются stale/closed.
8. 2 создаются в jobs.csv как реальные кандидаты.
9. jobs.py todo показывает их пользователю.
10. После ручного отклика application_status меняется на applied.
11. Позднее закрытие объявления меняет только listing_status.
```

Если этот путь работает надёжно, tracker уже становится не просто журналом откликов, а полноценным персональным job-search pipeline.

---

# Приоритет в одной строке

Если делать только три вещи сейчас:

1. **разделить `listing_status` и `application_status`;**
2. **добавить verification state (`verified_at`, `first_party_verified`, `apply_verified`);**
3. **сделать inbox + универсальный `jobs.py ingest`.**

Это даст максимальный прирост надёжности и подготовит фундамент для Himalayas API, LinkedIn email parser и следующих автоматизированных источников без преждевременного усложнения проекта.
