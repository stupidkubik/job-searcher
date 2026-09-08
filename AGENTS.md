# Правила работы с этим репозиторием

Это личный трекер поиска работы. Единственный структурированный источник истины —
`data/jobs.csv`. Схема и допустимые значения: `data/schema.md`. Профиль кандидата:
`config/profile.md`.

## Перед любым поиском вакансий

1. Прочитать `config/profile-digest.md` (компактный профиль: гео, уровень,
   стек, минимальная компенсация, work authorization, красные флаги).
2. Прочитать `data/index/known.tsv` (id, company, role и статусы каждой
   записи — для проверки «эта вакансия уже разбиралась»).
3. Прочитать `data/index/keys.tsv` (source → source_job_id/URL по
   источникам — для дедупа по provenance).
4. Прочитать `data/index/active.csv` (полный срез активных записей).
5. Прочитать `docs/sources/README.md` — точка входа в playbook'и
   источников; если для запрошенного источника есть отдельный playbook,
   прочитать и его.
6. Для browser-assisted поиска выполнить Browser preflight ниже.
7. Только потом искать новое.

Полные `data/jobs.csv`, `data/job_sources.csv` и `config/profile.md` читать
только по явной необходимости — когда индексов и дайджеста не хватает для
конкретного решения — и объяснить эту необходимость в отчёте об операции, а
не читать их как стандартный шаг бутстрапа.

Не анализировать заново вакансию, которая уже есть в CSV. Если её
`application_status=applied` / `rejected` — не откликаться повторно; для
вычисляемого `Skipped` сначала прочитать `decision_reason`; запись с
`listing_status=closed` без отклика пропустить; `not_started` / `reviewing` /
`apply` продолжать с предыдущего шага.

### ChatGPT web: Browser preflight

- GitHub plugin/connector и Browser — разные capabilities. GitHub connector
  читает репозиторий и создаёт разрешённые immutable requests, но не считается
  браузером для source discovery или first-party verification. Сам факт, что
  ChatGPT открыт пользователем в обычной вкладке браузера, также не даёт агенту
  управление этой вкладкой.
- Для browser-assisted маршрута явно использовать установленный `Browser`
  plugin в том же ChatGPT-чате и до поиска открыть requested source URL именно
  через Browser. Успешный preflight означает, что URL загрузился как
  интерактивная rendered page; отдельно фиксировать blocked, auth required,
  CAPTCHA и load error.
- Web search, search snippets, `Crawled:` metadata и cached/indexed results
  разрешены только как discovery evidence. Они не подтверждают текущую выдачу,
  exact vacancy, first-party status или работоспособность Apply route.
- Если Browser tool отсутствует или requested page не открывается, остановить
  browser pass, назвать точное ограничение и не подменять его web search.
  Продолжить можно только через явно разрешённый source adapter/API либо после
  нового Browser-enabled запуска.

## Контракт полей

До сборки любого `add`/`verify`/`set`/`screen`/`status`/`batch` request
прочитать [`data/operations/contract.md`](data/operations/contract.md) —
сгенерированную таблицу «команда × поле» с допустимыми значениями и
инвариантами между полями. Это единственный источник истины по тому, какая
команда какое поле принимает: он собирается из кода и не может разойтись с
runner'ом незаметно. Поле вне таблицы своей команды или значение вне enum'а
runner отклонит целиком запросом `rejected` — не пытаться угадать синтаксис
или добавить поле «на всякий случай». В частности, ни `add`, ни `verify`, ни
`set`, ни `screen` не принимают `next_action` или `verified_at` — оба
вычисляются runner'ом.

## Железные правила

- **Ни одна найденная вакансия не остаётся без записи.** Закрытая, не подходящая,
  слишком senior, с гео-ограничением — всё равно строка в CSV. Это защита от
  повторного анализа того же самого через неделю.
- **Агрегатор не определяет актуальность.** Перед полным анализом открыть
  первоисточник (careers page, Greenhouse, Lever, Ashby, Workable,
  SmartRecruiters, Teamtailor, BambooHR, Comeet). Закрыто в первоисточнике =
  закрыто, независимо от статуса на агрегаторе.
- **`Remote` сам по себе не значит global remote.** Проверять текст вакансии на
  ограничения по стране и work authorization. Не уверен → `remote_policy=Unclear`.
- **`application_status=applied` ставится только после фактической отправки
  заявки человеком.** Агент не отправляет отклики и не ставит `applied`
  самостоятельно.
- **Никогда не выдумывать факты о кандидате.** Метрики, должности, стек, срок
  опыта — только из `config/profile.md`. Нет доказательства → не писать.

## Как писать в CSV

