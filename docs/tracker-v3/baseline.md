# Tracker v3 baseline

Дата: 2026-09-22

Timezone: Europe/Belgrade

Branch: `codex/tracker-v3`

Research checkpoint commit: `cb58753`
Base from `main`: `6a9d0cc`

Этот снимок зафиксирован до изменений production-кода v3. Он нужен для
сравнения correctness, объёма данных, времени тестов и веса bootstrap context.
Цифры не следует обновлять задним числом; следующий phase snapshot добавляется
отдельным разделом или новым датированным документом.

## Canonical dataset

| Метрика | Baseline |
|---|---:|
| jobs | 458 |
| source references | 474 |
| active candidates | 54 |
| applications in funnel | 45 |
| `applied` | 37 |
| `rejected` | 8 |
| `reviewing` | 16 |
| `apply` | 1 |
| `interviewing` | 0 |
| `offer` | 0 |
| recorded responses | 8 |
| response rate | 17.8% |
| fully verified active records | 18 |
| verification coverage | 33.3% |
| stale active records (7 days) | 53 |
| `not_started` | 396 / 86.5% |
| empty `original_url` rows | 308 |
| placeholder company rows | 30 |

Нулевые interview/offer stages — важный product signal, но не доказательство,
что таких событий никогда не было. Snapshot не хранит полную event history.

## Operation health

| Метрика | Baseline |
|---|---:|
| requests | 178 |
| results | 178 |
| requests without result | 0 |
| completed | 130 |
| conflict | 15 |
| rejected | 33 |

## Validation baseline

- `jobs.py validate --strict`: OK, 458 rows, 474 source references;
- tracker projection: fresh;
- bootstrap indexes: fresh;
- operation contract: fresh;
- duplicate report: returns review candidates but does not fail validation;
- full unit suite: 213 tests, 24.518 seconds test time, 24.74 seconds wall time;
- documentation suite: included in the full suite.

## Bootstrap weight

Read-only `ops_health.py` snapshot:

| File | Bytes |
|---|---:|
| `AGENTS.md` | 19,635 |
| `config/profile.md` | 12,765 |
| `data/jobs.csv` | 244,274 |
| `data/job_sources.csv` | 52,696 |
| `data/schema.md` | 16,824 |
| `data/operations/README.md` | 18,540 |
| total measured set | 364,734 |

V3 не должна заставлять агента читать полный event ledger, packet manifests или
match artifacts при обычном bootstrap. Для каждого нового canonical/auxiliary
слоя нужна компактная projection или targeted read path.

## Commands used

```bash
python3 scripts/jobs.py validate --strict --format json
python3 scripts/jobs.py stats --format json
python3 scripts/jobs.py dupes --format json
python3 scripts/jobs.py render-tracker --check --format json
python3 scripts/jobs.py render-index --check --format json
python3 scripts/agent_operations.py render-contract --check --format json
python3 scripts/maintenance/ops_health.py --format json
python3 -m unittest discover -s tests -q
git diff --check
git status --short
```

## Baseline preservation rules

1. Phase tests должны использовать fixtures, а не зависеть от текущего числа jobs.
2. Migration dry-run проверяет row/event conservation на свежем `main`.
3. Performance regression оценивается относительно команд, а не абсолютного
   размера меняющегося production dataset.
4. Любая новая projection имеет deterministic freshness check.
5. Перед cutover повторно фиксируются jobs/source refs/operations/test duration.
