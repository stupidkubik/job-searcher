"""Internal, human-confirmed event append through the shared dataset publisher.

This is a WP1.3 integration seam, not a public CLI or connector command.
"""

import json

try:
    from event_ledger import (
        EventValidationError, compare_snapshot, mismatch_report, parse_file, project_events,
        validate_event,
    )
    from tracker_transaction import digest
    from tracker_write import (
        PATHS, apply_dataset_transaction, dataset_write_lock,
        load, load_job_sources, render_application_card, today,
        current_dataset_revisions,
    )
except ModuleNotFoundError:
    from scripts.event_ledger import (
        EventValidationError, compare_snapshot, mismatch_report, parse_file, project_events,
        validate_event,
    )
    from scripts.tracker_transaction import digest
    from scripts.tracker_write import (
        PATHS, apply_dataset_transaction, dataset_write_lock,
        load, load_job_sources, render_application_card, today,
        current_dataset_revisions,
    )


def append_application_event(event):
    """Append one confirmed event and publish its four-field projection atomically.

    Caller supplies the complete versioned event. An identical ID/payload retry
    is a no-op; a changed payload, stale snapshot, or cross-job ID is rejected.
    Existing applied jobs need explicit migration before their first event.
    """
    validate_event(event)
    job_id = event["job_id"]
    event_path = PATHS.root / "data" / "application_events" / f"{job_id}.jsonl"
    with dataset_write_lock():
        rows, source_rows = load(), load_job_sources()
        revisions = current_dataset_revisions()
        row = next((item for item in rows if item["id"] == job_id), None)
        if row is None:
            raise EventValidationError("missing_job", f"unknown job_id: {job_id}")
        previous_bytes = event_path.read_bytes() if event_path.exists() else None
        previous = parse_file(event_path, job_ids={item["id"] for item in rows}) if previous_bytes is not None else []
        matching = next((item for item in previous if item["event_id"] == event["event_id"]), None)
        if matching is not None:
            if matching == event:
                mismatch = compare_snapshot(project_events(previous, job_id=job_id), row)
                if mismatch:
                    raise EventValidationError("snapshot_mismatch", f"existing event history disagrees with snapshot: {mismatch}")
                report = mismatch_report(event_path.parent, {item["id"]: item for item in rows})
                if any(item["mismatches"] for item in report.values()):
                    raise EventValidationError("snapshot_mismatch", "event history disagrees with jobs.csv")
                return {"job": row, "event": matching, "outcome": "already_recorded"}
            raise EventValidationError("duplicate_event", "event_id already has different content")
        if previous:
            mismatch = compare_snapshot(project_events(previous, job_id=job_id), row)
            if mismatch:
                raise EventValidationError("snapshot_mismatch", f"existing event history disagrees with snapshot: {mismatch}")
        elif row["application_status"] not in {"not_started", "reviewing", "apply"} or row["applied_at"]:
            raise EventValidationError("legacy_requires_backfill", "existing application needs migration before event append")

    projected = project_events([*previous, event], job_id=job_id, job_ids={item["id"] for item in rows})
    row.update(projected)
    row["decision_reason"] = (
        "no_response_timeout" if row["application_status"] == "ghosted"
        else "withdrawn_by_me" if row["application_status"] == "withdrawn" else ""
    )
    if row["application_status"] in {"applied", "rejected", "ghosted", "withdrawn"}:
        row["next_action"] = ""
        row["next_action_date"] = ""
    row["last_update"] = today()
    application_writes = ()
    if row["applied_at"]:
        path, body, revision = render_application_card(row, update_existing=True, with_revision=True)
        if body is not None:
            application_writes = ((path, body, revision),)
    event_body = (previous_bytes or b"") + json.dumps(
        event, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8") + b"\n"
    apply_dataset_transaction(
        rows, source_rows, application_writes,
        expected_revisions=revisions,
        event_write=(event_path, event_body, digest(previous_bytes)),
    )
    return {"job": row, "event": event, "outcome": "recorded"}
