# Roadmap

## Implemented

- Canonical `data/jobs.csv`, source provenance, application cards and safe
  writes through `scripts/jobs.py`.
- v2 data model: separate listing/application lifecycle, validation, structured
  input, source registry, inbox/ingest, Himalayas adapter, `todo`, `stale`,
  stats and reports.
- Browser-first generated view: [`tracker.md`](tracker.md) with an exact
  freshness gate in CI.
- GitHub connector gateway: immutable requests, trusted runner, immutable
  results and review/direct delivery modes.

The implementation plan and its accepted decisions remain in
[`tracker-v2-plan.md`](tracker-v2-plan.md); it is now an implementation record,
not a queue of unstarted phases. The browser-view specification is preserved in
[`tracker-browser-view-plan.md`](tracker-browser-view-plan.md).

## Next, only after a concrete need

- Design a versioned connector v2 only if manifest repetition or stale-operation
  conflicts become an observed burden. Preserve v1 compatibility while
  considering filename-derived operation identity, inherent batch atomicity and
  a stronger revision token.
- Add source adapters or optional analytics after a source demonstrates stable
  value and verification quality.

## Later, only after a confirmed need

- an interactive UI beyond the existing Markdown browser view;
- SQLite/Postgres;
- GitHub Issues как intake layer;
- автоматическая отправка заявок.

These items do not supersede the current CSV + Markdown + Git audit trail.
