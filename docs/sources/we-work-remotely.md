# We Work Remotely search playbook

Checked: 2026-08-13

Official/current references:

- [We Work Remotely jobs](https://weworkremotely.com/)
- [Remote programming jobs](https://weworkremotely.com/categories/remote-programming-jobs)

Common lifecycle, dedupe and write-path rules live in
[`README.md`](README.md). This file contains only We Work Remotely-specific
behavior. Use `WWR` below only as an abbreviation; the tracker source value
remains `We Work Remotely`.

## Role in the search layer

WWR is a remote-focused job board. It hosts exact job descriptions and usually
routes Apply to an employer site, ATS, form or email. The board is useful for
discovery, but its region labels do not override the employer's current listing
or application questions.

For tracker provenance:

- `source=We Work Remotely`;
- `source_url` = exact `/remote-jobs/<company>-<slug>` card;
- leave `source_job_id` empty unless a genuinely stable internal ID is exposed;
- `original_url` = verified exact employer careers/ATS job;
- if WWR is the only available posting, preserve it as provenance and leave
  first-party/Apply verification unknown until employer-side evidence exists.

Never use the homepage, category page or search results as an individual source
reference.

## Discovery strategy

Use WWR's search and filters in overlapping passes:

- role families and technology terms;
- categories such as Front End, Full Stack and Software Development;
- country/region filters;
- salary and skills only as later refinements;
- newest, 24-hour, one-week and two-week windows as separate recency passes.

Featured, boosted or `Top 100` placement affects visibility, not job fit or
listing freshness. Read the full exact card even when a title looks ideal: a
nominal React role can be predominantly backend or much more senior than its
preview suggests.

## Exact-card fields

Capture from the exact WWR page:

- title and company;
- posted date and any apply-before date;
- full description and requirements;
- job type, category, region and skills;
- the actual target of `Apply now`.

Dates and a visible Apply button are preliminary signals. A removed WWR job may
redirect to the homepage, while a still-rendered WWR page may point to a closed
employer requisition.

## Verify the Apply target

For every plausible job:

1. open the exact WWR card;
2. inspect the full role for hard blockers;
3. follow `Apply now` and identify ATS, employer form, third-party form or email;
4. confirm the target is exact to this role and currently accepts applications;
5. confirm employer identity and current job status elsewhere when the target is
   a generic form or email;
6. stop before submitting or sending anything.

An external form such as Google Forms can be a real application route, but it
does not by itself prove employer ownership. Corroborate the role through the
employer domain/profile before marking first-party verification complete.

## Geography traps

- `Anywhere in the World` is a WWR board label, not final proof of global
  eligibility.
- The external ATS can narrow a worldwide WWR card to one country or payroll
  region.
- Timezone overlap, work authorization and office travel may exist only in the
  description or form.
- A country list can be inclusive or merely describe preferred timezones; read
  the wording rather than mapping it mechanically.

The first-party card/form wins over the WWR label. If evidence conflicts or is
incomplete, use `remote_policy=Unclear` and leave a concrete next check.

## Dedupe traps

- WWR slugs can change after title edits.
- A repost can have a new WWR URL but the same external requisition.
- Several regional WWR cards may route to one employer job.
- A generic external application form may be reused across distinct roles.

Compare exact WWR URL, then resolved ATS URL/requisition, then company + role +
location. Do not use one generic form URL alone to merge distinct jobs.

## Connector checklist

- [ ] Several role/category and recency passes were searched.
- [ ] Exact `/remote-jobs/...` card, not a feed URL, was preserved.
- [ ] Full description was read for seniority and backend weight.
- [ ] `Apply now` target and employer ownership were verified.
- [ ] WWR region label was checked against the target form and description.
- [ ] Featured/boosted placement was not treated as fit or freshness.
- [ ] Every inspected exact job produced an immutable operation or duplicate
      source reference.
- [ ] No form or email was submitted.
