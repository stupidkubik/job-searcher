# Documentation map

Это индекс актуальной документации проекта. Если структура репозитория или
write path меняются, этот файл и корневой [`README.md`](../README.md) должны
обновляться в том же коммите.

## Действующие документы

| Область | Source of truth |
|---|---|
| назначение проекта и быстрый старт | [`README.md`](../README.md) |
| текущая архитектура и поток данных | [`current-architecture.md`](current-architecture.md) |
| обязательные правила для агентов | [`AGENTS.md`](../AGENTS.md) |
| canonical CSV schema и enums | [`data/schema.md`](../data/schema.md) |
| локальный CLI и примеры | [`jobs-cli.md`](jobs-cli.md) |
| connector request/result contract | [`data/operations/README.md`](../data/operations/README.md) |
| ChatGPT Browser/GitHub boundary, launch prompt и connector runner | [`agent-operations.md`](agent-operations.md) |
| immutable raw inbox и ingest | [`data/inbox/README.md`](../data/inbox/README.md) |
| source/ATS playbooks | [`sources/README.md`](sources/README.md) |
| реализованное и будущие изменения | [`roadmap.md`](roadmap.md) |
| generated browser view | [`tracker.md`](tracker.md) |

## Historical records

Следующие документы сохраняют историю решений, но не являются инструкциями:

- [`architecture.md`](architecture.md) — pre-v1 architecture research;
- [`setup-plan.md`](setup-plan.md) — первоначальный setup plan;
- [`tracker-v2-plan.md`](tracker-v2-plan.md) и
  [`tracker-browser-view-plan.md`](tracker-browser-view-plan.md) — принятые
  implementation plans;
- `tracker-*-feedback.md` и `tracker-*-audit-*.md` — снимки обратной связи и
  аудитов на конкретную дату.

## Матрица обновлений

| Что изменилось | Что обновить в том же коммите |
|---|---|
| поле CSV, enum или invariant | `data/schema.md`, `scripts/jobs.py`, tests; при видимом изменении — tracker renderer/docs |
| connector command или risk/write policy | `data/operations/README.md`, `docs/agent-operations.md`, `AGENTS.md`, tests |
| adapter, source policy или raw contract | `config/sources.toml`, соответствующий `docs/sources/*.md`, `data/inbox/README.md`, tests |
| workflow или trust boundary | `.github/workflows/`, `docs/current-architecture.md`, соответствующий contract doc, tests |
| ChatGPT Browser/GitHub capability boundary или launch prompt | `AGENTS.md`, `docs/agent-operations.md`, `docs/sources/README.md`, `docs/current-architecture.md` |
| каталог или основной entry point | `README.md`, `docs/current-architecture.md`, этот индекс |
| временная семантика | `data/schema.md`, raw/artifact contracts и boundary tests |

Планы и исторические аудиты не следует переписывать задним числом. Вместо этого
обновляется действующий документ, а изменение фиксируется обычным Git diff.
