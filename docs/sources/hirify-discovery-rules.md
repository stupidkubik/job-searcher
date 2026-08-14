# Hirify discovery rules

Checked: 2026-08-14

Status: operational specification for manual or connector-assisted Hirify
discovery and for a possible offline HTML parser. It is not permission to fetch
Hirify pages programmatically.

Related documents:

- [`hirify.md`](hirify.md) — verification and source-specific tracker rules;
- [`hirify-technical-discovery.md`](hirify-technical-discovery.md) — observed
  public surface, unknowns and Terms boundary;
- [`README.md`](README.md) — common preflight, dedupe and write-path rules.

## 1. Boundary

The permitted modes are:

1. a human or connector navigates public Hirify pages through an ordinary
   browser session and interprets visible content;
2. an offline parser reads HTML files that a human deliberately saved and
   supplied;
3. tests read sanitized, checked-in HTML fixtures.

Do not:

- implement a networked Hirify crawler without documented permission;
- call or reverse-engineer internal XHR/fetch endpoints;
- imitate private web-application requests;
- automate infinite scroll or pagination against Hirify;
- probe rate limits, bot detection or access controls;
- treat this document as overriding Hirify's current Terms.

Re-check the official Terms before any networked implementation. An official
API/feed or explicit written permission is required before adding Hirify to the
runner's networked `source-discovery.yml` modes.

## 2. Preflight

Before every live pass:

1. read all of `data/jobs.csv`;
2. read all of `data/job_sources.csv`;
3. read `config/profile.md`;
4. read this document and `hirify.md`;
5. record the run start instant in UTC and derive the tracker date in
   `Europe/Belgrade`;
6. build the set of known Hirify numeric IDs before opening results.

Never re-analyze a known source ID. For a known canonical job, follow its
current lifecycle and `next_action`. A new Hirify ID that resolves to an
existing canonical job is a new source reference, not a new job.

## 3. Cadence and age windows

| Pass | Cadence | Discovery window | Purpose |
|---|---:|---:|---|
| narrow | 24 hours | 7 days | High-signal Junior/Frontend/React/TypeScript discovery |
| broad | 72 hours | 30 days | Adjacent titles, missed naming variants and stretch Middle roles |

The cadence is an operational target, not permission to poll automatically.
Run it manually or through an explicitly permitted browser-assisted workflow.

Relative Hirify labels such as `2 hours ago`, `1 month ago` or
`updated 5 days ago` are navigation signals only. Do not convert them to
canonical `posted_at`.

## 4. Narrow route matrix

Visit the following public SEO routes in order:

| Priority | Route | Intent |
|---:|---|---|
| 1 | `/en/junior-frontend-dev-jobs` | Core level and role |
| 2 | `/en/junior-frontend-dev-typescript-jobs` | Core level plus TypeScript |
| 3 | `/en/junior-frontend-dev-javascript-jobs` | Core level plus JavaScript |
| 4 | `/en/junior-frontend-dev-remote-jobs` | Core remote pass |
| 5 | `/en/frontend-dev-typescript-jobs-in-serbia` | Serbia plus TypeScript |
| 6 | `/frontend-dev-javascript-jobs-in-serbia` | Serbia plus JavaScript |
| 7 | `/en/middle-frontend-dev-remote-jobs` | Deliberate stretch pass |

Use `https://hirify.me` as the origin. Preserve the route spelling observed on
the live public surface; do not normalize it into an invented route.

## 5. Broad route matrix

Run only on the broad cadence:

| Priority | Route | Intent |
|---:|---|---|
| 1 | `/en/frontend-dev-jobs` | General frontend naming |
| 2 | `/en/frontend-dev-remote-jobs` | General remote frontend |
| 3 | `/en/middle-frontend-dev-jobs` | Stretch Middle roles |
| 4 | `/en/web-dev-jobs` | Web/UI naming variants |
| 5 | `/en/jobs-in-serbia` | Local and Serbia-compatible roles |
| 6 | `/en/jobs-in-europe` | European remote/hybrid roles |
| 7 | `/en/software-remote-jobs` | Frontend-leaning adjacent software roles |

The broad routes are intentionally noisy. Apply the title and frontend-weight
rules below before opening an exact page.

## 6. Visible UI settings

Use a setting only when its current selected state is visible in the UI. Do not
guess URL parameters or assume a filter survived navigation.

### Sorting

- Select or confirm `newest`.
- If the selected sort cannot be confirmed, mark the route `sort_unclear`.
- Never claim that a relative date label is an authoritative publication date.

### Role and seniority

Primary title families:

