#!/usr/bin/env python3
"""Plan a conservative historical event backfill; apply only to an explicit root.

The default is a read-only plan. Production application remains gated until
cutover. No notes, stage chronology, or missing dates are inferred.
"""

import argparse
import csv
import io
import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if __package__:
    from scripts.event_ledger import (  # noqa: E402
        EventValidationError,
        compare_snapshot,
        mismatch_report,
        project_events,
    )
    from scripts.tracker_transaction import StaleRevision, TransactionError, digest, publish  # noqa: E402
else:
    sys.path.insert(0, str(ROOT / "scripts"))
    from event_ledger import (  # noqa: E402
        EventValidationError,
        compare_snapshot,
        mismatch_report,
        project_events,
    )
    from tracker_transaction import StaleRevision, TransactionError, digest, publish  # noqa: E402

PRE_APPLICATION = {"not_started", "reviewing", "apply"}
MIGRATION_TYPES = ("application_submitted", "response_received", "rejection_received")
CUTOVER_MARKER = "config/event-ledger-cutover.json"
CUTOVER_BYTES = b'{"enabled":true,"migration":"migration-v1","version":1}\n'
POST_APPLICATION = {"applied", "interviewing", "offer", "rejected", "ghosted", "withdrawn"}


def event_for(row, kind, occurred_at, recorded_at):
    return {
        "schema_version": 1,
        "event_id": f"migration-v1:{row['id']}:{kind}",
        "job_id": row["id"],
        "event_type": kind,
        "occurred_at": occurred_at,
        "precision": "date",
        "recorded_at": recorded_at,
        "source": "migration",
        "actor": "migration",
        "confirmed_by_user": False,
        "evidence_ref": None,
        "payload": {},
        "supersedes": None,
    }


def candidate_events(row, recorded_at):
    """Return only events supported by the four structured lifecycle fields."""
    status = row["application_status"]
    stage = row["stage_reached"]
    applied = row["applied_at"]
    response = row["response_at"]
    if status in PRE_APPLICATION:
        if applied or response or stage != "None":
            return None, "inconsistent_pre_application_snapshot"
        return [], None
    if not applied:
        return None, "missing_applied_at"
    if response and response < applied:
        return None, "invalid_lifecycle_dates"
    if stage != "Applied":
        return None, "unproven_stage_chronology"
    events = [event_for(row, "application_submitted", applied, recorded_at)]
    if status == "applied":
        if response:
            events.append(event_for(row, "response_received", response, recorded_at))
    elif status == "rejected":
        if not response:
            return None, "missing_response_at"
        events.append(event_for(row, "rejection_received", response, recorded_at))
    else:
        # Terminal candidate actions and offers have no dated transition in
        # the v2 snapshot. A date from last_update would invent chronology.
        return None, "undated_or_unrepresentable_transition"
    try:
        projected = project_events(events, job_id=row["id"])
    except EventValidationError:
        return None, "invalid_lifecycle_dates"
    differences = compare_snapshot(projected, row)
    if differences:
        return None, "projection_mismatch"
    return events, None


def read_rows(root):
    body = (root / "data/jobs.csv").read_bytes()
    rows = list(csv.DictReader(io.StringIO(body.decode("utf-8"))))
    if not rows or len({row["id"] for row in rows}) != len(rows):
        raise ValueError("jobs.csv is empty or has duplicate IDs")
    return rows, body


def plan(root, recorded_at):
    """Build a deterministic plan without writing any file or directory."""
    root = Path(root)
    rows, csv_body = read_rows(root)
    ledger = root / "data/application_events"
    snapshots = {row["id"]: row for row in rows}
    existing = mismatch_report(ledger, snapshots) if ledger.exists() else {}
    mismatches = {job_id: item["mismatches"] for job_id, item in existing.items() if item["mismatches"]}
    if mismatches:
        raise ValueError(f"existing ledger disagrees with snapshot: {mismatches}")
    pending, blocked = {}, []
    untouched = 0
    categories = Counter()
    existing_count = sum(item["events"] for item in existing.values())
    for row in rows:
        job_id = row["id"]
        category = (
            row["application_status"],
            row["stage_reached"],
            bool(row["applied_at"]),
            bool(row["response_at"]),
        )
        categories[str(category)] += 1
        if job_id in existing:
            continue
        events, reason = candidate_events(row, recorded_at)
        if reason:
            blocked.append({"job_id": job_id, "reason": reason})
        elif events:
            pending[job_id] = events
        else:
            untouched += 1
    counts = Counter(event["event_type"] for events in pending.values() for event in events)
    if len(existing) + len(pending) + len(blocked) + untouched != len(rows):
        raise ValueError("row conservation failed")
    return (
        {
            "rows": len(rows),
            "untouched_jobs": untouched,
            "existing_jobs": len(existing),
            "existing_events": existing_count,
            "pending_jobs": len(pending),
            "pending_events": sum(counts.values()),
            "event_counts": {kind: counts[kind] for kind in MIGRATION_TYPES},
            "blocked": blocked,
            "categories": dict(sorted(categories.items())),
        },
        pending,
        digest(csv_body),
    )


