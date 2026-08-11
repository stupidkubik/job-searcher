# Agent operations: безопасный write-path через GitHub Actions

Дата: 2026-08-11
Статус: proposal для Tracker v2.1

## 1. Идея

AI-агент не изменяет canonical данные трекера напрямую. Вместо этого он формирует
декларативную операцию, описывающую намерение (`add`, `verify`, `set`, batch
resolution). GitHub Actions runner делает checkout репозитория, проверяет операцию
по allowlist/policy, исполняет её через `scripts/jobs.py`, запускает validation и
создаёт commit или PR.

```text
AI agent via connector
        │
        │ declarative job operation
        ▼
operations inbox
        │
        ▼
GitHub Actions runner (trusted checkout)
        │
        ├─ validate operation schema
        ├─ enforce policy / allowlist
        ├─ optimistic-lock checks
        ├─ scripts/jobs.py ...
        ├─ jobs.py validate --strict
        ├─ unit tests
        └─ optional dupes check
        ▼
commit / pull request
```

Главное архитектурное правило:

> **AI может записывать intent. Canonical state может изменять только tracker.**

Это сохраняет существующий принцип v2, где `scripts/jobs.py` является единым
write-path для `data/jobs.csv` и `data/job_sources.csv`.

## 2. Зачем это нужно

Connector умеет читать и записывать файлы GitHub, но прямое редактирование
`jobs.csv` нарушает правила трекера: обходятся validation, dedupe, side effects,
создание application card, provenance и другие invariants.

В то же время агенту полезно уметь завершать найденную работу без ручного переноса
каждого результата пользователем. Например, после разбора 30 вакансий агент уже
знает, какие записи закрыты, какие имеют geo blocker, а какие стоит перевести в
`reviewing`.

Operation layer закрывает этот разрыв:

- агент передаёт структурированное решение;
- runner не доверяет shell-командам или произвольным аргументам;
- tracker сам решает, какие canonical поля нужно изменить;
- существующие invariants остаются обязательными;
- каждое действие имеет audit trail.

## 3. Transport: operations inbox

Рекомендуемый transport:

```text
data/operations/pending/<operation-id>.json
```

Агент через GitHub connector имеет право создавать новые operation-файлы, но не
редактировать canonical данные.

GitHub Action запускается на появление нового файла в `pending/` или через
явный dispatch, который принимает только путь к уже существующему manifest.

Raw operation после принятия должна быть immutable. Для результата возможны два
варианта:

```text
data/operations/pending/<id>.json
        ↓
data/operations/completed/<id>.json
```

или immutable request + отдельный result:

```text
data/operations/requests/<id>.json
data/operations/results/<id>.json
```

Второй вариант предпочтительнее: он не изменяет исходный intent и даёт более
чистый audit trail.

Эти каталоги можно оставить tracked в Git, если объём невелик. Если операции
станут частыми и начнут создавать шум в истории, result можно хранить как Actions
artifact, а в Git сохранять только итоговый commit/PR metadata.

## 4. Operation должна быть данными, а не shell

Недопустимый контракт:

```json
{
  "command": "python scripts/jobs.py verify job-0122 --listing-status open ..."
}
```

Также нельзя передавать произвольный shell fragment или использовать `eval`.

Правильный контракт описывает доменное намерение:

```json
{
  "version": 1,
  "operation_id": "op-20260811-001",
  "command": "verify",
  "job_id": "job-0122",
  "args": {
    "listing_status": "open",
    "first_party_verified": "yes",
    "apply_verified": "yes",
    "original_url": "https://careers.example.com/jobs/frontend",
    "decision_reason": "geo_restriction"
  }
}
```

Runner читает `command`, проверяет schema и policy, а затем сам строит безопасный
вызов внутреннего API или CLI. Никакое значение из manifest не становится shell
кодом.

## 5. Разрешённые операции

Начальный allowlist:

```text
add
verify
set
batch
```

`ingest` лучше не разрешать как произвольную операцию по внешнему пути. Вместо
этого batch/ingest operation должна ссылаться только на известный immutable raw
batch внутри `data/inbox/`, проверять его hash и использовать существующий
resolution contract.

### `add`

Создание новой вакансии через тот же canonical write-path, что и ручной CLI.
Operation передаёт только поля, которые уже разрешены structured `add` input.

### `verify`

Главная операция для агентного workflow. Фиксирует завершённую first-party
проверку, listing/apply status и optional hard blocker.

### `set`

