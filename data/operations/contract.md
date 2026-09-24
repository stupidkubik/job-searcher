# Operation field contract

> Generated from `scripts/agent_operations.py` and `scripts/jobs.py` by `python3 scripts/agent_operations.py render-contract`. Do not edit manually.

This is the single source of truth for which connector command accepts which field. It is assembled from the same allowlists the runner enforces, so it cannot drift silently from actual validation. See [`README.md`](README.md) for the full request/result contract.

## `add`

| Field | Type | Allowed values | Required | Note |
| --- | --- | --- | --- | --- |
| `application_status` | enum | `not_started`, `reviewing` | no |  |
| `apply_verified` | enum | `yes`, `no`, `unknown` | no |  |
| `company` | text | — | yes |  |
| `decision_reason` | enum | `already_applied`, `closed_before_application`, `company_not_interesting`, `geo_restriction`, `other`, `role_not_frontend`, `salary_too_low`, `seniority_too_high`, `seniority_too_low`, `stack_mismatch`, `work_authorization` | no |  |
| `duplicate_of` | job-NNNN | — | no | attaches a new source reference to an existing job instead of creating one |
| `first_party_verified` | enum | `yes`, `no`, `unknown` | no |  |
| `force` | boolean | — | no | explicitly resolves a fuzzy duplicate candidate or a shared discovery URL |
| `found_at` | date (YYYY-MM-DD) | — | no |  |
| `level` | enum | `Intern`, `Graduate`, `Junior`, `Junior+`, `Associate`, `Junior/Middle`, `Middle`, `Senior`, `Lead`, `Unknown` | no |  |
| `listing_status` | enum | `open`, `closed`, `unknown` | no |  |
| `location` | text | — | no |  |
| `match_score` | number (1-10) | — | no | decimal values are allowed, e.g. 7.5 |
| `notes` | text | — | no | single line; long context belongs in applications/<id>.md |
| `original_url` | URL | — | no |  |
| `posted_at` | date (YYYY-MM-DD) | — | no |  |
| `remote_policy` | enum | `Global`, `Europe`, `EMEA`, `Serbia`, `Country-specific`, `Hybrid`, `On-site`, `Unclear` | no | a bare "Remote" with no country list is not a valid value; use Unclear |
| `role` | text | — | yes |  |
| `salary` | text | — | no |  |
| `source` | enum | `Hirify`, `Jaabz`, `LinkedIn`, `Welcome to the Jungle`, `We Work Remotely`, `HiringCafe`, `Hacker News — Who is Hiring?`, `Hacker News — Who Wants to Be Hired?`, `YC Work at a Startup`, `Wellfound`, `HelloWorld.rs`, `Reactiflux Discord`, `Find My Remote / Telegram`, `Telegram`, `Himalayas`, `Startit Jobs`, `Hired Valley`, `Relocate.me`, `Remote OK`, `Geekjob`, `TalentMove`, `Company Careers`, `Referral`, `Manual`, `Other` | yes |  |
| `source_job_id` | text | — | no |  |
| `source_url` | URL | — | no |  |
| `stack` | text | — | no |  |

## `add` with `duplicate_of`

A duplicate add only attaches a new source reference to an existing job; any canonical field beside the ones below is rejected (`duplicate_add_extra_fields`).

| Field | Type | Allowed values | Required | Note |
| --- | --- | --- | --- | --- |
| `company` | text | — | yes |  |
| `duplicate_of` | job-NNNN | — | no | attaches a new source reference to an existing job instead of creating one |
| `force` | boolean | — | no | explicitly resolves a fuzzy duplicate candidate or a shared discovery URL |
| `found_at` | date (YYYY-MM-DD) | — | no |  |
| `role` | text | — | yes |  |
| `source` | enum | `Hirify`, `Jaabz`, `LinkedIn`, `Welcome to the Jungle`, `We Work Remotely`, `HiringCafe`, `Hacker News — Who is Hiring?`, `Hacker News — Who Wants to Be Hired?`, `YC Work at a Startup`, `Wellfound`, `HelloWorld.rs`, `Reactiflux Discord`, `Find My Remote / Telegram`, `Telegram`, `Himalayas`, `Startit Jobs`, `Hired Valley`, `Relocate.me`, `Remote OK`, `Geekjob`, `TalentMove`, `Company Careers`, `Referral`, `Manual`, `Other` | yes |  |
| `source_job_id` | text | — | no |  |
| `source_url` | URL | — | no |  |

## `verify`

