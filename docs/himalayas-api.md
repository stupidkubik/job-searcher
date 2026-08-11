# Himalayas API — notes for search automation

Checked: 2026-08-11

Official references:

- https://himalayas.app/api
- https://himalayas.app/docs/remote-jobs-api
- https://himalayas.app/docs/openapi.json
- https://himalayas.app/docs/data-dictionary

## Why this source is useful

Himalayas exposes a public JSON jobs API that is well suited to discovery before first-party verification. The useful part for this repository is not just keyword search: records include structured geography, employment type, seniority, publication/expiry dates, description text, and application links.

Treat the API as a discovery layer only. `expiryDate` and an application link do **not** prove that the employer still has the role open. The repository rule remains unchanged: verify the first-party careers/ATS page before treating a vacancy as actionable.

The public API is cached and refreshed roughly daily. Respect rate limits and back off on HTTP 429. The canonical operating policy — cadence, age windows, geo, queries, verification gates and caveats — lives in [`config/sources.toml`](../config/sources.toml), not in this document.

## Endpoints

### Feed

```text
GET https://himalayas.app/jobs/api
```

Useful parameters:

- `offset`
- `limit` (up to 20 per request)

### Search

```text
GET https://himalayas.app/jobs/api/search
```

Useful documented parameters:

- `q` — text query
- `country` — country name or ISO alpha-2 code
- `worldwide` — worldwide-only jobs
- `exclude_worldwide` — exclude worldwide jobs from a country query
- `seniority` — e.g. `Entry-level`, `Mid-level`, `Senior`
- `employment_type` — e.g. `Full Time`, `Contractor`, `Intern`
- `company` — company slug
- `timezone` — UTC offset
- `sort` — including `recent`
- `page` — 1-based page

Do not rely on boolean syntax inside `q` unless it is explicitly documented later. Safer approach: run several small queries and deduplicate locally.

## Useful response fields

| Himalayas field | Tracker use |
|---|---|
| `title` | `role` |
| `companyName` | `company` |
| `employmentType` | Full-time / contract / internship filter |
| `locationRestrictions` | `location`, `remote_policy`, geo check |
| `timezoneRestriction` | additional geo/timezone check |
| `minSalary`, `maxSalary`, `salaryPeriod`, `currency` | `salary` |
| `description` | experience, stack, backend-heavy and work-authorization checks |
| `pubDate` | `posted_at` |
| `expiryDate` | preliminary stale check |
| `applicationLink` | candidate first-party link, must still be verified |
| `guid` | temporary importer dedupe key |
| `companySlug` | stable company filter |

For imported jobs:

- `source=Himalayas`
- `source_url` = Himalayas job card
- `original_url` = verified first-party careers/ATS URL, not the aggregator card

## Operating policy

Use the validated registry rather than copying constants into an adapter:

```bash
python3 scripts/source_config.py
```

`sources.Himalayas` sets the narrow cadence (24 hours), broad cadence (72 hours),
primary and fallback age windows (7 and 30 days), search geography, query sets,
employment types, seniority and both mandatory verification gates. The adapter must
keep `expiryDate` as a preliminary stale signal only; it must not make a decision
about listing openness before first-party verification.

The API does not need to provide a native “posted within N days” filter: an
adapter computes the registry's age window locally from `pubDate`.

## Deduplication

Before adding a row:

1. compare the resolved first-party URL with `original_url`
2. compare the Himalayas card with `source_url`
3. compare normalized `companyName + title`
4. optionally keep Himalayas `guid` in importer state/cache without changing the CSV schema

Do not create duplicates just because the same vacancy appears in both Serbia and worldwide queries.

## Important false-positive example from 2026-08-11

Two initially attractive Himalayas cards demonstrated why first-party verification is mandatory:

- **Choice — Frontend Developer**: Himalayas presented a recent worldwide card, but the current Choice careers page did not list that role; a matching older posting elsewhere was inactive.
- **KDCI — Web Developer**: Himalayas presented a worldwide card with a future expiry date, but KDCI's current careers page did not list that Web Developer opening.

Conclusion: `expiryDate`, freshness, and `applicationLink` are useful discovery signals, not source-of-truth status fields.

## Adapter (Phase 5)

`scripts/import_himalayas.py` is a fetch-only adapter. It validates and reads
the Himalayas policy from `config/sources.toml`, then executes every selected
query in each configured geography pass, with the registry seniority/employment
filters and local age window. It retries only temporary network/429/5xx failures
a bounded number of times.

The configured `geo = ["Serbia", "worldwide", "Europe"]` is operational, not
descriptive metadata:

- Serbia sends `country=Serbia` and `exclude_worldwide=true`.
- Worldwide sends `worldwide=true`.
- Europe pages the unscoped query and keeps only European country/region values
  in `locationRestrictions`; worldwide roles arrive through the Worldwide pass.

Each query/pass starts at `page=1` and continues according to the API response's
`totalCount` and `limit`. Results are deduplicated by `guid` across every query,
geo pass and page, so a role returned by more than one pass remains one raw
record. The JSON summary reports fetched pages and records excluded by the local
Europe filter.

```bash
# Fetch, normalize and report without creating a raw file.
python3 scripts/import_himalayas.py --narrow --dry-run

# Create exactly one new immutable batch; this does not call jobs.py ingest.
python3 scripts/import_himalayas.py --narrow \
  --output data/inbox/himalayas-2026-08-11T090000Z.jsonl
```

`--narrow` is the default and uses `narrow_queries`, `cadence_hours` and
`max_age_days`. `--broad` uses `broad_queries`, `broad_cadence_hours` and
`fallback_max_age_days`. The adapter de-duplicates same-run results by `guid`,
uses that value as `source_job_id`, and retains the complete API job object in
`payload.himalayas`. It only writes a new UTF-8 JSONL file inside `data/inbox/`;
an existing batch is immutable and never overwritten.

The raw record maps `guid` (or, where needed, `applicationLink`) to `source_url`
and keeps `applicationLink` separately as an unverified candidate URL. Neither
is treated as proof of a live or first-party listing. During ingest this candidate
may be compared with an already verified `original_url` for deduplication, but it
is never copied into canonical `original_url`; only `jobs.py verify` writes that
field after first-party verification. The adapter does not call
`jobs.py ingest`, does not inspect canonical jobs, and does not make a decision
about geo, work authorization, seniority, Apply, or listing status.

The first three real runs remain manually controlled: validate the batch, compare
the ingest dry-run and apply summaries, then explicitly decide whether to run
ingest without `--dry-run`. Follow its `verify first-party` queue with the
single `jobs.py verify` command documented in `jobs-cli.md`.

The registry's 24-hour narrow cadence intentionally avoids polling several times
per day while the public dataset refresh cadence remains roughly daily.