Должен иметь отдельный allowlist полей. Агент не получает право менять любое поле
только потому, что `jobs.py set` технически это умеет.

### `batch`

Контейнер из нескольких разрешённых операций, применяемых атомарно.

## 6. Risk policy

Runner, а не агент, определяет уровень риска операции.

### Low risk: разрешён auto-commit

Примеры:

```text
verify → closed_before_application
verify → geo_restriction
verify → work_authorization
verify → seniority_too_high
set next_action=...
set next_action_date=...
set listing_status=closed для уже applied записи
```

Эти действия в основном фиксируют наблюдаемое состояние и не утверждают, что
человек отправил заявку или прошёл этап найма.

### Medium risk: только через PR

Примеры:

```text
add new job
verify → reviewing
match_score / level / stack enrichment
explicit duplicate resolution
batch с несколькими mutable операциями
```

PR даёт человеку быстрый визуальный контроль diff без необходимости переносить
данные вручную.

### Human-only: runner обязан отвергать

Независимо от содержимого manifest агент не должен иметь возможности поставить:

```text
application_status=applied
application_status=interviewing
application_status=offer
application_status=withdrawn
applied_at
response_at
```

В первую очередь это касается `applied`: tracker уже использует принцип, что
фактическую отправку заявки подтверждает человек.

Поле вроде:

```json
{"requires_human_confirmation": false}
```

может быть metadata, но не источник policy. Уровень риска всегда вычисляется
runner'ом из command + args.

## 7. Optimistic locking

Между чтением вакансии агентом и исполнением operation состояние может измениться.
Например, агент увидел `not_started`, а пользователь уже успел отправить заявку.

Operation должна поддерживать preconditions:

```json
{
  "command": "verify",
  "job_id": "job-0122",
  "expected": {
    "application_status": "not_started",
    "last_update": "2026-08-11"
  },
  "args": {
    "listing_status": "closed",
    "first_party_verified": "yes",
    "apply_verified": "no",
    "decision_reason": "closed_before_application"
  }
}
```

До изменения runner сравнивает `expected` с checkout state. При несовпадении
операция завершается как stale/conflict и ничего не пишет.

Пример результата:

```json
{
  "status": "conflict",
  "reason": "stale_operation",
  "expected": {"application_status": "not_started"},
  "actual": {"application_status": "applied"}
}
```

Для надёжности можно также поддержать `expected_commit_sha`, но field-level
preconditions полезнее: unrelated commit не должен делать безопасную operation
невалидной.

## 8. Atomic batch operations

Batch особенно полезен для разбора источников: Himalayas, HiringCafe, Wellfound и
других выдач, где агент анализирует десятки вакансий за один проход.

Пример:

```json
{
  "version": 1,
  "operation_id": "himalayas-review-2026-08-11",
  "command": "batch",
  "atomic": true,
  "operations": [
    {
      "command": "verify",
      "job_id": "job-0099",
      "expected": {"application_status": "not_started"},
      "args": {
        "listing_status": "open",
        "first_party_verified": "yes",
        "apply_verified": "yes",
        "decision_reason": "geo_restriction"
      }
    },
    {
      "command": "verify",
      "job_id": "job-0102",
      "expected": {"application_status": "not_started"},
      "args": {
        "listing_status": "closed",
        "first_party_verified": "yes",
        "apply_verified": "no",
        "decision_reason": "closed_before_application"
      }
    }
  ]
}
```

Runner сначала должен полностью провалидировать manifest и все preconditions.
Только затем операции применяются в checkout.

После применения выполняется проверка dataset целиком. Если операция №17 или
финальный validation падает, commit/PR не создаётся. Рабочее дерево runner можно
просто отбросить вместе с failed job.

`atomic=false` на первом этапе лучше не поддерживать: partial success усложняет
audit и повторное исполнение.

## 9. Idempotency

`operation_id` должен быть уникальным.

Runner перед выполнением проверяет, что этот ID ещё не имеет successful result.
Повторный webhook/retry не должен второй раз применять одну и ту же операцию.

Для `add` и duplicate resolution дополнительно продолжают действовать штатные
idempotency/dedupe механизмы `jobs.py` и `job_sources.csv`.

Recommended result:

```json
{
  "version": 1,
  "operation_id": "op-20260811-001",
  "status": "completed",
  "executed_at": "2026-08-11T16:00:00Z",
  "commit_sha": "abc123",
  "pull_request": null,
  "result": {
    "job_id": "job-0122",
    "command": "verify"
  }
}
```

## 10. Runner workflow

