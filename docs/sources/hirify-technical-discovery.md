# Hirify technical discovery research note

Checked: 2026-08-14

Status: research note for a possible future `import_hirify.py`. This document is
not an implementation contract and does not enable automated fetching by itself.
Re-check Hirify's public Terms and technical surface before implementation.

This is a non-normative research record, not another search lifecycle. The
normative workflow lives in [`README.md`](README.md), and the short source
playbook lives in [`hirify.md`](hirify.md).

## Executive summary

The public Hirify surface is useful for deterministic discovery because exact job
pages expose a stable numeric ID and the site publishes many crawlable SEO routes
for role, seniority, technology, geography and remote-work combinations.

However, during this discovery no documented public JSON API was found. The
previous Hirify pass did **not** use a Hirify API: candidates came from public
HTML/SEO pages, exact `/jobs/<id>-<slug>` cards, and in some cases search-engine
indexing of those pages. Search-engine caches can be stale and must never be
used as a freshness signal.

The public Hirify Terms observed on 2026-08-14 prohibit direct programmatic
access to internal APIs, imitation of web-application requests and automated
scraping/parsing. Because of that restriction, this discovery intentionally did
not reverse-engineer private XHR/fetch endpoints or browser request parameters.
A networked `import_hirify.py` should therefore wait for explicit Hirify
permission or an officially documented feed/API.

## 1. What was actually used in the previous pass

The previous manual/agent-assisted pass used these surfaces:

1. public indexable list/SEO pages;
2. public exact job pages;
3. search-engine results pointing at exact Hirify pages when the live list was
   not fully available through the browsing surface;
4. employer careers/ATS pages for first-party verification.

It did **not** use:

- a documented public Hirify JSON API;
- an authenticated Hirify API;
- a reverse-engineered internal XHR endpoint;
- browser automation that reproduced Hirify application requests.

The stale `334257` case is the clearest warning: an external search index
resurfaced an old exact card even though the card had already been manually
confirmed stale/archived. External indexing is discovery-only and cannot provide
freshness.

## 2. Confirmed public routes

### Generic and category routes

```text
https://hirify.me/en/remote-jobs
https://hirify.me/en/software-remote-jobs
https://hirify.me/en/html-remote-jobs
https://hirify.me/en/frontend-dev-jobs
https://hirify.me/en/web-dev-jobs
https://hirify.me/en/jobs-in-serbia
https://hirify.me/en/jobs-in-europe
```

### Seniority / frontend routes

```text
https://hirify.me/en/junior-frontend-dev-jobs
https://hirify.me/en/middle-frontend-dev-jobs
https://hirify.me/en/junior-frontend-dev-remote-jobs
https://hirify.me/en/middle-frontend-dev-remote-jobs
https://hirify.me/en/frontend-dev-remote-jobs
```

### Technology combinations

```text
https://hirify.me/en/junior-frontend-dev-typescript-jobs
https://hirify.me/en/junior-frontend-dev-javascript-jobs
https://hirify.me/en/frontend-dev-typescript-jobs
https://hirify.me/en/frontend-dev-typescript-jobs-in-serbia
https://hirify.me/frontend-dev-javascript-jobs-in-serbia
```

These paths show that at least part of Hirify's discovery taxonomy is encoded in
SEO-friendly paths rather than requiring query-string filters.

### Exact job route

```text
https://hirify.me/jobs/<numeric-id>-<slug>
```

Example shape:

```text
/jobs/123456-frontend-developer-react-typescript
      ^^^^^^
      stable Hirify source_job_id
```

Treat the numeric ID as the stable source identity. The slug is descriptive and
should not be used for dedupe.

## 3. Transport: HTML vs embedded JSON vs JSON endpoint

Confirmed from the public surface available during discovery:

