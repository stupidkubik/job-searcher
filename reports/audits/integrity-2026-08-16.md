# Аудит целостности проекта — 2026-08-16

Полный debug-проход по коду, данным, конфигурации, CI и документации.
Состояние репозитория: ветка `main`, `995ea35`, рабочее дерево чистое.

## Сводка

| Проверка | Результат |
|---|---|
| `jobs.py validate --strict` | ✅ 214 записей, 221 reference, 0 ошибок, 0 предупреждений |
| `jobs.py render-tracker --check` | ✅ `docs/tracker.md` актуален |
| `python3 -m unittest discover -s tests` | ✅ 110 тестов, OK (17.9 s) |
| `jobs.py backfill-sources --check` | ✅ 0 недостающих references |
| `jobs.py dupes` | ⚠️ 22 пары-кандидата |
| `source_config.py` | ✅ конфиг валиден, но покрывает 1 источник из 19 |

Формальные проверки зелёные. Проблемы, найденные проходом, — это то, что текущая
validation **не** ловит: достижимые состояния, ломающие рендер, обходы write-path
контракта, расхождение карточек с canonical, дрейф данных и документации.

Найдено: **2 критических**, **5 высоких**, **12 средних**, **8 низких**.

> **Статус на 2026-08-16:** оба критических пункта закрыты, см.
> [«Исправления»](#исправления-2026-08-16) в конце документа. Разделы C1 и C2
> сохранены как описание дефекта и обоснование правки.

---

## Критические

### C1. `validate --strict` сломается сам по себе 2026-09-09 — без единого коммита

> ✅ Исправлено 2026-08-16.

`scripts/jobs.py:515-521` добавляет предупреждение, когда `application_status=applied`
и с `applied_at` прошло больше `GHOST_AFTER_DAYS = 30` без `response_at`.
`cmd_validate` (`scripts/jobs.py:2158`) при `--strict` считает **любое** предупреждение
провалом: `ok = not errors and not (warnings and args.strict)`.

Сейчас в данных 24 записи `applied` без `response_at`. Самая старая — `job-0001`
(`applied_at=2026-08-09`), ей 7 дней. Через 24 дня она перешагнёт порог, дальше
остальные подтянутся в течение недели.

Что сломается одновременно:

- `.github/workflows/validate.yml` — шаг «Проверка схемы jobs.csv» на каждом push и PR;
- `.github/workflows/agent-operations.yml`, шаг «Validate resulting tracker state» —
  то есть **весь connector write-path встанет**, включая операции, которые к этим
  записям отношения не имеют;
- локальные проверки из `README.md` и `AGENTS.md`.

Причём «починить» это данными нельзя: предупреждение исчезнет только когда человек
явно проставит `ghosted` каждой записи. Это не баг данных, а конструктивный дефект —
временна́я эвристика попала в блокирующий gate.

**Рекомендация.** Разделить предупреждения на два класса: детерминированные
(зависят только от содержимого строки — будущие даты, `stage=Offer` при чужом статусе)
и временны́е (ghost-эвристика). `--strict` должен блокировать только первый класс.
Ghost-подсказка — место для `todo`/`stale`, а не для validation gate.

Воспроизведение:

```bash
python3 -c "
import csv
from datetime import date
rows=list(csv.DictReader(open('data/jobs.csv',encoding='utf-8')))
print(sorted((r['applied_at'],r['id']) for r in rows if r['application_status']=='applied' and r['applied_at'] and not r['response_at'])[:3])"
```

### C2. Достижимое состояние, которое проходит validation, но намертво ломает `render-tracker`

> ✅ Исправлено 2026-08-16. При разборе нашёлся второй вариант той же дыры —
> через `decision_reason`, а не только через `listing_status`; закрыты оба.

`tracker_section()` (`scripts/jobs.py:2257-2282`) не умеет классифицировать строку
с `application_status ∈ {not_started(без reason), reviewing, apply}` и
`listing_status=closed`:

- в `applications` не попадает — статус не post-application;
- в `archive` не попадает — `derived_state()` вернёт `Reviewing`, а не `Closed`
  (ветка `Closed` в `derived_state`, `scripts/jobs.py:2238`, требует `not_started`);
- в `action_now` не попадает — требуется `listing_status=open`;
- в `to_verify` не попадает — требуется `listing_status != closed`;
- → `raise ValueError` → `die()`.

При этом `validate_rows` это состояние пропускает: проверка на строке 486
(`listing closed + not_started + reason != closed_before_application`) покрывает
только `not_started`, а `reviewing`/`apply` не покрыты ничем.

Проверено на копии репозитория:

```
$ python3 scripts/jobs.py set job-0169 listing_status=closed
job-0169  application_status=reviewing  listing_status=closed  stage=None
$ python3 scripts/jobs.py validate --strict
проверено записей: 214; ... ошибок: 0; предупреждений: 0
$ python3 scripts/jobs.py render-tracker
error: render-tracker: job-0169: cannot classify application_status='reviewing',
       listing_status='closed', decision_reason=''
```

Отягчающее обстоятельство: **`docs/jobs-cli.md:401` приводит ровно эту команду
как пример** в разделе «Примеры обновления и проверки»:

```bash
python3 scripts/jobs.py set job-0001 listing_status=closed --format json
```

Выйти из состояния можно только вторым `set` или ручной правкой CSV — то есть
через нарушение контракта. В CI это даст красный `render-tracker --check`, а в
connector-runner — падение после уже применённой canonical записи.

**Рекомендация (одно из двух, лучше оба):**

1. Закрыть дыру в `validate_rows`: `listing_status=closed` при
   `application_status ∈ PRE_APPLICATION_STATUSES` и пустом `applied_at`
   требует `decision_reason=closed_before_application` (сейчас правило есть
   только для `not_started`).
2. Сделать `tracker_section` тотальной: финальный fallback в `archive` вместо
   `ValueError`, чтобы generated view никогда не был hard-fail от данных.

Плюс исправить пример в `docs/jobs-cli.md:401` на `screen`/`verify`.

---

## Высокие

### H1. `set` обходит человеческий gate на `applied`

> ✅ Исправлено 2026-08-16, см. [«Исправления»](#h1---set-больше-не-может-выставить-lifecycle-поля) в конце документа.

`SET_PROTECTED` (`scripts/jobs.py:99`) защищает только `id`, `stage_reached`,
`verified_at`, `last_update`. `application_status` не защищён, а
`apply_job_changes` (`scripts/jobs.py:1757-1760`) дополнительно **сам** проставляет
`applied_at=today()` и `stage_reached=Applied`.

Проверено:

```
$ python3 scripts/jobs.py set job-0169 application_status=applied
job-0169  application_status=applied  listing_status=unknown  stage=Applied
$ python3 scripts/jobs.py validate --strict     # ошибок: 0
```

Это прямо противоречит железному правилу `AGENTS.md`
(«`application_status=applied` ставится только после фактической отправки заявки
человеком») и обходит всё, что делает `status_job`: проверки переходов
(`apply_status_change`, `scripts/jobs.py:1807-1900`), запрет отката из
post-application, требование `--cv-version`, синхронизацию карточки.

Connector этой дырой воспользоваться не может: `SET_ALLOWED_ARGS`
(`scripts/agent_operations.py:29`) ограничен `next_action`, `next_action_date`,
`listing_status`. Дыра только в локальном CLI — но именно им пользуется агент.

**Рекомендация.** Добавить `application_status`, `applied_at`, `response_at`,
`decision_reason` в `SET_PROTECTED` и направить их через `status`/`screen`/`verify`.
Это ровно та же логика, по которой `duplicate_listing` уже запрещён в `set`
(`scripts/jobs.py:1738`).

### H2. `add` и `set` пишут мимо транзакционного write-path

> ✅ Исправлено 2026-08-16, см. [«Исправления»](#h2--h5---транзакционность-и-package-import) в конце документа.

`verify_job`, `status_job`, `screen_job` и `ingest` идут через
`apply_dataset_transaction` (`scripts/jobs.py:1475`): файловая блокировка,
staging, backup, rollback при сбое, post-commit валидация.

`persist_add` (`scripts/jobs.py:1057-1077`) и `set_job` (`scripts/jobs.py:1771-1778`)
этого не делают:

- `persist_add` вызывает `save(plan.rows)` и `save_job_sources(plan.source_rows)`
  двумя отдельными `os.replace`. Если второй упадёт, в `jobs.csv` останется
  вакансия без provenance-строки, и откат не произойдёт — `except BaseException`
  чистит только временный файл карточки и саму карточку;
- `set_job` вызывает голый `save(rows)` без блокировки, то есть может
  затереть данные, записанные параллельным `ingest`/batch;
- ни один из двух не делает post-commit re-validation.

Вероятность низкая (однопользовательский репозиторий), последствие — молчаливое
расхождение двух canonical таблиц. Учитывая, что механизм уже написан и
используется четырьмя другими командами, это чистая непоследовательность.

**Рекомендация.** Перевести `persist_add` и `set_job` на
`apply_dataset_transaction(rows, source_rows, application_writes)`.

### H3. 9 карточек невидимы для `docs/tracker.md`

> ✅ Исправлено 2026-08-16, см. [«Исправления»](#h3--h4---карточки-найдены-и-синхронизируются-даже-после-провала) в конце документа.

`tracker_application_cards` (`scripts/jobs.py:2318`) ищет карточки по маске
`f"{row['id']}-*.md"`. Legacy-карточки названы `job-NNNN.md` — без дефиса — и под
маску не попадают. В колонке `Card` у этих вакансий стоит `—`, хотя файл есть.

Затронуты: `job-0022`, `job-0023`, `job-0024`, `job-0025`, `job-0026`, `job-0032`,
`job-0051`, `job-0052`, `job-0055`. Пять из них — отправленные заявки
(`job-0026`, `job-0032`, `job-0051`, `job-0052`) и один отказ (`job-0055`), то есть
самый ценный контекст. Проверено в `docs/tracker.md:38-39`.

Отдельно: у `job-0055` карточки две — `job-0055.md` и
`job-0055-elevenlabs-full-stack-engineer-front-en.md`. Hard-fail из
`scripts/jobs.py:2319` не срабатывает только потому, что первая не подходит под маску.

**Рекомендация.** Расширить маску до `job-NNNN.md` + `job-NNNN-*.md`, оставив
запрет на несколько совпадений, и одним коммитом переименовать/слить 9 legacy-файлов.

### H4. Карточка молча расходится с canonical после непрошедшей verification

> ✅ Исправлено 2026-08-16, см. [«Исправления»](#h3--h4---карточки-найдены-и-синхронизируются-даже-после-провала) в конце документа.

`prepare_verified_application_write` (`scripts/jobs.py:2075-2081`) синхронизирует
front matter только при `passed=True`. Если проверка показала, что вакансия
закрыта или Apply не работает, карточка остаётся со старым содержимым.

Найдено в данных — `applications/job-0150-undisclosed-web-developer.md`:

| Поле | Карточка | `jobs.csv` |
|---|---|---|
| `original_url` | (пусто) | `https://milestone.pt/en/career-opportunities/web-developer-2/` |
| `verified_at` | (пусто) | `2026-08-13` |
| `listing_status` | `unknown` | `closed` |
| `first_party_verified` | `unknown` | `yes` |
| `apply_verified` | `unknown` | `no` |

То есть карточка утверждает «не проверено», а canonical — «проверено, закрыто».
Сам шаблон (`applications/_TEMPLATE.md:15`) требует обратного: «Структурированные
поля выше должны совпадать с `data/jobs.csv`».

**Рекомендация.** Синхронизировать front matter существующей карточки при любом
`verify`, независимо от `passed`. Создание новой карточки при провале по-прежнему
не нужно.

### H5. `plan_ingest` падает, если `jobs.py` импортирован как пакет

> ✅ Исправлено 2026-08-16, см. [«Исправления»](#h2--h5---транзакционность-и-package-import) в конце документа.

`scripts/jobs.py:21-23` аккуратно обрабатывает оба варианта импорта `tracker_time`.
`scripts/jobs.py:1229` (`from ingestion import ...`) — нет. То же в
`scripts/ingestion.py:3` (`from inbox import load_batch`) и `scripts/inbox.py:13`
(`from source_config import ...`).

```
$ python3 -c "import sys; sys.path.insert(0,'.'); from scripts import jobs; \
    jobs.plan_ingest('tests/fixtures/inbox/himalayas-small.jsonl')"
FAIL: ModuleNotFoundError No module named 'ingestion'
```

Сейчас не проявляется: CI запускает `python3 scripts/jobs.py`, а тесты ingest идут
через subprocess. Но любой будущий вызов ingest из `agent_operations.py` (который
импортирует `jobs` именно как `scripts.jobs`, см. `scripts/agent_operations.py:6-9`)
упадёт. Комментарий на `scripts/jobs.py:22` прямо говорит, что второй режим импорта
поддерживается — значит инвариант нарушен.

**Рекомендация.** Одинаковый `try/except ModuleNotFoundError` во всех трёх местах.

---

## Средние — данные

### M1. 17 из 24 отправленных заявок без first-party verification

> ✅ Видимость в `todo` исправлена 2026-08-16, см.
> [«M1 — `verification_queue` видит долг любого статуса»](#m1--verification_queue-видит-долг-любого-статуса)
> в конце документа. Сам verification-долг (22 записи) не закрыт — это
> требует реальной проверки первоисточников человеком, не кода.

Порядок в `AGENTS.md` («Порядок обработки одной вакансии», шаги 2 → 7) требует
verification до отклика. Фактически:

- 15 записей `applied` с `first_party_verified=unknown`, `apply_verified=unknown`,
  пустым `verified_at`: `job-0001`, `0011`, `0012`, `0014`, `0016`, `0026`, `0032`,
  `0051`, `0052`, `0056`, `0064`, `0078`, `0079`, `0088`, `0094`, `0147`;
- 2 записи `applied` с `first_party_verified=no` **и** `apply_verified=no`:
  `job-0142`, `job-0143` (`verified_at=2026-08-12`) — то есть проверка явно
  провалилась, а заявка всё равно отправлена.

`verification_coverage=24.1%` в `stats` — это оно.

`todo` эти записи никуда не выводит: секция `verification_queue`
(`scripts/jobs.py:2697-2702`) требует `application_status=not_started`, поэтому она
сейчас пуста, хотя 22 активные записи не верифицированы. Они видны только в
`stale` (19 шт.), у которого нет отдельной секции в `todo`.

**Рекомендация.** Либо расширить `verification_queue` на активные записи любого
статуса, либо добавить в `todo` отдельную секцию для `stale` — сейчас самая
крупная проблема данных не попадает в ежедневную очередь.

### M2. `cv_version` записан неверным значением во всех 6 случаях + пуст в 21 из 27 заявок

> ✅ Исправлено 2026-08-16, см. [«M2 — `cv_version` нормализован
> до 100% покрытия»](#m2--cv_version-нормализован-до-100-покрытия) в конце
> документа.

`cv/current/README.md` задаёт контракт явно: «в `cv_version` пишется slug из
третьей колонки, не имя файла», slug = `frontend-2026-08`.

В данных: `cv-frontend-2026-08` × 6, пусто × 208. То есть используется stem
имени файла — ровно то, что запрещено. Источник ошибки — пример в
`README.md` («`--cv-version cv-frontend-2026-08`»), который противоречит примеру в
`docs/jobs-cli.md:269` («`--cv-version frontend-2026-08`»).

Из 27 записей с `applied_at` только 6 имеют `cv_version`. Блок `cv_versions` в
`stats_payload` (`scripts/jobs.py:2748-2761`) — то есть аналитика «какая версия CV
приносит ответы», заявленная в `README.md` как одна из двух целей проекта, —
построена на 22% выборке с неверным ключом.

**Рекомендация.** Исправить пример в `README.md`, привести 6 значений к
`frontend-2026-08`, дозаполнить остальные заявки. Опционально — валидировать
`cv_version` по `cv/current/README.md`.

### M3. `cover_letter` содержит значение вне схемы

> ✅ Исправлено 2026-08-16, см. [«M3 — `cover_letter`: валидация + честные
> значения»](#m3--cover_letter-валидация--честные-значения) в конце документа.

`data/schema.md:46`: поле — `no` или путь. Фактически: пусто × 207, `no` × 4,
**`yes` × 3** (`job-0051`, `job-0052`, `job-0053` — все Storyteller).
`yes` не является ни `no`, ни путём; найти сам файл по записи нельзя.
`validate_rows` это поле не проверяет вообще.

**Рекомендация.** Заменить `yes` на реальные пути (в `cv/cover-letters/` лежат
только PDF без привязки к job ID) и добавить проверку в `validate_rows`.

### M4. В `company` попали названия агрегаторов и заглушки

> ✅ Исправлено 2026-08-16, см. [«M4 — 21 заглушка сделаны уникальными»](#m4--21-заглушка-сделаны-уникальными)
> в конце документа.

- `Undisclosed` × 14 (все из Hirify);
- `FetchJobs.co` × 3, `Hire Feed` × 3 — это job-борды, не работодатели;
- `getmatch` × 1 (`job-0198`) — агрегатор.

Последствия конкретные: дедуп в `find_duplicate_candidates` и `dupes` строится на
`similarity(company, company)`, поэтому все 14 `Undisclosed` попарно совпадают на
1.00. Из 22 пар в отчёте `dupes` 4 порождены исключительно этим. Разбивка
`sources` в `stats` тоже смешивает борд и работодателя.

**Рекомендация.** Для неизвестного работодателя — уникальная заглушка
(`Undisclosed (hirify-<id>)`) или обязательное разрешение до записи; названия
бордов держать в `source`/`source_url`, а не в `company`.

### M5. `first_party_verified=yes` при `original_url` на агрегаторе

`data/schema.md:33`: `original_url` — «официальный ATS/careers URL».
7 записей нарушают это при заявленной first-party проверке:

`job-0065`, `job-0066`, `job-0067`, `job-0068`, `job-0069`, `job-0130` →
`wellfound.com`; `job-0198` → `getmatch.ru`.

Wellfound в `config/profile.md:45` числится как агрегатор, а `AGENTS.md` требует
открывать первоисточник перед анализом. Для части стартапов Wellfound
действительно и есть их ATS — но тогда это надо зафиксировать явным правилом,
а не оставлять неотличимым от ошибки. `getmatch.ru` первоисточником не является
ни при каком чтении.

**Рекомендация.** Решить и записать в `docs/sources/wellfound.md`, считается ли
Wellfound first-party. `job-0198` перепроверить.

### M6. 22 пары-кандидата в `dupes`, часть выглядит настоящими дублями

Наиболее вероятные:

- `job-0173` и `job-0186` — обе `FetchJobs.co — Frontend Developer`, Germany,
  `found_at=2026-08-14`, обе `geo_restriction`, разные LinkedIn ID;
- `job-0162` / `job-0164` / `job-0168` — `Undisclosed — Frontend Developer
  (React/TypeScript)`, попарное совпадение 1.00/1.00;
- `job-0129` / `job-0168`; `job-0194` / `job-0195` (Яндекс MultiTrack, 0.90).

`dupes` — отчёт, а не автослияние (это правильно), но 22 неразобранные пары
означают, что защита от повторного анализа, ради которой проект и существует, не
доведена до конца. `dupes --fail` в CI стоит с `continue-on-error: true`, поэтому
счётчик может расти бесконечно и никто не заметит.

**Рекомендация.** Разобрать пары через `add --duplicate-of` / `--force`, затем
снять `continue-on-error` — иначе флаг `--fail` бессмысленен.

### M7. Несогласованные screening-решения для одинаковых ролей

- `job-0164` `Frontend Developer (React/TypeScript)` → `seniority_too_high`;
- `job-0168` — та же компания-заглушка и та же роль → `other`;
- `job-0159` `Middle React Developer` → `seniority_too_high`, хотя
  `config/profile.md:9` допускает `Junior/Middle` как stretch.

Причина структурная: `decision_reason` ставится вручную/коннектором, а
детерминированные правила из `scripts/ingestion.py:11-14`
(`TOO_SENIOR_SIGNALS` — `senior`, `lead`, `staff`, `principal`, …; `middle` там нет)
к этому пути не применяются. Одинаковые входы дают разные выходы — значит
аналитика по `decision_reasons` не воспроизводима.

**Рекомендация.** Свести ручной screening к тем же сигналам, что и ingest, или
задокументировать различие в `docs/sources/README.md`.

### M8. 7 из 66 connector-запросов остались без результата

Нет `data/operations/results/` для:
`add-hirify-web-developer-823409-20260813`, `add-serpapi-junior-fullstack-20260812`,
`board-cleanup-0054-0022-0023-0129-20260812`, `job-updates-20260813-1153`,
`status-0055-0130-20260812`, `verify-watchlist-six-20260812`,
`wttj-zen-educate-emea-product-20260812`.

Для пяти видно, что операцию перезапустили под новым id (`…-v2`, `…-v3`, `…-r2`,
`…-retry`), для `board-cleanup-…` и `verify-watchlist-six-…` — что переименовали
под другой охват. Но по файлам это не читается: `data/operations/README.md`
утверждает «The runner creates the matching result exactly once» и не описывает,
что делать с брошенным запросом.

Практический риск: `data/operations/README.md:46-50` требует ждать matching result
как признак завершения. Агент, читающий каталог, не отличит «ещё выполняется» от
«брошено две недели назад».

**Рекомендация.** Записывать `status=abandoned` result для брошенных запросов
(или явный `superseded_by`) и добавить правило в контракт.

---

## Средние — конфигурация и код

### M9. Реестр источников покрывает 1 источник из 19

`config/sources.toml` содержит только `[sources.Himalayas]`.
`scripts/inbox.py:61-65` отвергает любую запись, чей `source` отсутствует в реестре
или выключен. Значит `inbox.py validate` и `jobs.py ingest` работают только для
Himalayas, тогда как в данных используются 15 источников, из них LinkedIn (52) и
Hirify (50) — крупнее Himalayas (34).

То есть весь дедуп-и-ingest конвейер, включая транзакционность и fuzzy-resolution,
приложим к 16% датасета. Остальное пишется поштучно.

**Рекомендация.** Либо расширить реестр (хотя бы `type = "manual"` записями для
Hirify/LinkedIn/WTTJ/WWR), либо явно зафиксировать в `data/inbox/README.md`, что
inbox-контракт — Himalayas-only by design.

### M10. Незаполненные и мёртвые поля

| Поле | Пусто | Комментарий |
|---|---:|---|
| `contact_name` | 214 / 214 | не использовано ни разу |
| `contact_url` | 214 / 214 | не использовано ни разу |
| `match_score` | 149 / 214 | участвует в сортировке `todo` и `action_now` |
| `salary` = `Unknown` | 160 / 214 | `salary_too_low` при этом используется как reason |
| `stack` | 56 / 214 | |

`match_score` особенно заметен: `score_priority` (`scripts/jobs.py:2649`) при пустом
значении возвращает `0.0`, поэтому 70% записей в очереди приоритезируются одинаково.

**Рекомендация.** Удалить `contact_name`/`contact_url` из схемы (с обновлением
`data/schema.md` и `scripts/jobs.py` в одном коммите, как требует `AGENTS.md`) или
начать их заполнять. Для `match_score` — сделать обязательным при переходе в
`reviewing`.

### M11. Недельные отчёты не ведутся

`AGENTS.md` («Файлы») и `templates/weekly-review.md` предполагают
`reports/weekly/YYYY-Wxx.md`; команда `jobs.py report` готова. Фактически в
`reports/weekly/` только `README.md`. За 6 недель истории (263 коммита) — ни одного
отчёта.

### M12. Одноразовые миграции живут в основном CLI

`migrate-v2` (`scripts/jobs.py:645-656`) и `repair-himalayas-screening`
(`scripts/jobs.py:659-760`) — завершённые одноразовые операции. Вторая тащит
23 строки захардкоженных job ID и ожидаемых значений (`scripts/jobs.py:159-181`) и
падает с `die`, если ожидаемые записи изменились. Плюс `V1_FIELDS`,
`V1_LEGACY_FIELDS`, `V1_STATUS_MAPPING`, `migrate_v1_rows`, `migration_summary` —
около 120 строк мёртвого кода в файле на 3100 строк, плюс тесты на них.

**Рекомендация.** Удалить после подтверждения, что миграции применены (сейчас
`repair-himalayas-screening --check` вернёт `already_applied`).

---

## Низкие

**L1.** `AGENTS.md:123` даёт пример `next_action="follow up"`, а секция `Follow-ups`
в `todo_sections` (`scripts/jobs.py:2689`) ищет подстроку `follow-up` через дефис.
Запись, созданная по примеру из документации, в секцию не попадёт. В данных
используется правильная форма — то есть неверен именно пример.

**L2.** `docs/roadmap.md:13` всё ещё упоминает «review/direct delivery modes».
Режим review PR удалён коммитами `f9909ec` и `995ea35`; `docs/agent-operations.md:100`
и `docs/current-architecture.md:70` уже обновлены, roadmap — нет.

**L3.** Расхождение примеров `--cv-version` между `README.md` и
`docs/jobs-cli.md:269` (см. M2).

**L4.** `data/schema.md` противоречит сам себе: строка 6 — «Все значения в CSV
пишутся на английском», строка 31 — «Компания и роль — как в первоисточнике».
В данных есть `Разработчик интерфейсов (Игры)` (`job-0194`),
`Junior Frontend-разработчик (React)` (`job-0192`), `Т-Банк`, `Яндекс MultiTrack`.
Нужно выбрать одно правило.

**L5.** `norm_url` (`scripts/jobs.py:373`) вырезает query-параметры `ref`,
`referrer`, `source` и `utm_*`. Для ATS, где вакансия идентифицируется через
`?source=`, это склеит разные URL в один и даст ложный дубль. Сейчас затронутых
URL в данных 0 — риск латентный.

**L6.** `--format json` поддерживают не все команды: `backfill-sources`,
`migrate-v2` и `report` его не имеют, хотя `AGENTS.md:97` предписывает «для
машинного чтения использовать `--format json`». `docs/jobs-cli.md:72-73`
перечисляет набор корректно, так что это ограничение CLI, а не ошибка документации.

**L7.** `python3 -m unittest discover -s tests` работает только без `-t`:
в `tests/` нет `__init__.py`, поэтому `discover -s tests -t .` падает с
`ImportError: Start directory is not importable`. CI использует рабочую форму,
но любой, кто добавит `-t`, получит непонятную ошибку.

**L8.** Пагинация в `collect_records` (`scripts/import_himalayas.py:304-331`) — это
`while True`, ограниченный только `has_next_page` по `totalCount/limit`.
Ограничения на число страниц нет; при аномальном ответе API (большой `totalCount`,
пустой `jobs`) цикл сделает `totalCount/limit` запросов. Есть `timeout-minutes: 15`
в workflow, но не в самом адаптере.

---

## Что сделано хорошо (чтобы не сломать при исправлениях)

- `apply_dataset_transaction` (`scripts/jobs.py:1475-1520`) — честная транзакция с
  backup, rollback и post-commit валидацией, плюс инъекция сбоя через
  `JOBS_INGEST_FAIL_AFTER_REPLACE` для тестов. Это лучший кусок кода в проекте.
- Разделение `application_status` / `listing_status` / `first_party_verified` /
  `apply_verified` — модель, которая честно отличает «мы не проверяли» от «закрыто».
- `render_tracker_markdown` экранирует все canonical-значения
  (`markdown_escape`, `markdown_url`) — generated view не инъектируется данными.
- Connector-шлюз: optimistic locking через `expected`, изолированный
  workspace для batch, allowlist изменённых путей в workflow, immutable результаты.
- Разделение времени: `Europe/Belgrade` для календарных полей, UTC для audit —
  вынесено в `tracker_time.py` и покрыто тестами.
- 110 тестов, включая boundary-тесты документации (`tests/test_documentation.py`).

---

## Предлагаемый порядок работ

| # | Задача | Почему сначала |
|---:|---|---|
| ~~1~~ | ~~C1 — вывести ghost-эвристику из `--strict`~~ | ✅ сделано |
| ~~2~~ | ~~C2 — закрыть дыру validation + пример в `jobs-cli.md`~~ | ✅ сделано |
| ~~3~~ | ~~H1 — защитить lifecycle-поля в `set`~~ | ✅ сделано |
| ~~4~~ | ~~H4, H3 — синхронизация карточек и маска legacy-файлов~~ | ✅ сделано |
| ~~5~~ | ~~M2 — `cv_version`~~ | ✅ сделано |
| ~~6~~ | ~~M1 (queue) + M6 — verification-долг и 22 пары дублей~~ | ✅ M1 сделано (код); M6 требует ручного разбора пар |
| ~~7~~ | ~~H2, H5 — транзакционность `add`/`set`, импорты~~ | ✅ сделано |
| 8 | M8–M12, L1–L8 | гигиена |

Пункты 1–4 — это изменения в `scripts/jobs.py` плюс тесты; они закрывают всё, что
может сломать автоматику. Остальное — данные и документация.

---

## Исправления 2026-08-16

Закрыты C1 и C2. Canonical данные (`data/jobs.csv`, `data/job_sources.csv`,
`docs/tracker.md`, карточки) не менялись — правки только в коде, тестах и
документации.

### C1 — ghost-эвристика выведена из блокирующего gate

Добавлена `temporal_notices()` (`scripts/jobs.py`), и подсказка о ghosting
перенесена туда из `validate_rows`. Введено три уровня вместо двух:

| Уровень | Зависит от | Блокирует |
|---|---|---|
| `errors` | содержимого строки | всегда |
| `warnings` | содержимого строки | при `--strict` |
| `notices` | текущей даты | никогда |

`cmd_validate` печатает заметки как `note:` и отдаёт их отдельным полем
`notices` в JSON. Код возврата и `ok` от них не зависят.

Проверено на копии датасета со сдвигом `applied_at` на 60 дней назад: 24 заметки,
`ok=true`, `EXIT=0`. До правки это была бы остановка `validate.yml`,
`agent-operations.yml` и всех write-команд.

Видимость сигнала не потеряна: он остался ровно там, где был, но перестал быть
gate. Решение о переводе в `ghosted` по-прежнему принимает человек через `status`.

### C2 — состояние стало невыразимым, а не только неотображаемым

Выбран вариант «закрыть дыру в validation» вместо fallback-а в `tracker_section`:
молчаливо отправлять активную вакансию в архив хуже, чем отказать в записи.
Теперь `ensure_dataset_valid` отклоняет операцию **до** записи в CSV, а не после.

Два новых инварианта (`scripts/jobs.py`, `data/schema.md`):

1. `decision_reason` несовместим с `application_status ∈ {reviewing, apply}` —
   закрывает вариант через `no_response_timeout`/`withdrawn_by_me`, который
   старое правило `PRE_APPLICATION_REASONS` не покрывало;
2. `listing_status=closed` до отклика требует `application_status=not_started`
   и `decision_reason=closed_before_application` — раньше правило проверяло
   только `not_started`.

Ни одна из 214 существующих записей ни одному из правил не противоречит.

Легитимные пути не затронуты, проверено вручную: `screen`, `verify` с
`closed_before_application`, `status`, а также connector-операция
`set listing_status=closed` для отправленной заявки (`risk=low`,
`status=completed`) — она разрешена только при post-application статусе
(`scripts/agent_operations.py`), поэтому под новое правило не попадает.

Пример в `docs/jobs-cli.md`, который воспроизводил дефект, заменён на безопасный
`set next_action=...` плюс отдельный блок с правильным способом зафиксировать
закрытие через `verify`.

### Тесты

Добавлено 4 теста (110 → 114, весь набор зелёный):

- `test_ghost_heuristic_is_a_notice_and_never_fails_strict_validation`;
- `test_closed_listing_is_rejected_while_the_application_is_in_progress`;
- `test_decision_reason_is_rejected_while_the_application_is_in_progress`;
- `TrackerSectionTotalityTests.test_every_validated_row_lands_in_exactly_one_section` —
  постоянная защита инварианта: перебирает все сочетания
  `application_status × listing_status × decision_reason × first_party × apply_verified`
  на пяти формах строки, оставляет прошедшие validation и требует, чтобы каждая
  попадала в секцию. Сейчас 6149 валидных форм, 0 неклассифицируемых.

Тест тотальности проверен на способность ловить регрессию: с откаченными
правилами он падает на `application_status='reviewing',
decision_reason='no_response_timeout'`.

### Осталось открытым

H-уровня больше нет. Следующий по приоритету — **M2** (`cv_version`).

---

## H3 + H4 — карточки найдены и синхронизируются даже после провала

Обе проблемы делились одной причиной — способ, которым код узнаёт «эта
вакансия уже уже имеет карточку» — поэтому исправлены вместе.

### H3 — маска в `tracker_application_cards`

`tracker_application_cards` (`scripts/jobs.py`) теперь ищет и `job-NNNN.md`,
и `job-NNNN-*.md`, объединяя оба совпадения перед проверкой на
неоднозначность — запрет «больше одного файла» не ослаблен.

Отдельным коммитом переименованы/слиты все 9 legacy-карточек в канонический
формат `job-NNNN-<slug(company)>-<slug(role)>.md` (front matter дополнен
недостающими полями `verified_at`/`listing_status`/`first_party_verified`/
`apply_verified` через существующую `sync_application_card_front_matter` —
тело карточки не менялось): `job-0022`, `job-0023`, `job-0024`, `job-0025`,
`job-0026`, `job-0032`, `job-0051`, `job-0052`.

`job-0055` был особым случаем: канонический путь уже существовал как
пустая авто-сгенерированная заглушка (ровно то, что описывает H4 ниже — более
ранний `status`/`verify` вызов не нашёл `job-0055.md` под старым именем и
создал новый файл из шаблона). Содержимое настоящей карточки перенесено из
`job-0055.md` в канонический файл, front matter синхронизирован, дубликат
удалён.

`docs/tracker.md` перегенерирован: `job-0026`, `job-0032`, `job-0051`,
`job-0052`, `job-0055` теперь показывают реальную ссылку на карточку вместо
`—`.

### H4 — sync front matter не зависит от `passed`

Добавлен `application_card_path(row)` — общий расчёт канонического пути,
вынесенный из `render_application_card`. `prepare_verified_application_write`
переписан: сперва проверяется, существует ли уже карточка по этому пути;
если да — front matter синхронизируется всегда, независимо от `passed`; если
нет — новая карточка по-прежнему создаётся только при `passed=True` и
`application_status ∈ {reviewing, apply}`. `application_card_created`
считается по факту существования карточки до вызова, а не по гонке с ещё не
выполненной записью на диск.

Карточка `applications/job-0150-undisclosed-web-developer.md`, которую нашёл
аудит с расхождением front matter, отдельно синхронизирована с
`data/jobs.csv` вручную (тем же `sync_application_card_front_matter`, что
использует код) — `original_url`, `verified_at=2026-08-13`,
`listing_status=closed`, `first_party_verified=yes`, `apply_verified=no`.
Данные `jobs.csv` не менялись, только сама карточка.

### Тесты

- `test_render_tracker_finds_legacy_dashless_card_names` — `job-NNNN.md` без
  дефиса теперь отображается в `docs/tracker.md`;
- `test_verify_syncs_an_existing_card_even_when_verification_fails` —
  существующая карточка синхронизируется при `--decision-reason
  closed_before_application` (verification failed, `outcome=blocked`), новая
  карточка при этом не создаётся (`application_card_created=false`).

115 → 117 тестов, весь набор зелёный; `validate --strict` и
`render-tracker --check` — чисто.

---

## H2 + H5 — транзакционность и package import

### H2 — `persist_add` и `set_job` переведены на общий write-path

`persist_add` больше не пишет карточку через собственный `mkstemp`/`os.replace`
и `jobs.csv`/`job_sources.csv` двумя независимыми `save()`; вместо этого он
собирает `application_writes` (как это уже делают `status_job`/`verify_job`)
и передаёт всё как один `apply_dataset_transaction(plan.rows, plan.source_rows,
application_writes)`. `set_job` аналогично заменил голый `save(rows)` на
`apply_dataset_transaction(rows, source_rows)`.

Обе команды получили бесплатно то, что уже было у `verify`/`status`/`screen`/
`ingest`: файловую блокировку (`dataset_write_lock`), backup каждого
заменяемого файла, атомарный откат всех файлов при сбое посреди замены и
post-commit re-validation. Своего кода для отката `persist_add` больше не
пишет — блок `except BaseException: ... unlink` удалён целиком, эту работу
теперь делает `apply_dataset_transaction`.

Проверено инъекцией `JOBS_INGEST_FAIL_AFTER_REPLACE` (тот же механизм, что
`tests/test_ingest.py` уже использует для `ingest`):

```
$ JOBS_INGEST_FAIL_AFTER_REPLACE=1 python3 scripts/jobs.py add \
    --company AtomicCo --role "Frontend Developer" --source Manual \
    --source-url https://careers.example.test/atomic
error: ingest transaction отклонена... injected ingest replacement failure
$ python3 scripts/jobs.py validate --strict   # jobs.csv и job_sources.csv не изменены
```

До правки `JOBS_INGEST_FAIL_AFTER_REPLACE` на `add`/`set` вообще не действовал
(`save()`/`save_job_sources()` не читают эту переменную) — сбой между двумя
файлами прошёл бы тихо, оставив `jobs.csv` с вакансией без provenance-строки,
ровно как описано в исходной находке.

### H5 — одинаковый guarded import в трёх местах

`scripts/jobs.py` (`plan_ingest`), `scripts/ingestion.py` и `scripts/inbox.py`
теперь оборачивают свой единственный внутрипроектный импорт (`ingestion`,
`inbox`, `source_config` соответственно) в тот же `try/except
ModuleNotFoundError`, что уже был у `tracker_time` в `scripts/jobs.py:20-23`.

Репродукция из аудита теперь проходит:

```
$ python3 -c "import sys; sys.path.insert(0,'.'); from scripts import jobs; \
    jobs.plan_ingest('tests/fixtures/inbox/himalayas-small.jsonl')"
OK <class 'scripts.jobs.IngestPlan'>
```

### Тесты

- `test_add_is_atomic_across_csv_source_and_card_when_replacement_fails_midway`
  и `test_set_goes_through_the_locked_transactional_write_path` — оба
  проверены на способность ловить регрессию: без правки `set_job` они падают с
  `0 != 1`, потому что `save()` тогда игнорировал
  `JOBS_INGEST_FAIL_AFTER_REPLACE` и запись проходила как ни в чём не бывало;
- `test_plan_ingest_works_when_jobs_is_imported_as_a_package`
  (`PackageImportTests`) — прямой вызов `jobs.plan_ingest` при импорте модуля
  как `scripts.jobs`, ровно репродукция из H5.

118 → 120 тестов, весь набор зелёный; `validate --strict` и
`render-tracker --check` — чисто.

---

## H1 — `set` больше не может выставить lifecycle-поля

`SET_PROTECTED` (`scripts/jobs.py:99`) расширен: `application_status`,
`applied_at`, `response_at` и `decision_reason` теперь защищены наравне с
`id`/`stage_reached`/`verified_at`/`last_update`. `set field=value` с любым из
них теперь отклоняется тем же сообщением, что и раньше для `stage_reached`:
«поле … управляется скриптом и не меняется через field=value».

Единственный легитимный путь к этим полям — `status` (человеческое
подтверждение lifecycle-события) — использует ту же функцию
`apply_job_changes`, что и `set`. Чтобы не заблокировать сам себя, у
`apply_job_changes` появился параметр `enforce_protected` (по умолчанию
`True`); `apply_status_change` — единственный вызывающий, который передаёт
`enforce_protected=False`, потому что к этому моменту он уже прогнал все
проверки `status` (запрет отката из post-application, обязательный
`--cv-version` и т. д.). `set_job` (обычный CLI `set`) вызывает
`apply_job_changes` с защитой по умолчанию.

`screen_job`/`verify_job`/`add` этих полей не касаются — они пишут их
напрямую в строку, минуя `apply_job_changes`, и не затронуты изменением.

Проверено:

```
$ python3 scripts/jobs.py set job-0169 application_status=applied
error: поле application_status управляется скриптом и не меняется через field=value
$ python3 scripts/jobs.py status job-0169 --application-status applied
job-0169  application_status=applied  ...
```

### Тесты

Добавлен `test_set_cannot_bypass_the_human_confirmed_applied_gate`
(`tests/test_jobs.py`) — перебирает все четыре защищённых поля через `set` и
проверяет отказ без записи в CSV.

Пять существующих тестов, которые использовали `set application_status=…`
как обходной путь для быстрого перевода записи в нужное состояние
(`test_set_advances_lifecycle_and_cannot_lower_stage`,
`test_listing_can_close_after_application_without_changing_application_history`,
`test_screen_rejects_a_job_after_application_without_writing`,
`test_verify_can_close_listing_after_application_without_rewriting_history`,
`test_missing_cv_version_is_reported_without_validation_warning`,
плюс аналогичные в `test_agent_operations.py` и todo/stats-тесты), переписаны
на `status --application-status …`. `test_closed_listing_is_rejected_…` и
`test_decision_reason_is_rejected_…` (инварианты C2) тоже использовали
`set application_status=reviewing`/`set decision_reason=…` для построения
состояния — первый переписан на `status --application-status reviewing`
(поле не относится к защищаемым lifecycle-полям приложения после отклика,
переход `not_started → reviewing` — обычное pre-application действие);
второй — на `add --application-status reviewing --decision-reason
geo_restriction`, потому что после закрытия H1 ни один сценарный путь, кроме
`add`, не даёт независимо выставить `decision_reason` при активном
`application_status` (`status` ограничивает reason только `ghosted`/
`withdrawn`, `screen` и `verify` сами приводят запись к `not_started` при
непустом `decision_reason`) — инвариант C2 по-прежнему достижим и проверяется
через `add`.

---

## M1 — `verification_queue` видит долг любого статуса

Условие в `todo_sections` (`scripts/jobs.py`) требовало
`application_status == "not_started"` для попадания в `verification_queue`.
Это и было дырой видимости: 22 активные записи с непройденной проверкой
(`applied`, `reviewing`) существовали в данных, но ни разу не показывались
агенту в ежедневной очереди — только в `stale`, у которого нет отдельной
секции в `todo`.

Условие сужено до того, что реально имелось в виду — активная запись
(`is_active_candidate`, то есть не terminal-статус, не закрытый листинг, без
`decision_reason`) без полной верификации:

```python
if (
    is_active_candidate(row)
    and (row["first_party_verified"] != "yes" or row["apply_verified"] != "yes")
):
    sections["verification_queue"].append(todo_item(row, action_date or row["last_update"]))
```

Статус `not_started` был частным случаем `is_active_candidate`, поэтому
существующее поведение для него не изменилось; добавились `reviewing` и
`applied`/`interviewing`/`offer` без полной верификации. Terminal-статусы
(`rejected`, `ghosted`, `withdrawn`) по-прежнему исключены — это не регрессия,
а сохранённая граница `is_active_candidate`.

Проверено на реальном датасете: `verification_queue` теперь содержит ровно
22 записи, статусы `applied`/`reviewing` — то же число, что аудит насчитал
вручную для M1. `validate --strict` и `render-tracker --check` не тронуты,
canonical-данные не менялись.

**Не закрыто.** Это фикс видимости в инструменте, а не самого долга: 22
записи по-прежнему требуют реальной first-party проверки первоисточника
человеком (или агентом через `verify`) — код не может это сделать за них.
`M6` (22 пары-кандидата в `dupes`) отдельно не тронут: он требует такого же
ручного разбора, а не изменения кода.

### Тесты

`test_verification_queue_covers_active_records_of_any_status_not_only_not_started`
(`tests/test_jobs.py`) — три записи: `applied` без верификации (должна
попасть в очередь), `applied` с полной верификацией (не должна), `rejected`
без верификации (не должна — terminal-статус). Без правки первая проверка
падает, потому что старое условие требовало `not_started`.

121 тест, весь набор зелёный.

---

## M2 — `cv_version` нормализован до 100% покрытия

Три отдельных действия, все через штатный write-path (`set`), без ручной
правки CSV:

1. **Пример в `README.md:47`** (`--cv-version cv-frontend-2026-08`) заменён на
   `--cv-version frontend-2026-08` — это и был источник ошибки: пример
   противоречил и собственному контракту `cv/current/README.md` («slug из
   третьей колонки, не имя файла»), и корректному примеру в
   `docs/jobs-cli.md:269`.
2. **6 записей с `cv_version=cv-frontend-2026-08`** (`job-0001`, `job-0054`,
   `job-0055`, `job-0142`, `job-0143`, `job-0147`) приведены к
   `frontend-2026-08` командой `set <id> cv_version=frontend-2026-08` —
   единственный существующий файл резюме один, слаг для него однозначен по
   `cv/current/README.md`, так что это исправление формата, а не
   предположение о факте.
3. **21 запись с `applied_at`, но без `cv_version`** — это была граница,
   которую нельзя закрыть кодом: какая версия резюме реально ушла по каждой
   заявке, в репозитории не записано нигде. Уточнено у пользователя:
   - 18 из 21 — frontend-роли, подтверждено, что все использовали
     единственную существующую версию `frontend-2026-08`;
   - 3 Storyteller-заявки (`job-0051`, `job-0052`, `job-0053`) — Ops-роли,
     не frontend, с `cover_letter=yes` (кастомные сопроводительные), поэтому
     не предполагались по умолчанию — отдельно подтверждено, что тоже
     `frontend-2026-08`.
   Все 21 проставлены той же командой `set`.

Итог: `verified.strict` — 0 ошибок/предупреждений; из 27 заявок с
`applied_at` все 27 (100%, было 6 = 22%) имеют корректный `cv_version`.
Аналитика `cv_versions` в `stats_payload` (`scripts/jobs.py:2757-2761`)
теперь строится на полной выборке вместо 22%. `render-tracker` перегенерирован
и проверен `--check`. Canonical-данные менялись только через `set`, каждая
запись — отдельным вызовом с post-write валидацией.

**Не тронуто.** `cv/current/README.md` не редактировался — таблица там уже
верна, ошибка была только в примере `README.md` верхнего уровня. Опциональная
часть рекомендации M2 («валидировать `cv_version` по `cv/current/README.md`»)
не сделана: это добавило бы чтение файловой системы в `validate_rows`, которая
сейчас — чистая функция от строк CSV; решил не делать эту архитектурную
правку без отдельного запроса.

### Тесты

Отдельных тестов не добавлено — `set field=value` для произвольного
незащищённого поля уже покрыт существующими тестами `set`
(`cv_version` не входит в `SET_PROTECTED`), а сама нормализация — правка
данных, а не кода.

121 тест, весь набор зелёный (без изменений — тестов не добавлялось).

---

## M3 — `cover_letter`: валидация + честные значения

`validate_rows` (`scripts/jobs.py`) получил проверку: непустое `cover_letter`
должно быть либо `no`, либо содержать `/` (то есть выглядеть путём). Ловит
ровно паттерн бага — bare-слово вроде `yes`, не являющееся ни `no`, ни путём.

Для трёх записей с `yes` (`job-0051`, `job-0052`, `job-0053`, все Storyteller)
проверено у пользователя: `yes` не был опечаткой — cover letter реально
отправлялся по всем трём, но текст/файл нигде не сохранён, восстановить
нечем. Записать путь было бы выдумыванием факта (в `cv/cover-letters/` нет и
не было файлов под эти вакансии — там только Ciklum, GetBlock, GoDaddy,
Horizon Trading Solutions, TripleTen). Решение: `cover_letter=no` (честное
значение по схеме — "нет сохранённого пути", не "письма не было") плюс
уточнение в `notes` каждой записи, что письмо отправлялось, но не
заархивировано. Правки — через `set <id> cover_letter=no notes=...` одним
вызовом на запись, `validate --strict` и `render-tracker --check` чистые.

### Тесты

`test_cover_letter_must_be_no_or_a_path` (`tests/test_jobs.py`) — `set
cover_letter=yes` отклоняется без записи; `no` и путь вида
`cv/cover-letters/job-0001-....md` проходят.

121 → 122 теста, весь набор зелёный.

---

## M4 — 21 заглушка сделаны уникальными

Настоящий работодатель по всем 21 записям (14 `Undisclosed`/Hirify, 3
`FetchJobs.co`/LinkedIn, 3 `Hire Feed`/LinkedIn, 1 `getmatch`) неизвестен без
открытия первоисточника — открывать 21 ссылку ради этого фикса не стали
(решение пользователя: заглушка сейчас, полноценная first-party проверка —
отдельная работа, частично уже видна в `verification_queue` после M1).

Каждая запись получила уникальный суффикс с внешним ID из `source_url`, по
формату из собственной рекомендации аудита: `<имя-агрегатора> (<источник>-<id>)`,
например `Undisclosed (hirify-652587)`, `FetchJobs.co (linkedin-4451398325)`,
`getmatch (getmatch-22455)`. Одна запись (`job-0129`) не имеет числового ID в
`source_url` (`hirify.me/frontend-dev-jobs`) — для неё суффикс `hirify-job-0129`
(собственный id вакансии, а не выдуманный внешний). Правки — 21 отдельный вызов
`set <id> company=...` через штатный write-path.

**Подводный камень, не упомянутый в исходной рекомендации.** У пяти записей
(`job-0128`, `job-0129`, `job-0150`, `job-0169`, `job-0170`) уже были карточки
в `applications/`. `application_card_path()` (`scripts/jobs.py:1038`) вычисляет
путь из `slug(company)` **на лету** при каждом вызове — смена `company` только
в CSV без переименования файла оставила бы карточку по старому пути
(`job-0128-undisclosed-frontend-engineer-payments.md`), а
`prepare_verified_application_write` (`scripts/jobs.py:2104`) на следующем
`verify`/`status` не нашёл бы её по новому вычисляемому пути и **молча ничего
не сделал бы** (`card_exists=False`, статус пост-application → ни sync, ни
создание) — тот же класс проблемы, что H3/H4, только созданный этим самым
фиксом. Поймано до коммита, не по факту поломки.

Исправлено вместе с переименованием `company`: все 5 карточек переименованы
(`git mv`) под новый канонический путь, front matter пересинхронизирован тем
же `sync_application_card_front_matter`, которым пользуется код (не руками) —
поле `company` в каждой карточке теперь совпадает с `jobs.csv`.
`tracker_application_cards` их видит по-прежнему (маска `job-NNNN-*.md`,
закрыта H3, не зависит от суффикса).

Побочный эффект — уменьшение `dupes`: было 22 пары-кандидата, стало 8. 14 пар
были порождены исключительно совпадением `company="Undisclosed"`/`"FetchJobs.co"`/
`"Hire Feed"` — с уникальными суффиксами они больше не совпадают. Оставшиеся
8 — предмет M6 (ручной разбор), не тронуты.

Проверено: `validate --strict` — 0/0, `render-tracker --check` — актуален,
122 теста зелёные.

### Тесты

Отдельных тестов не добавлено — правка данных и переименование файлов, не
кода; существующие тесты `render-tracker`/`tracker_application_cards`
(маска `job-NNNN-*.md`) уже покрывают то, что новые суффиксы в имени файла не
ломают обнаружение карточки.

122 теста, весь набор зелёный (без изменений — тестов не добавлялось).

114 → 115 тестов, весь набор зелёный.
