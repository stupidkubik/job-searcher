#!/usr/bin/env python3
"""One-time migration: rewrite a v1 `data/jobs.csv` (single `status` column)
into the v2 schema (`application_status` + `listing_status`).

docs/agent-write-path-plan-2026-09-07.md, Э9/G-12. The dataset has used the
v2 schema since the tracker-v2 migration; this script stays only as a
historical/disaster-recovery tool and is intentionally not reachable from
`scripts/jobs.py --help` or the connector write path.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(ROOT / "scripts"))
import jobs  # noqa: E402

V1_FIELDS = [
    "id",
    "status",
    "company",
    "role",
    "level",
    "original_url",
    "source_url",
    "source",
    "location",
    "remote_policy",
    "stack",
    "salary",
    "posted_at",
    "found_at",
    "match_score",
    "stage_reached",
    "decision_reason",
    "applied_at",
    "response_at",
    "next_action",
    "next_action_date",
    "cv_version",
    "cover_letter",
    "contact_name",
    "contact_url",
    "last_update",
    "notes",
]
V1_LEGACY_FIELDS = [
    "id",
    "company",
    "role",
    "level",
    "original_url",
    "source_url",
    "source",
    "location",
    "remote_policy",
    "stack",
    "salary",
    "posted_at",
    "found_at",
    "match_score",
    "status",
    "stage_reached",
    "decision_reason",
    "applied_at",
    "response_at",
    "next_action",
    "next_action_date",
    "cv_version",
    "cover_letter",
    "contact_name",
    "contact_url",
    "last_update",
    "notes",
]
V1_STATUS_MAPPING = {
    "New": ("not_started", "unknown"),
    "Reviewing": ("reviewing", "unknown"),
    "Apply": ("apply", "unknown"),
    "Applied": ("applied", "unknown"),
    "Interviewing": ("interviewing", "unknown"),
    "Offer": ("offer", "unknown"),
    "Rejected": ("rejected", "unknown"),
    "Ghosted": ("ghosted", "unknown"),
    "Skipped": ("not_started", "unknown"),
    "Closed": ("not_started", "closed"),
    "Duplicate": ("not_started", "unknown"),
    "Withdrawn": ("withdrawn", "unknown"),
}


def load_v1():
    header, rows = jobs.read_csv()
    if tuple(header or []) not in {tuple(V1_FIELDS), tuple(V1_LEGACY_FIELDS)}:
        if header == jobs.FIELDS:
            jobs.die("jobs.csv already uses the v2 schema; migrate-v2 is not needed")
        jobs.die("jobs.csv header is not a supported v1 schema")
    return rows


def migrate_v1_rows(rows):
    migrated = []
    for line, legacy in enumerate(rows, start=2):
        status = legacy.get("status") or ""
        if status not in V1_STATUS_MAPPING:
            jobs.die(f"row {line}: unknown v1 status={status!r}")
        application_status, listing_status = V1_STATUS_MAPPING[status]
        row = {key: legacy.get(key) or "" for key in jobs.FIELDS}
        row.update(
            {
                "application_status": application_status,
                "listing_status": listing_status,
                "verified_at": "",
                "first_party_verified": "unknown",
                "apply_verified": "unknown",
            }
        )
        if status == "Closed":
            row["decision_reason"] = "closed_before_application"
        elif status == "Duplicate":
            row["decision_reason"] = "duplicate_listing"
        migrated.append(row)
    return migrated


def migration_summary_payload(rows):
    return {
        "rows": len(rows),
        "unique_ids": len({row["id"] for row in rows}),
        "with_applied_at": sum(bool(row["applied_at"]) for row in rows),
        "listing_status_closed": sum(row["listing_status"] == "closed" for row in rows),
        "decision_reason_duplicate_listing": sum(
            row["decision_reason"] == "duplicate_listing" for row in rows
        ),
    }


def migration_summary(rows):
    payload = migration_summary_payload(rows)
    return [
        f"rows: {payload['rows']}",
        f"unique ids: {payload['unique_ids']}",
        f"with applied_at: {payload['with_applied_at']}",
        f"listing_status=closed: {payload['listing_status_closed']}",
        f"decision_reason=duplicate_listing: {payload['decision_reason_duplicate_listing']}",
    ]


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="report the migration without writing it")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    rows = migrate_v1_rows(load_v1())
    jobs.ensure_valid(rows)
    if args.format == "json":
        payload = {
            "ok": True,
            "command": "migrate-v2",
            "mode": "check" if args.check else "migrate",
            "summary": migration_summary_payload(rows),
        }
        if not args.check:
            jobs.save(rows)
        payload["saved"] = not args.check
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return 0
    mode = "check" if args.check else "migration applied"
    print(f"v1 -> v2: {mode}")
    for line in migration_summary(rows):
        print(line)
    if args.check:
        print("data/jobs.csv not changed")
        return 0
    jobs.save(rows)
    print("data/jobs.csv atomically updated")
    return 0


if __name__ == "__main__":
    sys.exit(main())