- Frontend Developer / Front-End Developer;
- Frontend Engineer / Front-End Engineer;
- React Developer / React Engineer;
- UI Engineer;
- Web Engineer.

Allowed discovery grades:

- Trainee;
- Junior;
- Associate, if available;
- Middle only as a stretch bucket.

Senior, Lead, Staff, Principal, Architect, Head and Manager are not target
grades. If an exact page is opened before the grade is clear, it still must be
recorded with the appropriate structured screening outcome.

### Skills

Use OR semantics for the primary discovery skills:

```text
React OR TypeScript OR JavaScript OR Next.js
```

Do not require all skills simultaneously. Do not use negative skill filters at
discovery time: previews can mention backend, CMS or QA tools while the actual
role remains frontend-heavy.

### Geography and work format

Remote discovery may include visible scopes or countries compatible with:

- Global;
- Europe / European Union;
- Serbia;
- Georgia;
- United States.

Hybrid and on-site discovery is limited to Novi Sad unless the candidate
profile changes. A `Remote`, `Global` or country label is source-side metadata,
not proof of eligibility. Employer geography and work authorization must be
verified separately.

### Settings intentionally left unset

Do not filter discovery by:

- salary — missing salary would hide otherwise relevant roles;
- industry or company type;
- English level — source labels may be incomplete and the profile already
  records English B2 for later screening;
- relocation;
- employment type unless the user changes the candidate profile;
- AI score.

Salary below the candidate threshold is a screening outcome only when the
amount and basis are sufficiently explicit.

## 7. Title-query families

If the current UI visibly supports Boolean title search, use these families.
Do not infer the HTTP representation.

Primary:

```text
"frontend developer" OR "frontend engineer" OR "react developer" OR
"react engineer" OR "ui engineer" OR "web engineer"
```

Broad adjacent:

```text
"creative developer" OR "design engineer" OR "product engineer" OR
"software engineer"
```

An adjacent role should be opened only when the preview indicates that
frontend/UI is a substantial part of the work. Do not add negative Boolean
keywords during discovery.

## 8. Route scan procedure

For each route:

1. record the route and selected visible filters;
2. confirm or flag the visible sort state;
3. scan cards from newest to oldest as presented;
4. extract the numeric ID from every exact URL considered for opening;
5. check the ID against existing source references before analysis;
6. open a previously unseen exact page only when the title or visible skills
   satisfy the rules in sections 6 and 7;
7. immediately preserve the exact URL and numeric ID;
8. inspect the full visible description and source-side archive/stale signals;
9. create the required immutable operation or include the result in the same
   controlled atomic batch;
10. proceed to first-party verification when no immediate hard blocker exists.

Do not leave a newly inspected exact job only in prose, notes or a chat answer.
Every opened exact job must become a canonical row or a source reference through
the repository's allowed write path.

### Stop rule

For a route with visibly confirmed `newest` sorting, stop when two consecutive
visible numbered pages or two consecutive user-triggered scroll batches:

- contain no previously unseen numeric IDs; and
- contain only cards whose visible freshness is outside the pass window.

If sorting, page boundaries or freshness are unclear, the stop rule is unsafe.
Mark the route `incomplete` and report the exact point reached instead of
claiming complete coverage.

## 9. Exact-page extraction

Extract source facts without enriching or translating them:

| Field | Rule |
|---|---|
| `source` | Always `Hirify` |
| `source_job_id` | Numeric component of `/jobs/<id>-<slug>` |
| `source_url` | Absolute exact Hirify job URL |
| company label | Preserve visible label; `Company hidden` must not be resolved by guessing |
| role/title | Preserve visible title with whitespace normalized |
| work format | Preserve visible labels as source metadata |
| remote/location | Preserve visible labels as source metadata |
| grade | Preserve visible Hirify grade |
| skills | Preserve visible tag strings and order where practical |
| salary | Preserve raw source text; do not normalize an unclear period/currency |
| freshness | Preserve the complete raw label and whether it says `updated` |
| archive | Record the exact visible archive message |
| stale warning | Record the exact visible warning and threshold if shown |
| description | Preserve the visible source description as raw discovery context |
| `found_at` | Actual discovery date in `Europe/Belgrade` |
| `posted_at` | Omit unless Hirify exposes an authoritative exact calendar date |

The slug is descriptive and mutable. It is never the stable identifier.

If a canonical operation requires a company value for a hidden-company card,
use the repository convention `Undisclosed` and preserve `Company hidden` in
source-specific notes. Do not infer the employer from skills, prose or an
unverified intermediary.

## 10. Screening before full analysis

An exact Hirify page may establish an immediate title/seniority mismatch, but
source metadata alone does not establish first-party listing status or remote
eligibility.

