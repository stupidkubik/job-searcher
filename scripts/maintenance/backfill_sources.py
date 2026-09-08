#!/usr/bin/env python3
"""One-time backfill: create `data/job_sources.csv` rows from the
`source`/`source_url` already recorded on each historical job in
`data/jobs.csv`.

docs/agent-write-path-plan-2026-09-07.md, Э9/G-12. `job_sources.csv`
provenance tracking (source + source_job_id / source_url dedup) was added
after most of the dataset already existed; this script is how that history
was backfilled once. It is idempotent (an existing reference is left alone)
but has no ongoing role, so it is intentionally not reachable from
`scripts/jobs.py --help` or the connector write path.
"""

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(ROOT / "scripts"))
import jobs  # noqa: E402


def legacy_duplicate_origin(row):
    match = re.search(r"\bjob-\d{4,}\b", row["notes"] or "")
    if not match:
        jobs.die(f"{row['id']}: legacy duplicate_listing has no origin id in notes")
    return match.group(0)


def backfill_source_references(job_rows, source_rows):
    prepared_rows = list(source_rows)
    summary = {"scanned": 0, "created": 0, "existing": 0, "legacy_redirects": 0, "shared_urls": 0}
    for job in job_rows:
        summary["scanned"] += 1
        if not job["source_url"]:
            continue
        job_id = job["id"]
        if job["decision_reason"] == "duplicate_listing":
            job_id = legacy_duplicate_origin(job)
            summary["legacy_redirects"] += 1
        reference = jobs.build_source_reference(job_id, job, job["found_at"])
        normalized = jobs.norm_url(reference["source_url"])
        shared_url = any(
            existing["source_url"] and jobs.norm_url(existing["source_url"]) == normalized
            and existing["job_id"] != job_id
            for existing in prepared_rows
        )
        reference, created = jobs.prepare_source_reference(prepared_rows, reference, force=True)
        if created:
            prepared_rows.append(reference)
            summary["created"] += 1
            if shared_url:
                summary["shared_urls"] += 1
        else:
            summary["existing"] += 1
    return prepared_rows, summary


def print_backfill_summary(summary, changed):
    mode = "check" if not changed else "backfill applied"
    print(f"source references: {mode}")
    print(f"jobs scanned: {summary['scanned']}")
    print(f"references created: {summary['created']}")
    print(f"references already existed: {summary['existing']}")
    print(f"legacy duplicate redirects: {summary['legacy_redirects']}")
    print(f"shared discovery urls explicitly allowed: {summary['shared_urls']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="report the backfill without writing it")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    job_rows = jobs.load()
    source_rows = jobs.load_job_sources(allow_missing=True)
    new_source_rows, summary = backfill_source_references(job_rows, source_rows)
    jobs.ensure_dataset_valid(job_rows, new_source_rows)
    if args.format == "json":
        if not args.check:
            jobs.save_job_sources(new_source_rows)
        print(json.dumps({
            "ok": True,
            "command": "backfill-sources",
            "mode": "check" if args.check else "apply",
            "summary": summary,
            "saved": not args.check,
        }, ensure_ascii=False, sort_keys=True))
        return 0
    print_backfill_summary(summary, changed=not args.check)
    if args.check:
        print("data/job_sources.csv not changed")
        return 0
    jobs.save_job_sources(new_source_rows)
    print("data/job_sources.csv atomically updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