| Surface | Observed transport | Notes |
|---|---|---|
| List / SEO pages | HTML | First page content and filter labels are crawlable/readable without a private API contract. |
| Exact job pages | HTML | Title, metadata, description and archived/stale signals are exposed in the public page. |
| Embedded JSON | Not confirmed | No reliable `__NEXT_DATA__`, `__NUXT__`, JSON-LD or equivalent contract was established. |
| Public JSON endpoint | Not found | No documented public API was identified. |
| Internal JSON/XHR API | Not investigated | Terms prohibit direct programmatic access / request imitation. |

Absence of embedded JSON in the parsed browsing representation does not prove
that raw HTML contains no script data. The current conclusion is only that a
stable embedded-JSON contract was not established and should not be assumed.

## 4. Search and filter semantics visible in the UI

The public UI and Hirify's filter guide expose these filter families:

- work format: `Remote`, `Hybrid`, `Onsite`;
- remote type / region: `Global`, `Russia`, `Europe`, `USA`;
- specialization;
- skills / technologies;
- industries;
- grade / seniority, including Trainee through C-level;
- company type;
- geo-regions and countries;
- relocation;
- work type / employment format;
- English level;
- vacancy language;
- salary currency and minimum salary.

Title search supports Boolean-style operators in the product UI, including:

```text
"exact phrase"
A OR B
A AND B
-excluded
```

Skills can be combined using OR by default and the UI can switch to AND.
Exclusion is also supported at the product level.

### Important unknown

The exact HTTP parameter names for these filters were **not** established.
Do not invent parameters such as:

```text
?page=
?sort=
?grade=
?skills=
```

until Hirify documents them or explicitly permits network-level inspection.

## 5. Sorting and pagination

### Sorting

The public UI shows a default sorting state equivalent to `newest`.

What is unknown:

- the HTTP parameter name;
- alternative machine-readable sort values;
- whether sorting is server-side or performed by an internal API/client layer.

### Pagination

The public list UI exposes numbered pages such as `1 2 3`, previous/next
navigation in some contexts, and an Infinite scroll mode.

What is unknown:

- the exact page URL convention;
- whether numbered pagination maps to a query parameter, path component, cursor
  or private API call;
- the page size;
- the cursor/infinite-scroll request contract.

A future importer must not guess this contract.

## 6. Stable identifier and dedupe

Use:

```text
source = Hirify
source_job_id = numeric ID from /jobs/<id>-<slug>
source_url = full exact Hirify job URL
```

Dedupe order remains:

1. `source + source_job_id`;
2. verified exact first-party URL;
3. exact Hirify source URL;
4. normalized company + role;
5. fuzzy review.

A repost may receive a new Hirify numeric ID while resolving to the same
employer/ATS vacancy. Therefore Hirify ID identifies a **Hirify card**, not
necessarily a unique canonical employer vacancy.

Observed tracker examples already demonstrate this:

- two Hirify IDs resolved to one Aviasales canonical job;
- two Hirify IDs resolved to one Plata Card canonical job;
- a fresh Hirify ID resolved to an already tracked Primer vacancy;
- a fresh Hirify ID resolved to an already applied SuperPlane vacancy.

## 7. Fields available from the public card/page

### List-card level

Observed or consistently exposed fields include:

- numeric job ID through the exact URL;
- title;
- company label or `Company hidden`;
- work format;
- remote region / country labels;
- work type;
- grade / seniority label;
- relative freshness/date label;
- skills / technology tags;
- sometimes salary.

### Exact-page level

The exact page can additionally expose:

- full description captured by Hirify;
- English requirement;
- relocation flag;
- more detailed location metadata;
- AI/Original description toggle;
- source/category metadata;
- AI score/ranking metadata;
- sometimes contact/source/application affordances.

### Publication time

A stable authoritative ISO `published_at` was not established. Public UI text
may contain values such as:

```text
2 hours ago
1 month ago
updated 5 days ago
Aug 10
```

Until a documented timestamp exists, a parser should preserve these strings as
raw discovery metadata rather than fabricate an ISO timestamp.

Suggested fields for a normalized discovery record:

```text
source_job_id
source_url
company_label
title
work_format
remote_scope
location_labels
work_type
grade
freshness_text
freshness_kind
skills
salary_text
archived
stale_warning
raw_description
```

