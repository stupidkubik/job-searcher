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

The public API is cached and refreshed roughly daily, so one narrow run per day is enough. Respect rate limits and back off on HTTP 429.

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

## Narrow pass

Cadence: daily.

Run geography separately for Serbia and worldwide/Europe rather than trusting a generic Europe label.

Example Serbia discovery query:

```text
https://himalayas.app/jobs/api/search?q=frontend&country=RS&sort=recent&page=1
```

Example worldwide discovery query:

```text
https://himalayas.app/jobs/api/search?q=frontend&worldwide=true&sort=recent&page=1
```

Run separate queries for:

- Frontend Developer
- Frontend Engineer
- React Developer
- Web Developer
- Frontend Engineer I
- Junior Frontend
- Graduate Frontend
- Associate Frontend
- React
- TypeScript
- Next.js
- JavaScript

Employment types to keep:

- Full Time
- Intern
- Contractor

Seniority:

- prioritize `Entry-level`
- also inspect `Mid-level`, because Himalayas labels can be broader than the actual years-of-experience requirement

Local post-filtering:

1. primary window: `pubDate` within 7 days
2. if sparse, expand to 30 days
3. `expiryDate` must be in the future as a preliminary check
4. reject Senior / Staff / Lead / Principal / Manager titles and descriptions
5. target roughly 0–2/3 years of required experience
6. verify `locationRestrictions` plus free-text geography/work-authorization wording
7. open the employer careers/ATS page and verify the role plus a working Apply path

The API does not need to provide a native “posted within N days” filter: compute the 7/30-day window locally from `pubDate`.

## Broad pass

Cadence: 2–3 times per week.

Run separate discovery queries for:

- Software Engineer I
- Product Engineer
- Design Engineer
- UI Engineer
- Creative Developer
- Technical Consultant
- Web Developer
- CMS
- Content
- Commerce
- Marketing Engineer

Keep a result only if it has at least two strong frontend signals among:

- React
- TypeScript
- Next.js
- HTML/CSS
- Figma
- CMS
- component library / design system

Reject backend-heavy roles before doing a full analysis.

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

## Recommended cadence

- narrow: once daily
- broad: 2–3 times per week

Polling several times per day is unnecessary while the public dataset refresh cadence remains roughly daily.