| Field | Type | Allowed values | Required | Note |
| --- | --- | --- | --- | --- |
| `application_status` | enum | `apply` | no |  |
| `apply_verified` | enum | `yes`, `no` | yes |  |
| `decision_reason` | enum | `already_applied`, `closed_before_application`, `company_not_interesting`, `geo_restriction`, `other`, `role_not_frontend`, `salary_too_low`, `seniority_too_high`, `seniority_too_low`, `stack_mismatch`, `work_authorization` | no |  |
| `first_party_verified` | enum | `yes`, `no` | yes |  |
| `level` | enum | `Intern`, `Graduate`, `Junior`, `Junior+`, `Associate`, `Junior/Middle`, `Middle`, `Senior`, `Lead`, `Unknown` | no |  |
| `listing_status` | enum | `open`, `closed` | yes |  |
| `match_score` | number (1-10) | — | no | decimal values are allowed, e.g. 7.5 |
| `next_action` | text | — | no |  |
| `next_action_date` | date (YYYY-MM-DD) | — | no |  |
| `notes` | text | — | no | single line; long context belongs in applications/<id>.md |
| `original_url` | URL | — | no |  |
| `remote_policy` | enum | `Global`, `Europe`, `EMEA`, `Serbia`, `Country-specific`, `Hybrid`, `On-site`, `Unclear` | no | a bare "Remote" with no country list is not a valid value; use Unclear |
| `salary` | text | — | no |  |
| `stack` | text | — | no |  |

## `screen`

| Field | Type | Allowed values | Required | Note |
| --- | --- | --- | --- | --- |
| `decision_reason` | enum | `already_applied`, `company_not_interesting`, `geo_restriction`, `other`, `role_not_frontend`, `salary_too_low`, `seniority_too_high`, `seniority_too_low`, `stack_mismatch`, `work_authorization` | yes |  |
| `notes` | text | — | no | single line; long context belongs in applications/<id>.md |

## `set`

At least one field is required.

| Field | Type | Allowed values | Required | Note |
| --- | --- | --- | --- | --- |
| `listing_status` | enum | `closed` | no | allowed only after a human application already exists |
| `next_action` | text | — | no |  |
| `next_action_date` | date (YYYY-MM-DD) | — | no |  |

## `status`

| Field | Type | Allowed values | Required | Note |
| --- | --- | --- | --- | --- |
| `application_status` | enum | `not_started`, `reviewing`, `apply`, `applied`, `interviewing`, `offer`, `rejected`, `ghosted`, `withdrawn` | yes |  |
| `applied_at` | date (YYYY-MM-DD) | — | no |  |
| `confirmed_by_user` | boolean | — | yes | must be the literal boolean true; set only after the human reports or requests the event |
| `cv_version` | text | — | no |  |
| `decision_reason` | enum | `no_response_timeout`, `withdrawn_by_me` | no |  |
| `next_action` | text | — | no |  |
| `next_action_date` | date (YYYY-MM-DD) | — | no |  |
| `notes` | text | — | no | single line; long context belongs in applications/<id>.md |
| `response_at` | date (YYYY-MM-DD) | — | no |  |
| `stage` | enum | `None`, `Applied`, `Recruiter screen`, `Tech interview`, `Test task`, `Final interview`, `Offer` | no | stage_reached only increases; a lower stage is rejected |

## `event` (single operation only; gated until v3 cutover)

The trusted runner supplies `event_id` from `operation_id`, `recorded_at`, `source=connector`, `actor=user` and `job_id`. An event is never a batch child. Production writes require the separate v3 cutover flag.

| Field | Type | Allowed values | Required | Note |
| --- | --- | --- | --- | --- |
| `confirmed_by_user` | boolean | — | yes | must be the literal boolean true; set only after the human reports or requests the event |
| `event_type` | enum | `acknowledgement_received`, `application_submitted`, `assessment_completed`, `assessment_invited`, `candidate_withdrew`, `event_voided`, `follow_up_sent`, `interview_cancelled`, `interview_completed`, `interview_scheduled`, `no_response_closed`, `offer_received`, `rejection_received`, `response_received` | yes | closed v1 taxonomy; see docs/tracker-v3/event-contract-v1.md |
| `evidence_ref` | single-line reference or null | — | no |  |
| `occurred_at` | date, aware instant or null (per precision) | — | yes |  |
| `payload` | object (exact keys depend on event_type) | — | yes | exact type-specific object; arbitrary keys are rejected |
| `precision` | enum | `date`, `instant`, `unknown` | yes |  |
| `supersedes` | earlier event_id or null | — | no |  |

## Batch child: `add` (with `client_ref`)

Same `args` as `add` above, addressed by `client_ref` instead of `job_id`/`expected`.