## 8. Archived and stale signals

### Hard Hirify-side archive signal

Exact pages can explicitly show:

```text
This vacancy is archived
```

This is sufficient to say the **Hirify card** is archived. It is not enough to
conclude that the canonical employer vacancy is closed without checking the
employer/ATS board.

### Soft stale warning

Hirify can keep an exact page accessible while warning that the vacancy is older
than a freshness threshold and may no longer be current.

The previously inspected `334257` is a representative case: the exact card can
remain indexable even though it is stale/archived from the practical search
perspective.

### Update label

Some cards show `updated N ago` rather than a normal relative date. The exact
semantics of the underlying original-vs-update timestamps are not documented.
Preserve the raw label rather than infer a new publication date.

### Search-engine cache

Google/Bing or another index can keep returning a Hirify exact page after its
state changes. Search-engine snippets are therefore useful only for discovering
an ID/URL, never for:

- freshness;
- current listing status;
- current location;
- Apply availability.

## 9. JavaScript, cookies, anti-bot and rate limits

Public list and exact-page content was readable without a Hirify login in the
available browsing environment.

Hirify's public privacy documentation states that cookies/local storage may be
used for login, language, theme and UI state. It also describes request rate
limiting and automated/suspicious access detection.

No numeric request quota was published or tested during this discovery.
Do not benchmark the anti-bot boundary by generating traffic.

### Terms restriction

As observed on 2026-08-14, Hirify's public Terms prohibit behavior including:

- direct programmatic access to internal/private APIs;
- imitation of requests made by the web application;
- automated bots/scripts for scraping/parsing the service.

Consequences for this repository:

1. do not build a networked `import_hirify.py` against a private endpoint;
2. do not automate browser XHR reproduction;
3. do not bypass rate limits, cookies, bot detection or access controls;
4. re-check Terms before future implementation;
5. prefer explicit written permission or an official feed/API.

Official pages to re-check before implementation:

```text
https://hirify.me/terms-of-service
https://hirify.me/privacy-policy
```

Public contact observed for AI/automation questions:

```text
ai@hirify.me
```

## 10. Proposed fixture shapes

These are **normalized parser fixtures**, not examples of a Hirify JSON API.
The public response established during this discovery is HTML.

### Normal active card

```json
{
  "source_job_id": "123456",
  "source_url": "/jobs/123456-frontend-developer-react",
  "company_label": "Company hidden",
  "title": "Frontend Developer (React)",
  "work_format": ["remote"],
  "remote_scope": ["Europe"],
  "work_type": "fulltime",
  "grade": ["junior"],
  "freshness_text": "2 hours ago",
  "skills": ["typescript", "react", "vite"],
  "salary_text": null,
  "archived": false
}
```

### Archived card

```json
{
  "source_job_id": "123457",
  "source_url": "/jobs/123457-frontend-engineer",
  "company_label": null,
  "title": "Frontend Engineer",
  "freshness_kind": "updated",
  "freshness_text": "5 days ago",
  "work_format": ["remote"],
  "grade": ["middle"],
  "archived": true
}
```

### Soft-stale card

```json
{
  "source_job_id": "123458",
  "source_url": "/jobs/123458-frontend-developer",
  "title": "Frontend Developer",
  "archived": false,
  "stale_warning": true,
  "stale_warning_days": 7,
  "freshness_text": "1 month ago"
}
```

If parser development becomes permitted, fixture source should preferably be
manually saved and sanitized HTML pages representing:

1. active visible-company card;
2. active hidden-company card;
3. archived card;
4. soft-stale card;
5. salary-present card;
6. repost/duplicate card.

## 11. Proposed deterministic query sets

The safest deterministic model currently available is a fixed set of public SEO
routes rather than undocumented query parameters.

### Narrow

High-signal routes:

```text
/en/junior-frontend-dev-jobs
/en/junior-frontend-dev-typescript-jobs
/en/junior-frontend-dev-javascript-jobs
/en/junior-frontend-dev-remote-jobs
/en/frontend-dev-typescript-jobs-in-serbia
/frontend-dev-javascript-jobs-in-serbia
/en/middle-frontend-dev-remote-jobs
```