def apply(root, summary, pending, csv_revision, *, cutover=False):
    root = Path(root)
    if summary["blocked"]:
        raise ValueError("blocked lifecycle rows require explicit resolution before apply")
    marker = root / CUTOVER_MARKER
    if marker.exists() and marker.read_bytes() != CUTOVER_BYTES:
        raise ValueError("cutover marker has unexpected content")
    if marker.exists() and pending:
        raise ValueError("cutover marker exists but historical jobs still need migration")
    if not pending and (not cutover or marker.exists()):
        return "already_complete"
    ledger = root / "data/application_events"
    created_dir = not ledger.exists()
    if pending or cutover:
        ledger.mkdir(exist_ok=True)
    created_config = cutover and not marker.parent.exists()
    if cutover:
        marker.parent.mkdir(exist_ok=True)
    writes = {}
    expected = {}
    for job_id, events in pending.items():
        relative = f"data/application_events/{job_id}.jsonl"
        writes[relative] = b"".join(
            json.dumps(event, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
            + b"\n"
            for event in events
        )
        expected[relative] = None
    if cutover:
        writes[CUTOVER_MARKER] = CUTOVER_BYTES
        expected[CUTOVER_MARKER] = digest(marker.read_bytes()) if marker.exists() else None

    def validate(replacement_root):
        if digest((replacement_root / "data/jobs.csv").read_bytes()) != csv_revision:
            raise StaleRevision("jobs.csv changed during migration")
        fresh_rows, _ = read_rows(replacement_root)
        report = mismatch_report(
            replacement_root / "data/application_events", {row["id"]: row for row in fresh_rows}
        )
        if any(item["mismatches"] for item in report.values()):
            raise ValueError("migration projection differs from snapshot")
        if cutover and any(
            row["id"] not in report for row in fresh_rows if row["application_status"] in POST_APPLICATION
        ):
            raise ValueError("cutover requires event history for every post-application job")

    try:
        publish(root, writes, expected, validate=validate)
    except BaseException:
        if created_dir and ledger.is_dir() and not any(ledger.iterdir()):
            ledger.rmdir()
        if created_config and marker.parent.is_dir() and not any(marker.parent.iterdir()):
            marker.parent.rmdir()
        raise
    return "applied"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, help="tracker checkout; required explicitly with --apply")
    parser.add_argument("--apply", action="store_true", help="publish planned event files atomically")
    parser.add_argument(
        "--cutover", action="store_true", help="atomically enable event writes after full migration"
    )
    parser.add_argument("--format", choices=("json", "text"), default="json")
    args = parser.parse_args(argv)
    if args.apply and args.root is None:
        parser.error("--apply requires an explicit --root")
    if args.cutover and not args.apply:
        parser.error("--cutover requires --apply")
    root = args.root or ROOT
    if args.apply and root.resolve() == ROOT.resolve() and os.environ.get("TRACKER_V3_EVENT_WRITES") != "1":
        parser.error("production migration requires TRACKER_V3_EVENT_WRITES=1 after cutover")
    recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    try:
        summary, pending, csv_revision = plan(root, recorded_at)
        summary["dry_run"] = not args.apply
        summary["cutover"] = args.cutover
        summary["outcome"] = (
            apply(root, summary, pending, csv_revision, cutover=args.cutover) if args.apply else "planned"
        )
        if args.format == "json":
            print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
        else:
            print(
                f"{summary['outcome']}: {summary['rows']} rows, {summary['pending_jobs']} pending jobs, "
                f"{summary['pending_events']} events, {len(summary['blocked'])} blocked"
            )
            for item in summary["blocked"]:
                print(f"blocked {item['job_id']}: {item['reason']}")
        return 0 if not summary["blocked"] else 2
    except (OSError, ValueError, EventValidationError, TransactionError) as error:
        print(json.dumps({"ok": False, "error": str(error)}), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
