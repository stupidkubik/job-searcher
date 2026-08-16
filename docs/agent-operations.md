# Agent operations: trusted connector write-path

Статус: implemented — 2026-08-14

Этот документ описывает действующий путь записи через GitHub connector и
trusted GitHub Actions runner. Полный, machine-enforced JSON contract находится
в [`data/operations/README.md`](../data/operations/README.md); он является
единственным источником истины для формы request. Правила поведения агента — в
[`AGENTS.md`](../AGENTS.md), а код policy — в
[`scripts/agent_operations.py`](../scripts/agent_operations.py).

## ChatGPT web capability boundary

Для ChatGPT web нужны два независимых плагина в одном новом чате:

- Browser открывает discovery source, exact vacancy, employer careers/ATS и
  видимый Apply route;
- GitHub connector читает этот репозиторий и создаёт immutable operation request
  непосредственно в `main`.

GitHub connector сам по себе не предоставляет arbitrary-site Browser access.
Вкладка, в которой пользователь открыл ChatGPT web, также не становится
управляемым агентом браузером без отдельного Browser plugin/tool.
Web search также не заменяет Browser: snippets, cached/indexed results и
`Crawled:` metadata — только discovery evidence, а не доказательство текущей
rendered page или действующего Apply route. После установки или включения
плагинов запускать новый чат, явно вызывать Browser для source navigation и
останавливать browser pass, если Browser tool или requested page недоступны.

### Recommended ChatGPT launch prompt

В composer следует явно выбрать `@GitHub` и `@Browser`, а затем использовать
такой стартовый текст вместе с requested source URL:

```text
Use @GitHub to open https://github.com/stupidkubik/job-searcher and follow AGENTS.md. Use @Browser—not web search—for every source page, employer careers/ATS listing, and Apply-route check.

Before searching, read the full data/jobs.csv, config/profile.md, data/job_sources.csv, and the relevant playbook in docs/sources/ through GitHub. Then perform a Browser preflight: open the requested source URL in @Browser and report whether it loaded as an interactive rendered page. If Browser is unavailable, blocked, or cannot load the page, stop and report the exact limitation. Do not silently substitute web search, cached/indexed results, Crawled metadata, or GitHub tools.

Search the requested source using its playbook. Deduplicate before analysis, verify every promising job on the employer's current careers/ATS page, check the actual Apply route and geographic eligibility, and record every inspected exact vacancy—even closed, unsuitable, or duplicate.

Use @GitHub for repository operations. Write only through immutable connector requests described in data/operations/README.md. Never edit canonical CSV files directly, submit applications, or set a job to applied.
```

## Назначение

Connector может создать только декларативный immutable request. Он не меняет
`data/jobs.csv`, `data/job_sources.csv` или generated
[`docs/tracker.md`](tracker.md) напрямую. Trusted runner интерпретирует request
через существующий `jobs.py` write-path, поэтому сохраняются validation,
dedupe, provenance и side effects application cards.

```text
AI agent via GitHub connector
        │
        │ one immutable request
        ▼
data/operations/requests/<operation-id>.json
        │
        ▼
trusted GitHub Actions runner
        ├─ validate manifest, command policy and optimistic lock
        ├─ apply through scripts/agent_operations.py → jobs.py
        ├─ write immutable result
        ├─ validate canonical dataset
        ├─ render and exact-check docs/tracker.md
        ├─ run unit tests and changed-path allowlist
        ▼
audited commit on main
```

`data/jobs.csv` remains the only structured source of truth. `docs/tracker.md`
is a deterministic read-only projection in the same audited commit, never a
second data store.

## Trust boundary

The request is untrusted data, not an executable instruction. The runner rejects
unknown fields, commands, paths and enum values; neither a shell fragment nor a
request-provided executable path is accepted. The request cannot select its risk
class or broaden the changed-file allowlist.

The runner may change only:

```text
data/jobs.csv
data/job_sources.csv
docs/tracker.md
data/operations/results/<operation-id>.json
applications/job-*.md
```

Any change to `scripts/`, `.github/`, `config/`, schema or other policy files is
rejected. Changes to this policy follow the ordinary reviewed repository path;
they cannot be bundled into an agent operation.

## Delivery

All connector operations use `main`. The runner commits the audited result
directly to `main`; it does not create operation branches or review PRs.

Risk remains useful audit information. `screen` and constrained `set` are low
risk; `add`, all user-confirmed `status`, and `verify` that enriches data or
starts `reviewing`/`apply` are medium risk. A batch inherits the highest child
risk. The current workflow records the calculated risk but does not silently
change a branch's delivery mode based on it.

## Current commands and policy

| Command | Purpose | Key restriction |
|---|---|---|
| `add` | create one new job or attach a confirmed duplicate source | single operation or batch child with stable `client_ref`; external source needs provenance |
| `screen` | record a pre-application blocker without claiming verification | cannot close or duplicate a listing |
| `verify` | record completed first-party and Apply verification | needs listing and both verification values |
| `set` | schedule a next action or close an already-applied listing | narrow field allowlist only |
| `status` | record a human lifecycle event | literal `confirmed_by_user=true` required |
| `batch` | apply up to 100 distinct updates/additions together | `atomic=true`; add IDs are assigned inside the transaction |

`status` is the only connector command for `applied`, `interviewing`, `offer`,
`rejected`, `ghosted`, and `withdrawn`. The user must explicitly report or
request the lifecycle event; an agent may never infer it from a vacancy page,
email fragment or silence.

## Optimistic locking and results

Every update request has a non-empty `expected` object. The connector reads the
current row and includes `last_update` plus the state fields relevant to its
decision. If any expected value differs in the runner checkout, no canonical
write occurs and the runner writes an immutable `conflict` result with the
mismatches.

An `add` batch child has no `job_id` or `expected`: it carries a unique stable
`client_ref` and validated add args. The runner assigns sequential job IDs in
child order inside the isolated dataset and returns the `client_ref → job_id`
mapping. A duplicate/source-reference conflict in any add child rolls back the
whole batch.

An operation ID can have exactly one result, regardless of whether that result
is `completed` or `conflict`. The presence of a request file is not completion;
the agent waits for the matching file in `data/operations/results/` and the
canonical diff/PR.

## Generated browser-view lifecycle

For every request outcome the runner executes the normal quality gates after
the operation executor:

1. `jobs.py validate --strict` validates canonical CSV and source references.
2. `jobs.py render-tracker` regenerates the browser view.
3. `jobs.py render-tracker --check` proves exact freshness.
4. The unit suite and changed-path allowlist must pass.
5. The runner commits its result and generated tracker directly to `main`.

Thus a successful connector operation cannot leave `docs/tracker.md` stale. A
conflict preserves the existing canonical view; its immutable result makes the
reason visible without creating a duplicate attempt.

## Connector checklist

1. Read the current job data and avoid reprocessing a terminal or duplicate
   record.
2. Verify the first-party listing before any full analysis; use `screen` only
   when a blocker is known without such verification.
3. Create one new request whose filename equals `operation_id`.
4. Create it directly on `main`.
5. Do not edit any generated or canonical file beside the request.
6. Wait for the matching immutable result and audited diff in `main`.
7. Wait for the successful workflow before reporting the operation complete.

## v1 boundary and future hardening

The v1 manifest intentionally retains `args` and `expected`: flattening them or
dropping the lock would make requests shorter but weaken the policy boundary.
`operation_id` duplicates the filename and `atomic=true` is currently mandatory
for every batch; simplifying those two redundancies belongs to a separate,
versioned v2 contract with backward compatibility. A stronger revision token is
also future work: `last_update` is a date, not a per-write revision.
