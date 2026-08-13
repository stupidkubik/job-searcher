# LinkedIn search playbook

Checked: 2026-08-13

Official references:

- [Filter and sort job search results](https://www.linkedin.com/help/linkedin/answer/a507441)
- [Apply for jobs on LinkedIn](https://www.linkedin.com/help/linkedin/answer/a512388)
- [Easy Apply limits](https://www.linkedin.com/help/linkedin/answer/a512348)

Common lifecycle, dedupe and write-path rules live in
[`README.md`](README.md). This file contains only LinkedIn-specific behavior.

## Role in the search layer

LinkedIn is a broad, signed-in discovery surface with personalized ordering. It
is not automatically the employer's first-party source. Use the visible UI and
exact job cards; do not call private endpoints, scrape around access controls or
automate application submission.

For tracker provenance:

- `source=LinkedIn`;
- normalize `source_url` to `https://www.linkedin.com/jobs/view/<id>/` and strip
  tracking parameters;
- `source_job_id` = numeric LinkedIn job ID;
- `original_url` = verified employer careers/ATS listing when one exists.

## Discovery strategy

Use separate query passes for role families and locations. Combine LinkedIn's
documented filters deliberately:

- Date posted: recent first, then one-week and one-month fallback;
- location: Serbia, Europe and explicitly remote-compatible markets;
- experience level and employment type;
- company or network filters when validating a lead;
- Easy Apply only as a separate pass, not as a universal quality filter;
- under-10-applicants or similar signals only for ordering.

Because results are personalized and capped, vary the keywords instead of
assuming one result set is exhaustive. Preserve exact cards before exploring
company pages or related jobs.

## Exact-card verification

For each plausible card:

1. capture the numeric ID and normalized exact URL;
2. read the complete description, including location and applicant screening;
3. identify the actual hiring employer, not only the poster or recruiting
   intermediary;
4. follow `Apply` to the employer/ATS and resolve the exact requisition;
5. check the employer's current board for the same job and nearby variants;
6. verify the visible Apply route without submitting it.

If LinkedIn shows `Easy Apply`, the application stays inside LinkedIn. The
button's presence alone does not prove employer-side listing freshness or allow
`first_party_verified=yes`. Do not claim verified first party merely because the
company page or poster looks legitimate.

## Easy Apply and external actions

LinkedIn documents two distinct routes:

- `Apply` redirects to a company website or external job board;
- `Easy Apply` submits inside LinkedIn.

For this repository:

- opening and reading the form is verification work;
- saving a job, messaging, following a company and submitting are external
  writes and require explicit user intent;
- never click the final Submit button;
- do not set `application_status=applied` without the user's confirmation;
- if no first-party listing can be established, keep verification fields
  unknown instead of promoting the LinkedIn card to `original_url` by default.

LinkedIn also enforces Easy Apply limits and discourages automated or bot-like
activity. Keep connector work read-only, paced and limited to visible product
flows.

## Geography and job-identity traps

- `Remote` commonly means remote within the card's listed market, not worldwide.
- One role may be reposted as several location-specific LinkedIn IDs.
- Staffing firms and confidential employers can obscure the true employer.
- Promoted or reposted labels are ranking/distribution signals, not freshness
  proof.
- A current LinkedIn card may lead to an expired ATS page; the first-party state
  wins.
- An old LinkedIn ID can be absent while an employer has a newly issued ID for
  the same requisition.

Inspect the description and first-party form for country eligibility, work
authorization, timezone and office requirements. Use `remote_policy=Unclear`
when the constraints remain ambiguous.

## Dedupe rules

Deduplicate in this order:

1. numeric LinkedIn job ID;
2. resolved exact ATS/careers URL and requisition ID;
3. existing LinkedIn source URLs;
4. normalized employer + role + location.

Different LinkedIn IDs that resolve to the same first-party requisition are
source references to one canonical job. Do not merge separate employer
requisitions solely because their titles match.

## Connector checklist

- [ ] Search used the signed-in visible UI and documented filters.
- [ ] Exact numeric ID and tracking-free URL were stored.
- [ ] Personalized ranking was not treated as exhaustive coverage.
- [ ] Actual employer and exact first-party listing were resolved where
      possible.
- [ ] Remote scope and work authorization came from full evidence.
- [ ] Easy Apply was not mistaken for first-party verification.
- [ ] Every inspected exact job produced an immutable operation or duplicate
      source reference.
- [ ] No Save, message, follow or application was submitted.