- Только через `scripts/jobs.py` (`add` / `set` / `status` / `screen` /
  `verify` / `ingest` / `render-tracker` / `render-index`). Ручная правка
  canonical CSV — исключение. Разовые исторические миграции (`migrate-v2`,
  `repair-himalayas-screening`, `backfill-sources`) не входят в `jobs.py`: это
  отдельные скрипты в `scripts/maintenance/`, вне write-path агента.
- GitHub connector создаёт только immutable request в
  `data/operations/requests/`; trusted GitHub Actions runner применяет request
  через `scripts/agent_operations.py` и `jobs.py`. Каждый request создаётся
  непосредственно в `main`, где runner применяет его и коммитит audited result.
  Не создавать operation-ветки или PR для connector operations. Путь через PR
  не поддерживается технически: `validate.yml` отклоняет любой pull request,
  меняющий `data/operations/requests/**`, ещё до merge — так об этом узнают
  раньше, чем по невнятной ошибке раннера после. Не использовать
  GitHub file API для прямого
  изменения `data/jobs.csv` или `data/job_sources.csv`: он обходит write-path.
- Значения полей — по-английски и строго из enum в `data/schema.md`.
- `id` неизменяем после создания.
- `data/job_sources.csv` — provenance каждой вакансии. Для нового внешнего
  источника передавать `--source-url` или `--source-job-id`; без reference
  допустимы только `Manual` и `Referral`.
- Рабочие raw batches живут только локально в `data/inbox/*.jsonl`: они
  immutable, игнорируются Git и не редактируются ingest-ом. Их контракт — в
  `data/inbox/README.md`; до ingest проверять `python3 scripts/inbox.py validate`
  и начинать с `jobs.py ingest PATH --dry-run --format json`. Fuzzy candidate
  batch не применять: он требует явного resolution.
- Подтверждённый дубль создавать только через `add --duplicate-of job-NNNN`:
  команда добавляет source reference к canonical job и не создаёт новый ID.
  `--force` означает, что совпадающий URL — осознанно shared discovery page или
  похожая запись является отдельной вакансией.
- Никаких переводов строк в ячейках. Длинный текст → `applications/<id>.md`.
- Разделитель в `stack` — `; `, не запятая.
- `docs/tracker.md` — generated browser view; не редактировать его вручную.
  Это документ только для человека: агент его не читает и не включает в
  request.
- После canonical write сначала выполнить `python3 scripts/jobs.py validate
  --strict`, затем перегенерировать оба generated-представления:
  `render-tracker` и `render-index`, каждое со своим `--check`. Оба проверяются
  в `validate.yml`, поэтому устаревший `data/index/*` роняет CI так же, как
  устаревший `docs/tracker.md`. Trusted connector runner коммитит оба
  представления вместе с canonical result.

## Командный минимум для агента

Не угадывать синтаксис и допустимые поля: перед незнакомой операцией выполнить
`python3 scripts/jobs.py <command> --help`. Для машинного чтения использовать
`--format json`. Полная справка и примеры находятся в `docs/jobs-cli.md`.

Безопасные read-only команды для начала работы:

```bash
python3 scripts/jobs.py todo --format json
python3 scripts/jobs.py stale --days 7 --format json
python3 scripts/jobs.py stats --format json
python3 scripts/jobs.py dupes --format json
```

Основные write-команды в локальном checkout:

```bash
# Новая вакансия; для внешнего источника добавить --source-url/--source-job-id.
python3 scripts/jobs.py add --company "ExampleCo" --role "Frontend Developer" \
  --source "Company Careers" --source-url "https://careers.example.com/jobs/123" \
  --application-status not_started --format json

# Завершённую first-party проверку записывать одной атомарной операцией.
python3 scripts/jobs.py verify job-NNNN --listing-status open \
  --first-party-verified yes --apply-verified yes --original-url "..." \
  --format json

# Последующие изменения существующей записи задаются как field=value.
python3 scripts/jobs.py set job-NNNN next_action="follow-up" --format json

# Подтверждённое человеком lifecycle-событие.
python3 scripts/jobs.py status job-NNNN --application-status rejected --format json

# Screening blocker без утверждений о first-party verification.
python3 scripts/jobs.py screen job-NNNN \
  --decision-reason geo_restriction --notes "..." --format json
```

Для raw batch порядок всегда такой; первый ingest обязательно dry-run:

```bash
python3 scripts/inbox.py validate data/inbox/<batch>.jsonl
python3 scripts/jobs.py ingest data/inbox/<batch>.jsonl --dry-run --format json
# После проверки плана и явного resolution fuzzy-кандидатов:
python3 scripts/jobs.py ingest data/inbox/<batch>.jsonl \
  --resolutions data/inbox/<batch>.resolution.json --format json
```

