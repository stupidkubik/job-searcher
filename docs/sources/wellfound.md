# Wellfound search playbook

Checked: 2026-08-13

Official references:

- [Set up a job search](https://help.wellfound.com/article/777-setting-up-a-search)
- [Apply to a job](https://help.wellfound.com/article/769-how-do-i-apply-to-a-job)
- [Frontend Engineer jobs](https://wellfound.com/role/r/frontend-engineer)

Common lifecycle, dedupe and write-path rules live in
[`README.md`](README.md). This file contains only Wellfound-specific behavior.

## Role in the search layer

Wellfound is a startup-focused job board and can also be the native application
surface. Unlike a pure aggregator, it can accept an application without an
external ATS, but the repository still requires an official employer
careers/ATS URL for first-party verification.

For tracker provenance:

- `source=Wellfound`;
- `source_url` = exact `/jobs/<id>-<slug>` card;
- `source_job_id` = numeric `<id>` from that path;
- use only an exact employer careers/ATS URL as `original_url`;
- if the only route is native Wellfound, keep `original_url` empty and
  first-party/Apply verification unknown until employer-side evidence exists.

Do not use a role search page, company profile or recommendations feed as the
individual job URL.

## Discovery strategy

Wellfound search supports roles, multiple locations, compensation/equity, job
type, experience, company stage/size and keyword matching over job and company
content. Use this in layers:

1. broad role families and synonyms;
2. Serbia, Europe and remote-compatible location passes;
3. relevant experience bands and full-time/contract passes;
4. compensation and company-stage filters as ranking, not early hard gates;
5. a separate pass that includes jobs without disclosed salary.

A salary filter can exclude jobs with no published range. Keep a no-salary pass
so missing compensation is not confused with low compensation.

## Read the exact card

Capture and distinguish:

- title, company and actual role description;
- posting age and recruiter/company activity signals;
- remote scope and eligible regions;
- cash salary versus equity;
- required experience and skills;
- visa sponsorship and work authorization;
- employment type, including internship or unpaid work;
- native Apply form versus external redirect.

Badges such as `Actively Hiring`, response rates or response-time labels help
prioritize outreach. They are not proof that one exact listing is current.

## Remote and compensation traps

- `Remote only · Everywhere` is a strong Wellfound discovery signal, but still
  check the description and form for country, payroll and timezone exclusions.
- `Remote · <city>` normally carries a location constraint and is not global.
- Salary and equity are separate components; do not combine them into one cash
  figure.
- A displayed range can be location-dependent or omit the contract currency and
  period.
- Old cards can retain an Apply button long after posting, so age plus button
  presence is not enough to establish current employer intent.

If remote eligibility or pay basis is ambiguous, preserve the exact text in
notes and use the corresponding unknown/unclear tracker value.

## Verify listing and Apply

For a native Wellfound route:

1. confirm the exact card still loads as a job, not a generic role page;
2. confirm company identity and the full role description;
3. open Apply far enough to establish that the form accepts this job;
4. stop before `Send Application`;
5. check the company profile or official careers page for closure evidence and
   adjacent roles.

A working native form is useful application-route evidence but does not by
itself satisfy this repository's first-party invariant. Do not set
`apply_verified=yes`, which requires `first_party_verified=yes`, until the
official employer listing has also been established.

For an external route, follow it to the exact employer/ATS listing and apply the
normal first-party verification workflow.

Wellfound says applications include the candidate profile and optional note and
cannot simply be undone. The connector must not apply, send a note, save or
otherwise mutate account state without explicit user instruction. Even with an
instruction, the repository agent never submits the final application itself.

## Dedupe traps

- A company can repost the same role under a new Wellfound numeric ID.
- External ATS and native Wellfound cards may describe one requisition.
- Similar startup names and stealth companies can cause false company matches.
- Several location variants may share one description but differ in eligibility.

Check numeric source ID first, then verified external URL/requisition, then
company + role + location. Preserve each confirmed discovery reference on the
one canonical job.

## Connector checklist

- [ ] Search included broad roles, geo variants and jobs without salary.
- [ ] Exact numeric ID and job-card URL were preserved.
- [ ] Cash, equity and employment type were read separately.
- [ ] Remote eligibility came from the full card/form, not one badge.
- [ ] Native versus external Apply route was identified.
- [ ] An old card or activity badge was not treated as freshness proof.
- [ ] Every inspected exact job produced an immutable operation or duplicate
      source reference.
- [ ] No Apply, Send Application, note or Save action was performed.
