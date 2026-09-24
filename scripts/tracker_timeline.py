"""Targeted, read-only human projection of one application event timeline."""

import csv
from pathlib import Path

try:
    from event_ledger import EventValidationError, compare_snapshot, parse_file, project_events
    from tracker_transaction import locked, recover_locked
except ModuleNotFoundError:
    from scripts.event_ledger import EventValidationError, compare_snapshot, parse_file, project_events
    from scripts.tracker_transaction import locked, recover_locked


def event_views(events):
    """Keep audit order and expose each correction chain without hiding rows."""
    successors = {event["supersedes"]: event["event_id"] for event in events if event["supersedes"]}
    views = []
    for event in events:
        event_id = event["event_id"]
        successor = successors.get(event_id)
        state = (
            "superseded"
            if successor
            else ("void_marker" if event["event_type"] == "event_voided" else "effective")
        )
        views.append(
            {
                "event_id": event_id,
                "event_type": event["event_type"],
                "occurred_at": event["occurred_at"],
                "precision": event["precision"],
                "recorded_at": event["recorded_at"],
                "source": event["source"],
                "actor": event["actor"],
                "confirmed_by_user": event["confirmed_by_user"],
                "evidence_ref": event["evidence_ref"],
                "payload": event["payload"],
                "state": state,
                "supersedes": event["supersedes"],
                "superseded_by": successor,
            }
        )
    return views


def read_timeline(root, job_id):
    """Recover first, then read the snapshot and one job file under one lock."""
    root = Path(root)
    with locked(root):
        recover_locked(root)
        with (root / "data/jobs.csv").open(newline="", encoding="utf-8") as stream:
            row = next((item for item in csv.DictReader(stream) if item["id"] == job_id), None)
        if row is None:
            raise EventValidationError("missing_job", f"unknown job_id: {job_id}")
        path = root / "data/application_events" / f"{job_id}.jsonl"
        events = parse_file(path, job_ids={job_id}) if path.exists() else []
        if events:
            projection = project_events(events, job_id=job_id)
            differences = compare_snapshot(projection, row)
            if differences:
                raise EventValidationError(
                    "snapshot_mismatch", f"event history disagrees with jobs.csv: {differences}"
                )
        return {
            "job_id": job_id,
            "company": row["company"],
            "role": row["role"],
            "history_state": "event_history"
            if events
            else ("legacy_snapshot_only" if row["applied_at"] else "no_application_events"),
            "snapshot": {
                field: row[field]
                for field in ("application_status", "stage_reached", "applied_at", "response_at")
            },
            "next_commitment": {
                "action": row["next_action"] or None,
                "date": row["next_action_date"] or None,
            },
            "events": event_views(events),
        }