Минимальный workflow:

```text
1. checkout exact base ref
2. setup Python 3.12
3. load operation JSON
4. validate operation schema/version
5. reject path traversal / unknown fields / unknown commands
6. classify risk
7. verify preconditions
8. dry-run/prepare full execution plan
9. execute through scripts/jobs.py or shared Python API
10. python scripts/jobs.py validate --strict
11. python -m unittest discover -s tests -v
12. python scripts/jobs.py dupes --fail (policy-dependent)
13. inspect changed-file allowlist
14. create commit or branch + PR according to risk
15. persist result metadata
```

Changed-file allowlist особенно полезен как последняя страховка. Job operation
должна иметь право изменить только ожидаемые tracker paths, например:

```text
data/jobs.csv
data/job_sources.csv
applications/**
```

и operation result metadata. Изменение `scripts/`, `.github/`, `config/` или
других executable/policy files должно автоматически останавливать job.

## 11. Security boundary

Action выполняет недоверенный manifest, поэтому нужно соблюдать несколько
правил:

- никогда не использовать `eval`, `bash -c <user input>` или shell interpolation;
- unknown command/arg/field = hard failure;
- job IDs валидировать как `job-NNNN`;
- URL передавать как данные, не выполнять и не fetch-ить внутри generic runner;
- input path разрешать только внутри заранее заданных каталогов;
- manifest не может задавать executable path;
- manifest не может менять risk class;
- GitHub token workflow получает минимальные permissions;
- для PR mode runner пишет только в выделенную branch namespace;
- canonical write происходит только после успешной policy validation.

Особенно важно разделять два типа автоматизации:

1. AI/connector создаёт operation request.
2. Trusted repository code интерпретирует request.

Изменение runner/policy code должно проходить обычный человеческий review и не
может быть частью той же agent operation, которую этот код затем исполнит.

## 12. Commit vs PR strategy

Рекомендуемая политика:

| Risk | Output |
|---|---|
| low | direct commit в `main` или отдельный auto-merge PR |
| medium | обычный PR |
| human-only | reject |

Для первого rollout безопаснее отправлять **все** успешные operations в PR.
После нескольких десятков проверенных операций low-risk subset можно перевести в
auto-commit.

Пример naming:

```text
agent/op-20260811-001
agent/himalayas-review-2026-08-11
```

Пример commit:

```text
jobs: apply agent operation op-20260811-001
```

PR body должен содержать machine-readable summary:

```text
Operation: op-20260811-001
Risk: medium
Commands: verify × 12, add × 2
Validation: passed
Tests: passed
Conflicts: 0
```

## 13. Возможный Python API

На первом этапе Action может безопасно строить `subprocess.run([...])` с массивом
аргументов без shell.

В долгосрочной перспективе лучше вынести operation executor внутрь Python:

```text
scripts/jobs.py          CLI adapter
scripts/operations.py    declarative operation parser + policy
scripts/job_store.py     shared canonical functions
```

Тогда CLI и GitHub Action используют один доменный API, а не вызывают друг друга
через текстовый интерфейс.

Это не обязательное условие первой реализации: текущий `jobs.py` уже достаточно
структурирован, чтобы сделать безопасный MVP вокруг его CLI.

## 14. MVP

Первую версию можно намеренно сделать маленькой.

### Phase A

- schema version `1`;
- только single operation;
- commands: `verify`, ограниченный `set`;
- только PR output;
- immutable operation request;
- optimistic locking;
- strict validation + tests;
- changed-file allowlist.

### Phase B

- `add`;
- atomic `batch`;
- operation result files;
- risk-based auto-commit для low-risk operations;
- richer PR summaries.

### Phase C

- declarative ingest/resolution operations;
- source-specific batch metadata;
- автоматическое связывание analysis run ↔ operation ↔ resulting commit;
- статистика по agent operations и conflicts.

## 15. Критерий успеха

Система работает правильно, если агент после поиска может сказать:

```text
verify job-0122 → geo_restriction
verify job-0124 → closed_before_application
add ExampleCo → reviewing
```

и безопасно передать эти решения в репозиторий, не зная формат CSV и не имея
возможности обойти tracker invariants.

При этом пользователь сохраняет контроль над действиями, которые отражают
реальные человеческие события: отправку заявки, интервью, оффер и withdrawal.

В результате Git-репозиторий становится не только хранилищем данных, но и
небольшим transactional API для job-search workflow, доступным любому будущему
агенту, importer или connector через единый декларативный контракт.
