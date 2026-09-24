#!/usr/bin/env python3
"""One-time repair: undo a stale first-party-verification stamp on one
historical Himalayas screening batch (job-0099..job-0126, minus four rows
that turned out not to belong to that batch).

docs/agent-write-path-plan-2026-09-07.md, Э9/G-12. This targets an exact,
already-closed incident and refuses to run against anything that doesn't
match the recorded before/after snapshot byte-for-byte, so it is safe to
re-run but has no use beyond that one batch. Intentionally not reachable
from `scripts/jobs.py --help` or the connector write path.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent

sys.path.insert(0, str(ROOT / "scripts"))
import jobs  # noqa: E402

HIMALAYAS_SCREENING_REPAIR_EXCLUSIONS = {
    "job-0102",
    "job-0110",
    "job-0111",
    "job-0124",
}
HIMALAYAS_SCREENING_REPAIR_IDS = tuple(
    f"job-{number:04d}"
    for number in range(99, 127)
    if f"job-{number:04d}" not in HIMALAYAS_SCREENING_REPAIR_EXCLUSIONS
)
HIMALAYAS_SCREENING_REPAIR_FIELDS = (
    "listing_status",
    "first_party_verified",
    "apply_verified",
    "verified_at",
)
HIMALAYAS_SCREENING_REPAIR_FROM = {
    "listing_status": "open",
    "first_party_verified": "no",
    "apply_verified": "no",
    "verified_at": "2026-08-11",
}
HIMALAYAS_SCREENING_REPAIR_TO = {
    "listing_status": "unknown",
    "first_party_verified": "unknown",
    "apply_verified": "unknown",
    "verified_at": "",
}


def himalayas_screening_repair_state(row):
    snapshot = {field: row[field] for field in HIMALAYAS_SCREENING_REPAIR_FIELDS}
    if snapshot == HIMALAYAS_SCREENING_REPAIR_FROM:
        return "pending"
    if snapshot == HIMALAYAS_SCREENING_REPAIR_TO:
        return "repaired"
    return "unexpected"


def repair_himalayas_screening(*, check=False):
    """Repair the exact legacy Himalayas screening batch without reclassifying it."""
    rows, source_rows, expected_revisions = jobs.load_for_write()
    by_id = {row["id"]: row for row in rows}
    required_ids = set(HIMALAYAS_SCREENING_REPAIR_IDS) | HIMALAYAS_SCREENING_REPAIR_EXCLUSIONS
    missing = sorted(required_ids - by_id.keys())
    if missing:
        jobs.die("repair-himalayas-screening: missing expected rows: " + ", ".join(missing))

    targets = [by_id[job_id] for job_id in HIMALAYAS_SCREENING_REPAIR_IDS]
    wrong_batch = [
        row["id"]
        for row in targets
        if row["source"] != "Himalayas"
        or row["application_status"] != "not_started"
        or not row["decision_reason"]
        or not row["notes"]
    ]
    if wrong_batch:
        jobs.die(
            "repair-himalayas-screening: rows do not match the old screening batch: " + ", ".join(wrong_batch)
        )
    wrong_exclusions = sorted(
        job_id for job_id in HIMALAYAS_SCREENING_REPAIR_EXCLUSIONS if by_id[job_id]["source"] != "Himalayas"
    )
    if wrong_exclusions:
        jobs.die(
            "repair-himalayas-screening: exclusions no longer belong to Himalayas: "
            + ", ".join(wrong_exclusions)
        )

    states = {row["id"]: himalayas_screening_repair_state(row) for row in targets}
    unexpected = sorted(job_id for job_id, state in states.items() if state == "unexpected")
    pending = sorted(job_id for job_id, state in states.items() if state == "pending")
    repaired = sorted(job_id for job_id, state in states.items() if state == "repaired")
    if unexpected or (pending and repaired):
        details = []
        if unexpected:
            details.append("unexpected=" + ",".join(unexpected))
        if pending and repaired:
            details.append(f"mixed pending={len(pending)}, repaired={len(repaired)}")
        jobs.die("repair-himalayas-screening: mixed or unexpected state; " + "; ".join(details))

    status = "ready" if pending else "already_applied"
    payload = {
        "ok": True,
        "command": "repair-himalayas-screening",
        "mode": "check" if check else "apply",
        "status": status,
        "target_count": len(HIMALAYAS_SCREENING_REPAIR_IDS),
        "target_ids": list(HIMALAYAS_SCREENING_REPAIR_IDS),
        "excluded_ids": sorted(HIMALAYAS_SCREENING_REPAIR_EXCLUSIONS),
        "changed": 0,
    }
    if check or status == "already_applied":
        return payload

    target_before = {row["id"]: dict(row) for row in targets}
    excluded_before = {job_id: dict(by_id[job_id]) for job_id in HIMALAYAS_SCREENING_REPAIR_EXCLUSIONS}
    for row in targets:
        row.update(HIMALAYAS_SCREENING_REPAIR_TO)

    for row in targets:
        before = target_before[row["id"]]
        changed_fields = {field for field in jobs.FIELDS if row[field] != before[field]}
        if changed_fields != set(HIMALAYAS_SCREENING_REPAIR_FIELDS):
            jobs.die(f"repair-himalayas-screening: unexpected change set for {row['id']}")
        if row["decision_reason"] != before["decision_reason"] or row["notes"] != before["notes"]:
            jobs.die(f"repair-himalayas-screening: decision_reason/notes changed for {row['id']}")
    if any(by_id[job_id] != before for job_id, before in excluded_before.items()):
        jobs.die("repair-himalayas-screening: one of the exclusions was changed")

    warnings = jobs.ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    jobs.apply_dataset_transaction(rows, source_rows, expected_revisions=expected_revisions)
    payload.update({"status": "applied", "changed": len(targets), "warnings": warnings})
    return payload


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--check", action="store_true", help="report the repair without writing it")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    result = repair_himalayas_screening(check=args.check)
    if args.format == "json":
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 0
    print(
        f"Himalayas screening repair: {result['status']}; "
        f"targets={result['target_count']}; changed={result['changed']}"
    )
    print("excluded: " + ", ".join(result["excluded_ids"]))
    if args.check:
        print("data/jobs.csv not changed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
