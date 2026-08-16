# Hirify route and extraction appendix

Checked: 2026-08-14

Status: source-specific operational settings for manual/browser-assisted Hirify
discovery and a possible offline HTML parser. This is not a second lifecycle and
not permission to fetch Hirify programmatically.

Related documents:

- [`README.md`](README.md) — normative lifecycle, dedupe and write paths;
- [`hirify.md`](hirify.md) — short source playbook;
- [`hirify-technical-discovery.md`](hirify-technical-discovery.md) — observed
  surface, unknowns and Terms research.

## Automation boundary

Allowed modes:

1. a human, or a ChatGPT agent explicitly using the installed Browser plugin,
   navigates public pages in an ordinary browser session; GitHub connector and
   web search alone do not satisfy this mode;
2. an offline parser reads HTML deliberately saved and supplied by a human;
3. tests read sanitized checked-in fixtures.

Do not implement a networked Hirify crawler without documented permission. Do
not reverse-engineer internal XHR/fetch endpoints, imitate private app requests,
automate infinite scroll, probe rate limits or bypass access controls. An
official API/feed or explicit written permission is required before adding a
Hirify mode to `source-discovery.yml`.

## Cadence and depth

| Pass | Cadence | Window | Purpose |
|---|---:|---:|---|
| narrow | 24 hours | 7 days | Junior/frontend/React/TypeScript signal |
| broad | 72 hours | 30 days | adjacent titles and missed naming variants |

Cadence is an operational target, not permission to poll. Relative labels such
as `2 hours ago` or `updated 5 days ago` are navigation signals and must not be
converted into canonical `posted_at`.

## Narrow route matrix

Visit in order:

| Priority | Route | Intent |
|---:|---|---|
| 1 | `/en/junior-frontend-dev-jobs` | core level and role |
| 2 | `/en/junior-frontend-dev-typescript-jobs` | core plus TypeScript |
| 3 | `/en/junior-frontend-dev-javascript-jobs` | core plus JavaScript |
| 4 | `/en/junior-frontend-dev-remote-jobs` | remote pass |
| 5 | `/en/frontend-dev-typescript-jobs-in-serbia` | Serbia plus TypeScript |
| 6 | `/frontend-dev-javascript-jobs-in-serbia` | Serbia plus JavaScript |

Add a Global/Europe/Serbia-compatible location pass where the visible UI makes
that state explicit. Preserve route, selected filters and sort state in the run
manifest.

## Broad route matrix

Use `/en/software-remote-jobs`, `/en/html-remote-jobs` and the generic
`/en/remote-jobs` surface with adjacent title families:

- web/UI/product/design/creative developer or engineer;
- frontend-heavy software engineer;
- CMS, content, commerce or marketing engineer;
- implementation/solutions/support roles only when the preview shows material
  web scope.

Do not set aggressive negative keywords. Apply skills and experience after the
broad title/category pass so incomplete card metadata does not hide candidates.

## Visible UI settings

- Confirm `newest` when the UI exposes it; do not infer sorting from relative
  dates alone.
- Prefer explicit role/title state over opaque AI ranking.
- Treat technology tags as inclusive signals, not exact requirements.
- Record Remote/Global/Europe as source filters, not candidate eligibility.
- Leave salary unset during discovery unless a separate coverage pass without
  salary is also run.

## Route scan and stop rule

For each route, scan in visible order, extract numeric IDs before opening, skip
known IDs, and preserve the exact `/jobs/<id>-<slug>` URL immediately. Exact-card
outcomes follow the universal lifecycle; they are not repeated here.

For a route with visibly confirmed newest sorting, stop after two consecutive
numbered pages or user-triggered scroll batches that both:

- contain no unseen numeric IDs; and
- contain only cards older than the pass window.

If sort, page boundaries or freshness are unclear, mark the route `incomplete`
and record the last visible page/batch instead of claiming coverage.

## Offline extraction contract

Extract only source-visible facts:

| Field | Rule |
|---|---|
| `source` | `Hirify` |
| `source_job_id` | numeric component of `/jobs/<id>-<slug>` |
| `source_url` | absolute exact URL without tracking |
| title/company/location | exact visible text; do not guess hidden company |
| freshness | preserve raw relative label; do not synthesize a date |
| source status | distinguish live, archived, soft-stale and unknown |
| original link | candidate route only until employer resolution |

Suggested parser outputs are read-only JSON artifacts containing records plus a
run manifest: route, filters, sort state, first/last visible ID, page/batch
count, source-status counts and incomplete reason.

## Current pipeline limitation

The current JSONL inbox requires exact `posted_at` and non-empty
`application_url`; Hirify often exposes neither reliably. Therefore:

- do not fabricate either field;
- do not write Hirify records into the current JSONL inbox contract;
- do not register a networked Hirify adapter in `config/sources.toml`;
- after permitted live Browser work, use immutable GitHub connector operations
  for repository writes;
- keep offline parser experiments as read-only artifacts.

Supporting Hirify in ingest requires an explicit raw-contract/schema change
with matching validation and tests.

## Validation

### Offline rule validation

Use sanitized fixtures for at least a normal card, archived card, soft-stale
card, hidden company, missing salary and relative freshness label. Verify stable
numeric extraction, tracking removal and no fabricated dates.

### Controlled live validation

Run one manual narrow pass and capture routes, filters, sort, IDs, depth and
incomplete reasons. Confirm that the checkout is unchanged until the normal
immutable write path is intentionally invoked. No contact reveal, sign-in
change, Save, Message or Apply submission is part of validation.