После любой записи выполнить strict validation и просмотреть fuzzy-кандидатов:

```bash
python3 scripts/jobs.py validate --strict --format json
python3 scripts/jobs.py dupes --format json
python3 scripts/jobs.py render-tracker --check --format json
python3 scripts/jobs.py render-index --check --format json
```

`dupes` — отчёт для проверки, а не разрешение автоматически объединить строки.
Флаг `--fail` использовать в CI или когда dataset уже не содержит известных
fuzzy-кандидатов.

GitHub connector не исполняет эти shell-команды. Для него CLI выше описывает
ожидаемую семантику, а запись выполняется только созданием одного нового
immutable request по контракту `data/operations/README.md` непосредственно в
`main`. Разрешены `screen`,
`add`, `verify`, `status`, ограниченный `set` и `batch`. `batch.atomic=true`
допускает не более 10 операций и откатывает всё при первом же конфликте;
`batch.atomic=false` допускает до 100 и применяет всех детей, кроме реально
конфликтующих (`unresolved_duplicate` / `source_reference_conflict` /
`stale_operation`) — результат тогда `status=partial`. Любой отказ по схеме
(неизвестное поле, недопустимое значение) отклоняет весь batch в обоих
режимах. Каждый конфликтующий child и каждый конфликтующий одиночный `add`
несут готовый к отправке `retry`-фрагмент под новым `operation_id`.
`add` разрешён и как batch child со стабильным `client_ref`, а `job_id`
назначается runner-ом внутри общей транзакции; `ingest` не поддерживается.
`status` для `applied`, `interviewing`, `offer`,
`rejected`, `ghosted` и `withdrawn` допустим только после явного подтверждения
человеком (`confirmed_by_user=true`); агент не выводит эти события сам. Не
считать операцию завершённой, пока runner не создал соответствующий result и
canonical diff в `main`. Дождаться matching result и завершения workflow перед
отчётом об операции.

У результата ровно три возможных `status`: `completed`, `conflict` и
`rejected`. `rejected` — это не «упало без объяснения»: любой отказ по
контракту или внутренний invariant runner'а всегда даёт файл в
`data/operations/results/<operation_id>.json` с машиночитаемым `error.code` из
закрытого набора (см. `data/operations/README.md`); canonical данные при
`rejected` не меняются, но прогон workflow специально завершается красным —
чтобы отказ был виден и человеку, а не только агенту. Результат неизменяем
независимо от `status`: чтобы повторить отклонённую или конфликтную операцию,
исправить причину и отправить **новый** `operation_id`, никогда не
переписывать существующий request или результат.

## Порядок обработки одной вакансии

1. Проверить дубли: сначала `data/job_sources.csv` по `source + source_job_id`,
   затем `original_url`, source URL и company + role.
2. Открыть первоисточник, проверить доступность вакансии и работу кнопки Apply;
   записать `listing_status`, `first_party_verified`, `apply_verified` и дату
   проверки через CLI.
3. Если есть hard blocker (гео, work authorization, seniority), сразу выполнить
   `add --application-status not_started --decision-reason <причина> --no-file` и
   не проводить полный анализ. Для закрытого объявления использовать
   `--listing-status closed --decision-reason closed_before_application` вместо
   обычной причины отсева.
4. Если фильтр пройден, провести полный анализ, присвоить `match_score` от 1 до 10,
   поставить `application_status=reviewing` и заполнить `applications/<id>.md`.
5. Принять решение `apply` или вычисляемое `Skipped` / `Closed` через
   структурированные поля.
6. Подготовить материалы: CV только из `cv/current/`, cover letter и ответы формы.
7. Человек отправляет заявку; только после этого выполнить
   `status <id> --application-status applied --cv-version ...` или создать
   connector request `status` с `confirmed_by_user=true`.

## Файлы

| Задача | Файл |
|---|---|
| структурированные данные | `data/jobs.csv` |
| provenance источников | `data/job_sources.csv` |
| локальные raw результаты источников | `data/inbox/*.jsonl` (не коммитятся) |
| длинный контекст по вакансии | `applications/<id>.md` из `_TEMPLATE.md` |
| профиль, приоритеты, доказательства | `config/profile.md` |
| резюме для отправки | `cv/current/` — только оттуда |
| шаблоны сообщений | `templates/outreach.md` |
| недельный отчёт | `reports/weekly/YYYY-Wxx.md` |

Не создавать новые файлы в корне. Не менять схему CSV без обновления
`data/schema.md` и `scripts/jobs.py` в том же коммите.

## Коммиты

Одна логическая операция = один коммит. Формат:

```text
jobs: add job-0042 SomeCo Frontend Developer (Reviewing)
jobs: job-0031 -> Applied
report: week 2026-W32
```
