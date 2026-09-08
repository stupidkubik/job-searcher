# Agent operations: trusted connector write-path

Статус: implemented — 2026-08-14, последняя ревизия write-path'а 2026-09-08

Этот документ описывает действующий путь записи через GitHub connector и
trusted GitHub Actions runner. Полный, machine-enforced JSON contract находится
в [`data/operations/README.md`](../data/operations/README.md); он является
единственным источником истины для формы request. Какое поле принимает какая
команда — в сгенерированном
[`data/operations/contract.md`](../data/operations/contract.md)
(`python3 scripts/agent_operations.py render-contract`), собранном из тех же
allowlist'ов, что enforces runner. Правила поведения агента — в
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

Bootstrap by reading exactly these, through GitHub, in this order: config/profile-digest.md (candidate digest), data/index/known.tsv and data/index/keys.tsv (deduplication indexes), data/index/active.csv (open work), then docs/sources/README.md and the one playbook it names for the requested source. Do not read data/jobs.csv, data/job_sources.csv, or config/profile.md in full unless an index is genuinely insufficient for a specific decision; say why when you do. Never read docs/tracker.md at all—it is a generated view for the human, and nothing in it is absent from the indexes.

Then perform a Browser preflight: open the requested source URL in @Browser and report whether it loaded as an interactive rendered page. If Browser is unavailable, blocked, or cannot load the page, stop and report the exact limitation. Do not silently substitute web search, cached/indexed results, Crawled metadata, or GitHub tools.

Search the requested source using its playbook. Deduplicate against the indexes before analysis, verify every promising job on the employer's current careers/ATS page, check the actual Apply route and geographic eligibility, and record every inspected exact vacancy—even closed, unsuitable, or duplicate.

Use @GitHub for every repository operation, and write only through immutable connector requests. Learn the request envelope from data/operations/README.md and the per-command fields from data/operations/contract.md: pass only fields the table allows for that command—an unlisted field or an off-enum value gets the whole request rejected, and no command anywhere accepts next_action or verified_at. Any command that updates an existing job also needs a non-empty expected lock carrying last_update plus the fields your decision depends on. Commit exactly one new file, data/operations/requests/<operation_id>.json, directly to main; never open a pull request and never touch another file in that commit. Keep an atomic batch at 10 children or fewer, a non-atomic batch at 100 or fewer. Never edit data/jobs.csv, data/job_sources.csv, data/index/*, or docs/tracker.md yourself—the runner regenerates the last two in the same audited commit. Never submit applications and never set a job to applied.

An operation is complete only when data/operations/results/<operation_id>.json exists and the runner's workflow has finished; a committed request is not a result. Read that file—it always exists, one per operation_id, and it is your only error channel: status is completed, partial, conflict, or rejected. A rejected result deliberately turns the GitHub Actions run red while leaving canonical data untouched; that is a readable outcome, not a lost operation, so read error.code, error.field and error.hint instead of resubmitting blindly. A conflict—or any conflicting child of a non-atomic batch—carries a ready-to-send retry fragment; use it. Every retry, in every case, goes out under a NEW operation_id: requests and results are immutable and are never rewritten.
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
        ├─ render and exact-check data/index/*
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
data/index/known.tsv
data/index/keys.tsv
data/index/active.csv
data/operations/results/<operation-id>.json
applications/job-*.md
```

The two generated projections — `docs/tracker.md` and `data/index/*` — are in
this list because the runner regenerates them from the canonical write in the
same commit, not because a request may address them.

Any change to `scripts/`, `.github/`, `config/`, schema or other policy files is
rejected. Changes to this policy follow the ordinary reviewed repository path;
they cannot be bundled into an agent operation. A `rejected` result narrows this
further: the only path it may touch is its own
`data/operations/results/<operation-id>.json`, since a rejected operation must
leave canonical data untouched.

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
| `batch` | apply distinct updates/additions together | `atomic=true` caps at 10 and rolls back on any conflict; `atomic=false` caps at 100 and keeps whatever children apply (`status=partial`); add IDs are assigned inside the transaction |

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
whole batch under `atomic=true`; under `atomic=false` only that child is
recorded as `conflict` and excluded, and the rest of the batch still applies.
The same split governs a stale optimistic-lock precondition on a non-add
child. Every conflicting child, and a conflicting single-operation `add`, gets
a `retry` object: ready-to-send `as_separate`/`as_duplicate` fragments for an
add conflict, or the same request with a refreshed `expected` for a stale
lock — always under a fresh `operation_id`.

An operation ID can have exactly one result, regardless of whether that result
is `completed`, `conflict`, `partial`, or `rejected`. The presence of a request
file is not completion; the agent waits for the matching file in
`data/operations/results/` and the runner's canonical diff on `main`.

A request that fails contract validation, or trips an internal invariant
before any canonical write, gets a `rejected` result instead of a silent
runner crash: `error.code` names one value from a closed taxonomy (see
[`data/operations/README.md`](../data/operations/README.md#result-status-and-the-rejected-shape)
for the full list and JSON shape). Canonical data never changes for a
`rejected` result, but unlike `conflict` the GitHub Actions run itself ends
red, since that is what makes an agent-invisible failure visible to a human.
Retrying means a new `operation_id`; the runner never overwrites an existing
result, rejected or not.

## Generated browser-view lifecycle

For every request outcome the runner executes the normal quality gates after
the operation executor:

1. `jobs.py validate --strict` validates canonical CSV and source references.
2. `jobs.py render-tracker` regenerates the human browser view, and
   `render-tracker --check` proves exact freshness.
3. `jobs.py render-index` regenerates the agent bootstrap indexes
   (`data/index/known.tsv`, `keys.tsv`, `active.csv`), and
   `render-index --check` proves exact freshness.
4. The unit suite and changed-path allowlist must pass.
5. The runner commits its result and both generated projections directly to
   `main`.

Thus a successful connector operation cannot leave `docs/tracker.md` or the
bootstrap indexes stale — which matters for the indexes in particular, since
they are what the next agent run boots from. A conflict preserves the existing
canonical view; its immutable result makes the reason visible without creating
a duplicate attempt.

A `rejected` result skips steps 1-3 by design: canonical data did not change,
so there is nothing to re-render, and the changed-path allowlist then demands
exactly one path — the result file itself.

## Connector checklist

1. Boot from `config/profile-digest.md` and `data/index/*`, and avoid
   reprocessing a terminal or duplicate record.
2. Verify the first-party listing before any full analysis; use `screen` only
   when a blocker is known without such verification.
3. Read `contract.md` and build `args` from the table for that command only.
4. Create one new request whose filename equals `operation_id`, directly on
   `main`, and edit no other file in that commit.
5. Wait for the matching immutable result in `data/operations/results/` and for
   the workflow run to finish.
6. Read the result before reporting. `completed` and `partial` carry the
   canonical diff; `conflict` and `rejected` carry the reason and, where
   applicable, a `retry` fragment.
7. Do not wait for a green run: a `rejected` result ends the run red on
   purpose. The finished run plus the result file is the completion signal —
   red with a result is an answer, and only a missing result is an
   unfinished operation.
8. Retry only under a new `operation_id`.

## v1 boundary and future hardening

The v1 manifest intentionally retains `args` and `expected`: flattening them or
dropping the lock would make requests shorter but weaken the policy boundary.
`operation_id` duplicating the filename is a redundancy that simplifying
belongs to a separate, versioned v2 contract with backward compatibility. A
stronger revision token is also future work: `last_update` is a date, not a
per-write revision.