Purpose:

- prioritize Junior / Trainee / Associate-like frontend roles;
- preserve React/TypeScript/JavaScript relevance;
- explicitly cover Serbia;
- keep Middle remote as a deliberate stretch bucket.

### Broad

```text
/en/frontend-dev-jobs
/en/frontend-dev-remote-jobs
/en/middle-frontend-dev-jobs
/en/web-dev-jobs
/en/jobs-in-serbia
/en/jobs-in-europe
/en/software-remote-jobs
```

Broad results need stricter local post-filtering because category pages include
backend-heavy, CMS, WordPress, QA and other adjacent roles.

### Queries/routes that produced useful signal

Most useful during the latest pass:

- frontend-specific pages;
- junior frontend pages;
- frontend + TypeScript combinations;
- frontend + Serbia combinations;
- middle frontend remote as a stretch pass;
- exact numeric job pages once discovered.

### High-noise families

Observed as much noisier for the target profile:

- bare `JavaScript` discovery;
- bare `TypeScript` discovery;
- generic software-remote pages;
- HTML as a standalone category;
- broad web-dev pages without frontend post-filtering.

Common noise includes:

- backend/full-stack roles where frontend is incidental;
- SDET / QA automation;
- WordPress / Tilda / low-code website work;
- marketing/web-content roles;
- senior roles caught by a technology keyword;
- country-specific remote jobs whose teaser looks global.

## 12. Facts that cannot be trusted without first-party verification

Hirify alone cannot reliably establish:

- whether the employer vacancy is still open now;
- whether the actual Apply route works;
- employer identity when the company is hidden or represented by an
  intermediary;
- Serbia eligibility;
- allowed/excluded countries;
- payroll/entity limitations;
- contractor availability;
- work authorization requirements;
- office attendance / relocation requirements;
- authoritative salary;
- authoritative seniority;
- authoritative required stack;
- authoritative publication date;
- whether two Hirify IDs are reposts of the same employer vacancy;
- whether the external source behind Hirify is itself another aggregator.

The first-party employer careers page or ATS remains the source of truth for all
of these fields.

## 13. Suggested implementation boundary

Do not implement a network fetcher yet.

A future compliant implementation can take one of three shapes:

### A. Official API/feed

Preferred path. Ask Hirify for permission/documentation and implement only the
published endpoint contract.

Required contract before coding:

```text
base/search endpoint
accepted query/filter parameters
sort values
pagination/cursor contract
page size
rate-limit policy
authentication requirements
stable field names
timestamp semantics
archive semantics
permitted automated-use policy
```

### B. Explicit permission to read public HTML

If Hirify explicitly permits automated retrieval of public HTML, implement an
HTML fetcher with conservative rate limiting and a stable parser over public SEO
routes.

The adapter should remain fetch-only and output immutable raw/normalized
records. First-party verification remains a separate stage.

### C. Offline/manual HTML parser

Safe interim engineering option: implement parsing against manually saved,
sanitzed HTML fixtures only. This validates normalization, dedupe and archive
logic without making automated requests to Hirify.

## 14. Open questions for later analysis

Before a production `import_hirify.py`, resolve:

1. Does Hirify offer an official API or partner feed for personal job-search
   automation?
2. Can Hirify explicitly authorize automated reading of public SEO pages?
3. If authorized, what is the canonical pagination contract?
4. What is the authoritative sort contract?
5. Is there a machine timestamp for original publication and last update?
6. Is archived state available as a structured field or only rendered text?
7. Are hidden-company application/source links available under automation
   permission without a paid/session-only interaction?
8. What request cadence is acceptable?
9. Can a single source card change slug while keeping the same numeric ID?
10. Can Hirify expose a stable original-source URL in an approved feed?

Until those questions are answered, treat this document as a taxonomy and
parser-design reference, not permission to perform automated network discovery.
