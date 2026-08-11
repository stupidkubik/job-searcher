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

## Suggested importer

Future file:

```text
scripts/import_himalayas.py
```

Pipeline:

```text
Himalayas search API
        ↓
normalize records
        ↓
local date/title/seniority/frontend-signal filters
        ↓
dedupe against data/jobs.csv
        ↓
resolve and verify first-party careers/ATS page
        ↓
stale/closed → add to tracker as Closed/Skipped
passed       → add to tracker as Reviewing
        ↓
python3 scripts/jobs.py validate
```

Start with `--dry-run`: print the shortlist plus rejection reasons without writing anything. Enable automatic writes only after several manual verification runs.

The registry's 24-hour narrow cadence intentionally avoids polling several times
per day while the public dataset refresh cadence remains roughly daily.
