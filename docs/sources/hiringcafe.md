# HiringCafe search playbook

Checked: 2026-08-13

Official/current references:

- [HiringCafe job search](https://hiringcafe.com/)
- [Frontend Engineer jobs](https://hiringcafe.com/jobs/frontend-engineer)

Common lifecycle, dedupe and write-path rules live in
[`README.md`](README.md). This file contains only HiringCafe-specific behavior.

## Role in the search layer

HiringCafe is a broad job-search aggregator with detailed normalized filters and
job summaries. Use it to generate candidates and locate the external `Job
Posting`; verify every result on the employer careers page or ATS.

For tracker provenance:

- `source=HiringCafe`;
- `source_url` = exact HiringCafe job card after normalizing the current
  `hiringcafe.com`/legacy `hiring.cafe` redirect;
- preserve a source job ID only when the exact card exposes a stable opaque ID;
  never derive one from a search query or mutable title slug;
- `original_url` = verified exact employer/ATS listing.

HiringCafe is never `original_url` merely because its card is detailed or its
external button is labelled `Job Posting`.

## Discovery strategy

Start with broad role and location passes, then use the platform's filters to
rank results. Useful current filter groups include:

- Date Posted and Apply Process;
- Departments and Job Titles & Keywords;
- Experience and Commitment;
- Salary and Benefits;
- Languages, Education, Licenses and Security Clearance;
- Company, Industry, Stage & Funding, Size and Founding Year;
- Shifts, Travel and encouraged-to-apply attributes.

Use Exclude Jobs only after broad discovery has been reviewed; an overly strict
exclusion can hide adjacent titles. Run recent narrow searches plus a wider
fallback. Search result pages and SEO landing pages are query surfaces, not
provenance for one job.

## What can be trusted

The exact card is useful for:

- locating an employer job posting;
- preliminary title, company, location and compensation screening;
- possible years-of-experience, skills, work environment and employment type;
- finding other current-looking jobs at the same employer.

Treat normalized summaries, experience estimates, technology tags, salary and
work-environment labels as extracted discovery data. Confirm every hard blocker
against the exact employer text or form before recording it as fact.

Likewise, an Apply Process filter describes the platform's classification of the
route. It does not prove the route is live, short or safe to submit.

## Resolve the employer posting

For every plausible exact card:

1. preserve the HiringCafe URL before following redirects;
2. open `Job Posting` and inspect its final URL;
3. reject generic employer homepages and search pages as incomplete resolution;
4. match title, company, location, description and requisition ID on the exact
   employer/ATS page;
5. open the visible Apply route and verify the exact role;
6. inspect the current employer board for closure or nearby roles.

If `Job Posting` lands on another aggregator, continue resolving the chain. If
no exact first-party listing can be found, keep the discovery record with
verification unknown and a specific next action.

## Geography and freshness traps

- `Remote` is not global remote; validate allowed countries, payroll, work
  authorization and timezone.
- Multiple location variants may represent one requisition or genuinely
  separate jobs.
- HiringCafe's date and live-looking card can outlast the employer listing.
- The same employer role can be indexed from more than one URL.
- A redirect from the legacy domain may change URL shape; preserve the exact
  normalized card rather than a category/search destination.

The current first-party listing and application form determine open/closed and
eligibility. Use `remote_policy=Unclear` when the employer evidence is not
conclusive.

## Dedupe rules

Check, in order:

1. stable HiringCafe source ID when present;
2. normalized exact HiringCafe URL;
3. resolved employer/ATS URL and requisition ID;
4. normalized company + role + location.

Do not create separate canonical jobs for HiringCafe location cards that resolve
to the same requisition. Conversely, do not merge genuinely separate
requisitions solely because the title and description match.

## Connector checklist

- [ ] Broad queries preceded aggressive exclusions.
- [ ] Exact card URL, not an SEO/search page, was preserved.
- [ ] Normalized summaries and AI/extracted fields were treated as provisional.
- [ ] `Job Posting` resolved to an exact employer/ATS listing.
- [ ] Apply, geography and work authorization were verified independently.
- [ ] Location variants were checked against the first-party requisition.
- [ ] Every inspected exact job produced an immutable operation or duplicate
      source reference.
- [ ] No application or external form was submitted.