| Field | Type | Allowed values | Required | Note |
| --- | --- | --- | --- | --- |
| `application_status` | enum | `not_started`, `reviewing` | no |  |
| `apply_verified` | enum | `yes`, `no`, `unknown` | no |  |
| `client_ref` | text (caller-assigned, unique per request) | — | yes | maps this child's assigned job_id back to the caller inside the result |
| `company` | text | — | yes |  |
| `decision_reason` | enum | `already_applied`, `closed_before_application`, `company_not_interesting`, `geo_restriction`, `other`, `role_not_frontend`, `salary_too_low`, `seniority_too_high`, `seniority_too_low`, `stack_mismatch`, `work_authorization` | no |  |
| `duplicate_of` | job-NNNN | — | no | attaches a new source reference to an existing job instead of creating one |
| `first_party_verified` | enum | `yes`, `no`, `unknown` | no |  |
| `force` | boolean | — | no | explicitly resolves a fuzzy duplicate candidate or a shared discovery URL |
| `found_at` | date (YYYY-MM-DD) | — | no |  |
| `level` | enum | `Intern`, `Graduate`, `Junior`, `Junior+`, `Associate`, `Junior/Middle`, `Middle`, `Senior`, `Lead`, `Unknown` | no |  |
| `listing_status` | enum | `open`, `closed`, `unknown` | no |  |
| `location` | text | — | no |  |
| `match_score` | number (1-10) | — | no | decimal values are allowed, e.g. 7.5 |
| `notes` | text | — | no | single line; long context belongs in applications/<id>.md |
| `original_url` | URL | — | no |  |
| `posted_at` | date (YYYY-MM-DD) | — | no |  |
| `remote_policy` | enum | `Global`, `Europe`, `EMEA`, `Serbia`, `Country-specific`, `Hybrid`, `On-site`, `Unclear` | no | a bare "Remote" with no country list is not a valid value; use Unclear |
| `role` | text | — | yes |  |
| `salary` | text | — | no |  |
| `source` | enum | `Hirify`, `Jaabz`, `LinkedIn`, `Welcome to the Jungle`, `We Work Remotely`, `HiringCafe`, `Hacker News — Who is Hiring?`, `Hacker News — Who Wants to Be Hired?`, `YC Work at a Startup`, `Wellfound`, `HelloWorld.rs`, `Reactiflux Discord`, `Find My Remote / Telegram`, `Telegram`, `Himalayas`, `Startit Jobs`, `Hired Valley`, `Relocate.me`, `Remote OK`, `Geekjob`, `TalentMove`, `Company Careers`, `Referral`, `Manual`, `Other` | yes |  |
| `source_job_id` | text | — | no |  |
| `source_url` | URL | — | no |  |
| `stack` | text | — | no |  |

## Batch child: existing job (`screen` / `verify` / `set` / `status`)

Every non-`add` batch child carries `job_id` and a non-empty `expected` optimistic lock in addition to its command-specific `args` (see the matching section above).

| Field | Type | Allowed values | Required | Note |
| --- | --- | --- | --- | --- |
| `expected` | object (subset of canonical fields, non-empty) | — | yes | optimistic lock; must include last_update and the fields the decision depends on |
| `job_id` | job-NNNN | — | yes | must match job-NNNN and already exist |

## Fields no command accepts

Written only by the runner, never by a connector command: `contact_name`, `contact_url`, `cover_letter`, `id`, `last_update`, `stage_reached`, `verified_at`.

## Invariants across fields

- `first_party_verified=yes` requires a non-empty `original_url`.
- `apply_verified=yes` requires `first_party_verified=yes`.
- `listing_status=closed` before an application requires `decision_reason=closed_before_application`.
- `application_status=apply` requires a passed open verification and a non-empty `next_action`.

## Canonical enum values (reference)

| Field | Values |
| --- | --- |
| `application_status` | `not_started`, `reviewing`, `apply`, `applied`, `interviewing`, `offer`, `rejected`, `ghosted`, `withdrawn` |
| `listing_status` | `open`, `closed`, `unknown` |
| `first_party_verified` | `yes`, `no`, `unknown` |
| `apply_verified` | `yes`, `no`, `unknown` |
| `stage_reached` | `None`, `Applied`, `Recruiter screen`, `Tech interview`, `Test task`, `Final interview`, `Offer` |
| `level` | `Intern`, `Graduate`, `Junior`, `Junior+`, `Associate`, `Junior/Middle`, `Middle`, `Senior`, `Lead`, `Unknown` |
| `remote_policy` | `Global`, `Europe`, `EMEA`, `Serbia`, `Country-specific`, `Hybrid`, `On-site`, `Unclear` |
| `source` | `Hirify`, `Jaabz`, `LinkedIn`, `Welcome to the Jungle`, `We Work Remotely`, `HiringCafe`, `Hacker News — Who is Hiring?`, `Hacker News — Who Wants to Be Hired?`, `YC Work at a Startup`, `Wellfound`, `HelloWorld.rs`, `Reactiflux Discord`, `Find My Remote / Telegram`, `Telegram`, `Himalayas`, `Startit Jobs`, `Hired Valley`, `Relocate.me`, `Remote OK`, `Geekjob`, `TalentMove`, `Company Careers`, `Referral`, `Manual`, `Other` |
| `decision_reason` | `geo_restriction`, `work_authorization`, `seniority_too_high`, `seniority_too_low`, `stack_mismatch`, `role_not_frontend`, `salary_too_low`, `company_not_interesting`, `closed_before_application`, `already_applied`, `duplicate_listing`, `no_response_timeout`, `withdrawn_by_me`, `other` |
