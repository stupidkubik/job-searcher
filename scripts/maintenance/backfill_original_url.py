#!/usr/bin/env python3
"""One-time backfill: fill `original_url` for rows whose source already is
the first-party listing.

docs/agent-write-path-plan-2026-09-07.md, Э5/G-7(B). `original_url` is the
canonical dedup key and the field `first_party_verified=yes` depends on, but
281 rows shipped with it empty. For `source=Company Careers` the recorded
`source_url` already points at the employer's own ATS/careers page — the
`source` enum value means exactly that (see data/schema.md) — so it is safe
to copy it into `original_url` without a new verification pass. Every other
source is an aggregator or a discovery channel and is left untouched: its
`source_url` is where the listing was *found*, not necessarily the
first-party page.

This script never touches a row whose `original_url` is already non-empty,
so it is idempotent. It updates `last_update` on changed rows only, per the
data/schema.md invariant that last_update changes with every row update; it
does not touch `verified_at` or `first_party_verified`, since copying a URL
is not a new verification event.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(ROOT / "scripts"))
import jobs  # noqa: E402

# "Company Careers" is the only SOURCES value that denotes the employer's own
# careers/ATS page rather than an aggregator or discovery channel (see the
# `source` row in data/schema.md). Extend this set only for a future source
# with the same first-party meaning.
FIRST_PARTY_SOURCES = {"Company Careers"}


def rows_to_backfill(rows):
    return [
        row
        for row in rows
        if not row.get("original_url", "").strip()
        and row.get("source") in FIRST_PARTY_SOURCES
        and row.get("source_url", "").strip()
    ]


def run(dry_run):
    rows = jobs.load()
    targets = rows_to_backfill(rows)
    changed = []
    for row in targets:
        row["original_url"] = row["source_url"]
        row["last_update"] = jobs.today()
        changed.append({"id": row["id"], "original_url": row["original_url"]})
    if changed and not dry_run:
        jobs.ensure_dataset_valid(rows, jobs.load_job_sources(allow_missing=True), emit_warnings=False)
        jobs.save(rows)
    return changed


def print_text(changed, dry_run):
    if not changed:
        print("no rows need an original_url backfill")
        return
    verb = "would backfill" if dry_run else "backfilled"
    for entry in changed:
        print(f"{verb}: {entry['id']}  original_url={entry['original_url']}")
    print(f"\n{len(changed)} row(s) {'would be ' if dry_run else ''}changed")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--dry-run", action="store_true", help="report what would change without writing it")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    changed = run(args.dry_run)
    if args.format == "json":
        print(json.dumps({"dry_run": args.dry_run, "changed": changed}, ensure_ascii=False, sort_keys=True))
    else:
        print_text(changed, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