Immediate structured screening is appropriate for:

- explicit Senior/Lead/Staff/Principal/Architect/Head/Manager role;
- role whose full description is clearly backend-heavy or not frontend;
- explicit source description requiring incompatible work authorization or
  residence, when the restriction is unambiguous.

Do not reject solely because of:

- a generic `Remote` or `Global` badge;
- an AI score;
- a teaser-only technology tag;
- absent salary;
- a relative freshness label;
- a hidden company.

An opened exact page that is screened out still requires a canonical write or
source reference.

## 11. Archive, staleness and first-party verification

`This vacancy is archived` proves only that the Hirify card is archived. A soft
stale warning proves even less. Neither signal alone sets the canonical
employer listing to `closed`.

For a candidate without an immediate hard blocker:

1. identify the employer without guessing;
2. find the exact employer careers or ATS listing;
3. match title, description, location and requisition ID where available;
4. open the current Apply route;
5. inspect geography, authorization and office requirements;
6. only then write `original_url`, `listing_status`, verification fields and
   Apply status.

If the first-party listing cannot be resolved, keep verification unknown and
record a concrete next action. Never substitute another aggregator for a
first-party URL.

## 12. Dedupe order

Apply this order before full analysis:

1. `Hirify + numeric source_job_id`;
2. verified exact first-party URL;
3. normalized exact Hirify source URL;
4. normalized company + role;
5. fuzzy human review.

A new Hirify ID can be a repost of an existing employer vacancy. Confirmed
reposts use `add --duplicate-of JOB_ID` or the equivalent immutable connector
operation. The new source reference receives the actual discovery date unless
an explicit historical `found_at` is supplied.

## 13. Current pipeline limitation

The current raw inbox contract requires both an exact `posted_at` date and a
non-empty `application_url`. Hirify often exposes neither reliably. Therefore:

- do not fabricate either field;
- do not write Hirify records into the current JSONL inbox contract;
- do not register a networked Hirify adapter in `config/sources.toml` yet;
- use immutable connector operations for a live manual/browser-assisted pass;
- use a separate read-only artifact for offline parser experiments.

Supporting Hirify in `jobs.py ingest` would require an explicit raw-contract
change that permits absent `posted_at` and `application_url`, with matching
schema, validation, ingestion and test updates.

## 14. Offline parser contract

An offline parser may be developed before network permission exists, provided
that it:

- accepts only explicit local HTML file paths;
- contains no HTTP client, browser navigation or URL fetching;
- never executes page scripts;
- records a SHA-256 digest for each input file;
- emits a read-only artifact rather than canonical CSV writes;
- preserves raw labels and parser warnings;
- reports missing selectors as record errors instead of inventing values;
- is tested only with manually saved, sanitized fixtures.

Minimum fixture coverage:

1. active visible-company card;
2. active hidden-company card;
3. archived card;
4. soft-stale card;
5. salary-present card;
6. repost with a different Hirify ID;
7. malformed or incomplete page.

The parser should extract the fields in section 9. Its artifact is not eligible
for `jobs.py ingest` until the raw-contract limitation in section 13 is resolved.

## 15. Validation passes

### Offline rule validation

First replay the rules against already tracked Hirify IDs and sanitized saved
pages. This pass is read-only because it discovers no new vacancies. Report:

- IDs tested;
- extraction matches and mismatches;
- missing or ambiguous fields;
- archive/stale classification;
- any selector or terminology drift.

### Controlled live validation

After offline validation, run one narrow live pass using the normal repository
preflight and immutable write path. This is not a canonical-write dry run: any
new exact page opened during the pass must be recorded.

Return per-route and total counts for:

```text
cards_seen
known_ids_skipped
exact_pages_opened
new_ids
new_canonical_jobs
new_source_references
hard_blockers
first_party_verified
verification_pending
hirify_archived
hirify_soft_stale
routes_complete
routes_incomplete
```

For every incomplete route, include the reason and last visible page/batch.

## 16. Acceptance criteria

The rules are ready for routine use when one controlled narrow pass shows that:

1. every opened exact page maps to a canonical job or source reference;
2. no known numeric ID is re-analyzed;
3. no relative freshness label becomes fabricated `posted_at`;
4. no Hirify badge alone becomes first-party verification;
5. duplicate/repost IDs attach to the correct canonical job;
6. route/filter/sort state is captured well enough to reproduce the pass;
7. incomplete coverage is reported honestly;
8. no application, contact reveal, sign-in change or message is performed.

After the first controlled pass, tune only documented route order, stop rules
and high-noise buckets. Do not loosen the Terms boundary or first-party
verification requirements based on convenience.
