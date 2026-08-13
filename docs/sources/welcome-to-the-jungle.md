# Welcome to the Jungle search playbook

Checked: 2026-08-13

Official/current references:

- [Welcome to the Jungle jobs](https://www.welcometothejungle.com/en/jobs)
- [Welcome to the Jungle](https://www.welcometothejungle.com/)

Common lifecycle, dedupe and write-path rules live in
[`README.md`](README.md). This file contains only Welcome to the
Jungle-specific behavior. Use `WTTJ` below only as an abbreviation; the tracker
source value remains `Welcome to the Jungle`.

## Role in the search layer

WTTJ combines European job discovery, employer profiles and both native and
external application routes. Search and recommendations can be influenced by a
signed-in profile, so explicit filters and multiple query families are required.
Its native form is application-route evidence, but not a replacement for the
repository's official employer careers/ATS verification.

For tracker provenance:

- `source=Welcome to the Jungle`;
- `source_url` = exact WTTJ job card, not the search or company page;
- if an `app.welcometothejungle.com/jobs/<opaque-id>` URL is available, preserve
  that opaque ID as `source_job_id`;
- otherwise rely on the normalized exact public job URL and do not invent an ID
  from a mutable slug;
- `original_url` = exact employer careers/ATS listing only;
- if the only route is native WTTJ, leave first-party/Apply verification unknown
  until official employer-side evidence is found.

Public cards commonly use a localized path such as
`/<locale>/companies/<company>/jobs/<slug>`. Normalize tracking and locale
redirects consistently, but do not collapse different job cards merely because
their slugs look similar.

## Discovery strategy

Run explicit role and geography passes with the available filters:

- role families and adjacent titles;
- contract type;
- location and remote level;
- compensation when available;
- recent results first, followed by a wider fallback window.

Repeat important searches in relevant language/locale variants when titles may
be localized. Treat recommendations as an additional lead source, never the
complete result set.

An interesting job card is also an entry point to the employer's `View all
jobs` page. Inspect nearby current roles, but record and verify each exact job
separately.

## Read the exact card

WTTJ cards may expose structured details such as:

- remote policy and location;
- contract type and start date;
- salary;
- whether a resume or cover letter is mandatory;
- role description and preferred experience;
- recruitment process;
- company profile and related jobs.

These are useful screening inputs, not substitutes for a current application
route. A polished company profile or complete job description can remain visible
after the employer has removed the underlying ATS requisition.

## Resolve native versus external Apply

For each candidate:

1. open the exact WTTJ card and its Apply control;
2. determine whether the flow stays in WTTJ or redirects externally;
3. for an external flow, resolve and verify the exact employer/ATS requisition;
4. for a native flow, confirm the form visibly accepts the exact role;
5. stop before any final submission or account mutation;
6. check the employer's current jobs page for closure evidence and adjacent
   openings.

A working native WTTJ form does not by itself allow `apply_verified=yes`, because
that tracker state requires verified first party. Preserve the route in
provenance/notes and leave a concrete employer-verification next action.

If an old WTTJ card points to a 404/410 or missing ATS requisition, the current
first-party state wins. Record the closed outcome even if WTTJ still renders the
description.

## Geography traps

- `Fully remote` describes work arrangement, not necessarily eligible countries.
- A location filter can reflect office location while the description imposes a
  different residence or timezone requirement.
- Localized pages do not imply eligibility in that locale.
- Contract, payroll, visa and work-authorization requirements can appear only in
  the description or application form.

Use `remote_policy=Unclear` until country scope is explicit enough to classify.

## Dedupe traps

- `app.` and public localized URLs can represent the same WTTJ job.
- The same requisition can appear in several locales.
- A stale WTTJ card can coexist with a newer ATS repost.
- Similar cards for different offices may or may not be one requisition.

Compare opaque WTTJ ID when present, then resolved exact first-party URL and
requisition, then normalized company + role + location. Preserve redirects and
locale variants as references rather than separate canonical jobs when identity
is confirmed.

## Connector checklist

- [ ] Explicit filters and several role/locale passes were used.
- [ ] Exact job URL and opaque app ID, when present, were preserved.
- [ ] Personalized recommendations were not treated as exhaustive.
- [ ] Native versus external Apply route was identified.
- [ ] Employer/ATS listing won over a stale WTTJ card.
- [ ] `Fully remote` was not equated with worldwide eligibility.
- [ ] Every inspected exact job produced an immutable operation or duplicate
      source reference.
- [ ] No application or account-changing action was submitted.
