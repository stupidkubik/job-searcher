# Hirify search playbook

Checked: 2026-08-13

Official/current references:

- [Hirify jobs](https://hirify.me/en/remote-jobs)
- [Software jobs](https://hirify.me/en/software-remote-jobs)
- [HTML jobs](https://hirify.me/en/html-remote-jobs)

Common lifecycle, dedupe and write-path rules live in
[`README.md`](README.md). This file contains only Hirify-specific behavior.

Deterministic route, filter, extraction and validation settings are defined in
[`hirify-discovery-rules.md`](hirify-discovery-rules.md). The observed technical
surface and automation boundary are documented separately in
[`hirify-technical-discovery.md`](hirify-technical-discovery.md).

## Role in the search layer

Hirify is a discovery aggregator. Use its filters, categories, tags and AI
search to find candidates, then resolve every promising result to an exact
employer careers page or ATS card before full analysis.

For tracker provenance:

- `source=Hirify`;
- `source_url` = exact Hirify `/jobs/<id>-<slug>` card, never a feed or search
  page;
- `source_job_id` = numeric `<id>` from that path;
- `original_url` = verified exact employer/ATS listing, not the Hirify card.

Do not replace `source=Hirify` with the ATS name reached later. The pair records
both discovery provenance and first-party verification.

## Discovery strategy

Run several overlapping searches rather than one strict query:

1. role families: frontend, front-end, UI engineer, web engineer, JavaScript,
   TypeScript and React;
2. adjacent categories such as Software and HTML;
3. location passes for Global, Europe and Serbia-compatible remote work;
4. experience and work-format filters only after a broad pass;
5. recent results first, followed by a wider fallback window.

Open each plausible exact card immediately and preserve its numeric ID. A
generic category page can reorder, refresh or stop showing the same job.

Avoid aggressive negative keywords during discovery. A relevant frontend role
may mention backend tools in the preview; determine backend weight from the full
description.

## What can be trusted

The exact Hirify card is useful for:

- stable source identity from the numeric URL;
- the description as captured by Hirify;
- discovery metadata such as title, company label, work format, employment type
  and technology tags;
- a preliminary archived/live signal.

It is not sufficient evidence for:

- a currently open employer listing;
- global eligibility or work authorization;
- authoritative salary, seniority or technology requirements;
- employer identity when the company is hidden or represented by an
  intermediary;
- a working application path.

Hirify may label metadata or calculate an AI score. Treat the score, extracted
tags and normalized location as ranking aids, not candidate or job facts.

## Resolve the first-party listing

For every card that survives the initial title/geo screen:

1. read the complete Hirify description and note any original application
   instructions, requisition ID or employer domain;
2. follow the visible source/contact route without signing up for paid features;
3. search the named employer's current careers board and common ATS hosts;
4. match title, location, description and requisition ID;
5. open the exact listing and visible Apply route;
6. record `original_url` only after that match succeeds.

A Telegram post, recruiter contact, generic company homepage, category page or
another aggregator is not a verified first-party listing. Continue resolution
or leave verification unknown.

## Status and Apply rules

- `This vacancy is archived` is enough to mark the Hirify source card archived,
  but check the employer board before concluding the canonical listing is
  closed.
- A live Hirify card with a future date does not prove the employer listing is
  open.
- A gated contact/source button is not `apply_verified=yes`.
- A first-party Apply button must reach an exact form or application page that
  visibly accepts the role.
- Do not sign in, reveal contacts, save, message or submit an application unless
  the user explicitly requests the corresponding external action.

If no exact first-party listing can be found, preserve the Hirify discovery row
and set a concrete verification `next_action`; do not invent `original_url`.

## Geography traps

`Remote (Global)` and similar Hirify labels remain source-side interpretations.
Inspect the full description and first-party form for:

- allowed and excluded countries;
- payroll/entity or contractor limitations;
- work authorization questions;
- timezone overlap;
- required office visits or relocation.

If those constraints cannot be established, use `remote_policy=Unclear` rather
than treating Global or Remote as proof.

## Dedupe traps

- The same employer job can appear with several titles or location variants.
- A repost can receive a new Hirify ID while resolving to the same ATS URL.
- Hidden-company cards can later resolve to an employer already in the tracker.
- The source displayed by Hirify may itself be another aggregator.

Always deduplicate the numeric Hirify ID first, then exact first-party URL, then
normalized company + role. A confirmed duplicate adds a Hirify source reference
to the existing canonical job; it does not create another job.

## Connector checklist

- [ ] Full `data/jobs.csv`, profile and existing source references were read.
- [ ] Several query families and geo passes were used.
- [ ] Exact `/jobs/<id>-<slug>` URL and numeric ID were preserved.
- [ ] AI score, tags and Remote label were treated as discovery metadata.
- [ ] Employer identity and exact first-party listing were resolved.
- [ ] Apply route, geography and work authorization were checked separately.
- [ ] Every inspected exact job produced an immutable operation or duplicate
      source reference.
- [ ] No application, contact reveal or message was sent.
