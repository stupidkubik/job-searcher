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
| generated field × command allowlist | [`data/operations/contract.md`](../data/operations/contract.md) |
| ChatGPT Browser/GitHub boundary, launch prompt и connector runner | [`agent-operations.md`](agent-operations.md) |
| immutable raw inbox и ingest | [`data/inbox/README.md`](../data/inbox/README.md) |
| source/ATS playbooks | [`sources/README.md`](sources/README.md) |
| локальный Telegram discovery adapter | [`sources/telegram.md`](sources/telegram.md) |
| реализованное и будущие изменения | [`roadmap.md`](roadmap.md) |
| generated browser view | [`tracker.md`](tracker.md) |
| generated bootstrap-индексы для дедупа и активного среза | `data/index/known.tsv`, `data/index/keys.tsv`, `data/index/active.csv` (`render-index`) |
| компактный bootstrap-профиль кандидата | [`config/profile-digest.md`](../config/profile-digest.md) |

## Historical records

Следующие документы сохраняют историю решений, но не являются инструкциями:

- [`architecture.md`](architecture.md) — pre-v1 architecture research;
- [`setup-plan.md`](setup-plan.md) — первоначальный setup plan;
- [`tracker-v2-plan.md`](tracker-v2-plan.md) и
  [`tracker-browser-view-plan.md`](tracker-browser-view-plan.md) — принятые
  implementation plans;
- [`telegram-source-integration-plan.md`](telegram-source-integration-plan.md) —
  implementation plan первой локальной Telegram-поставки;
- `tracker-*-feedback.md` и `tracker-*-audit-*.md` — снимки обратной связи и
  аудитов на конкретную дату;
- [`agent-ergonomics-analysis-2026-09-07.md`](agent-ergonomics-analysis-2026-09-07.md) —
  замеры write-path'а, бутстрапа и кодовой базы с точки зрения ИИ-агента;
  снимок на 2026-09-07, свежие цифры даёт
  `scripts/maintenance/ops_health.py`;
- [`agent-write-path-plan-2026-09-07.md`](agent-write-path-plan-2026-09-07.md) —
  поэтапный план, построенный на этих замерах; закрыт 2026-09-08, все этапы
  Э0–Э10 реализованы.

Незакрытые остатки закрытого плана живут в [`roadmap.md`](roadmap.md), а не в
самом плане: исторический документ не переписывается задним числом.

Каждый файл из этого раздела обязан нести в себе баннер
`> Historical record. Not a contract.`. `test_documentation.py` берёт список
именно отсюда — из первой ссылки каждого пункта, — поэтому добавленная сюда
строка сразу становится проверяемой.

## Исследования и предложения

- [`telegram-source-integration-analysis.md`](telegram-source-integration-analysis.md) —
  варианты получения вакансий из Telegram, ограничения API и рекомендуемая
  архитектура; предложение, а не реализованный source contract.
- [`github-job-tracker-inspiration-analysis-2026-09-22.md`](github-job-tracker-inspiration-analysis-2026-09-22.md) —
  обзор открытых job-tracker и job-search workspace на GitHub, сравнительный
  анализ паттернов и shortlist тем для последующего проектирования; исследование,
  а не implementation plan.
- [`deep-research-report.md`](deep-research-report.md) — углублённая проверка
  GitHub-проектов, их кода, CI и issues; конкретные P0–P2 улучшения и предлагаемая
  последовательность развития следующей версии трекера; исследование, а не
  утверждённый implementation plan.
- [`tracker-v3/README.md`](tracker-v3/README.md) — planning workspace следующей
  версии: последовательный план, baseline, журнал работ и решений, blockers,
  risk register и verification matrix; proposal на ветке `codex/tracker-v3`,
  пока не действующий архитектурный контракт.

## Матрица обновлений

| Что изменилось | Что обновить в том же коммите |
|---|---|
| поле CSV, enum или invariant | `data/schema.md`, `scripts/jobs.py`, tests; при видимом изменении — tracker renderer/docs |
| connector command или risk/write policy | `data/operations/README.md`, `docs/agent-operations.md`, `AGENTS.md`, tests |
| allowlist команды в `agent_operations.py` | перегенерировать `data/operations/contract.md` (`render-contract`), tests |
| adapter, source policy или raw contract | `config/sources.toml`, соответствующий `docs/sources/*.md`, `data/inbox/README.md`, tests |
| workflow или trust boundary | `.github/workflows/`, `docs/current-architecture.md`, соответствующий contract doc, tests |
| ChatGPT Browser/GitHub capability boundary или launch prompt | `AGENTS.md`, `docs/agent-operations.md`, `docs/sources/README.md`, `docs/current-architecture.md` |
| каталог или основной entry point | `README.md`, `docs/current-architecture.md`, этот индекс |
| временная семантика | `data/schema.md`, raw/artifact contracts и boundary tests |
| поле CSV меняется настолько, что затрагивает bootstrap-индексы | перегенерировать `data/index/*` (`render-index`), `data/schema.md` |
| `config/profile.md` меняется в гео/уровне/стеке/компенсации/work authorization/red flags | обновить `config/profile-digest.md`; тест проверяет наличие обязательных ключей |
| план или аудит закрыт | перенести его строку в «Historical records», добавить в файл баннер `> Historical record. Not a contract.`, а незакрытые остатки — в `roadmap.md` |

Планы и исторические аудиты не следует переписывать задним числом. Вместо этого
обновляется действующий документ, а изменение фиксируется обычным Git diff.
