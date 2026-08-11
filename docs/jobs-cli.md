# `jobs.py` CLI

`scripts/jobs.py` — единственный write path для canonical `data/jobs.csv`.
Ручной CLI, JSON-ввод и будущие importers используют одинаковые функции
построения записи, проверки дублей, validation и атомарной записи.

## Коды завершения

| Код | Значение |
|---:|---|
| `0` | Команда успешно выполнена. |
| `1` | Некорректный ввод или данные не проходят validation. |
| `2` | Обнаружен неразрешённый duplicate; нужен явный `--duplicate-of` или `--force`. |

## Добавление из CLI

```bash
python3 scripts/jobs.py add \
  --company "ExampleCo" --role "Frontend Developer" --source Manual \
  --application-status reviewing --listing-status open \
  --original-url "https://careers.example.com/jobs/frontend" \
  --first-party-verified yes --apply-verified yes
```

`--no-file`, `--force` и `--duplicate-of JOB_ID` — намеренные решения оператора;
они не принимаются через JSON. До Phase 3 `--duplicate-of` создаёт legacy row;
после появления source references изменится только это поведение.

## Structured input для `add`

Передать один JSON object можно файлом или stdin:

```bash
python3 scripts/jobs.py add --json tests/fixtures/job-input-valid.json --format json
printf '%s' '{"company":"ExampleCo","role":"Frontend Developer","source":"Manual"}' \
  | python3 scripts/jobs.py add --stdin --no-file --format json
```

`--json` и `--stdin` взаимоисключающие. Их нельзя смешивать с полями вакансии из
CLI, чтобы не было неявного merge. Управляющие флаги `--no-file`, `--force` и
`--duplicate-of` при structured input разрешены и остаются явными.

JSON должен быть UTF-8 object. Обязательные строковые поля:

```text
company, role, source
```

Допустимые необязательные поля:

```text
application_status, listing_status, first_party_verified, apply_verified,
level, remote_policy, original_url, source_url, location, stack, salary,
posted_at, found_at, match_score, decision_reason, notes
```

Все поля, кроме `match_score`, должны быть строками. `match_score` может быть
строкой или JSON number. Неизвестные поля отвергаются. В частности, importer не
может передать `id`, `last_update`, `verified_at`, `stage_reached`, `applied_at`
или любые другие canonical/derived поля: ID и timestamps назначает write path.

## Machine-readable output

`add`, `set`, `validate` и `dupes` поддерживают `--format text|json`; по
умолчанию — `text`. Успешный JSON-ответ состоит ровно из одного object с `ok`,
`command` и результатом команды. Например, `add` возвращает canonical `job`,
`warnings` и путь к созданной application card (или `null`).

```json
{"application_path":"applications/job-0099-exampleco-frontend-developer.md","command":"add","job":{"id":"job-0099"},"ok":true,"warnings":[]}
```

При `add --format json` неразрешённый duplicate также возвращается JSON object с
`ok=false`, `error="unresolved_duplicate"` и списком кандидатов, затем завершает
процесс с кодом `2`. Validation-ошибки завершаются кодом `1`.

## Примеры обновления и проверки

```bash
python3 scripts/jobs.py set job-0001 listing_status=closed --format json
python3 scripts/jobs.py validate --strict --format json
python3 scripts/jobs.py dupes --fail --format json
```
