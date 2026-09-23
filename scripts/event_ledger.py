"""Read-only parser, validator and projection for tracker v3 event contract v1."""

import argparse
import csv
import json
import re
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

try:
    from tracker_schema import STAGES
except ModuleNotFoundError:
    from scripts.tracker_schema import STAGES


BUSINESS_ZONE = ZoneInfo("Europe/Belgrade")
EVENT_FIELDS = {
    "schema_version", "event_id", "job_id", "event_type", "occurred_at",
    "precision", "recorded_at", "source", "actor", "confirmed_by_user",
    "evidence_ref", "payload", "supersedes",
}
ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
JOB_PATTERN = re.compile(r"^job-[0-9]{4,}$")
DATE_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}$")
UTC_PATTERN = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}(?:\.[0-9]+)?Z$")
OFFSET_PATTERN = re.compile(r"(?:Z|[+-][0-9]{2}:[0-9]{2})$")
EVENT_TYPES = {
    "application_submitted", "acknowledgement_received", "response_received",
    "assessment_invited", "assessment_completed", "interview_scheduled",
    "interview_completed", "interview_cancelled", "offer_received",
    "rejection_received", "candidate_withdrew", "no_response_closed",
    "follow_up_sent", "event_voided",
}
ASSESSMENT_TYPES = {"assessment_invited", "assessment_completed"}
INTERVIEW_TYPES = {"interview_scheduled", "interview_completed", "interview_cancelled"}
SUBSTANTIVE_TYPES = {
    "response_received", "assessment_invited", "assessment_completed",
    "interview_scheduled", "interview_completed", "offer_received",
    "rejection_received",
}
DATED_TYPES = EVENT_TYPES - {"acknowledgement_received", "follow_up_sent", "event_voided"}
ROUND_STAGES = {
    "recruiter": "Recruiter screen",
    "technical": "Tech interview",
    "final": "Final interview",
}
OTHER_STAGES = {"Recruiter screen", "Tech interview", "Test task", "Final interview"}
TERMINAL_STATUSES = {"rejected", "withdrawn", "ghosted"}


class EventValidationError(ValueError):
    """A machine-readable contract violation in a read-only event artifact."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def fail(code, message):
    raise EventValidationError(code, message)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            fail("bad_json", f"duplicate JSON key: {key}")
        result[key] = value
    return result


def require_id(value, field):
    if not isinstance(value, str) or not ID_PATTERN.fullmatch(value):
        fail("bad_id", f"{field} must be a 1–128 character stable identifier")


def utc_instant(value, field):
    if not isinstance(value, str) or not UTC_PATTERN.fullmatch(value):
        fail("bad_timestamp", f"{field} must be an aware UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        fail("bad_timestamp", f"{field} is not a real timestamp")


def business_date(event):
    value = event["occurred_at"]
    precision = event["precision"]
    if precision == "unknown":
        if value is not None:
            fail("bad_precision", "unknown precision requires occurred_at=null")
        return None
    if precision == "date":
        if not isinstance(value, str) or not DATE_PATTERN.fullmatch(value):
            fail("bad_precision", "date precision requires YYYY-MM-DD")
        try:
            return date.fromisoformat(value).isoformat()
        except ValueError:
            fail("bad_precision", "occurred_at is not a real date")
    if precision == "instant":
        if not isinstance(value, str) or "T" not in value or not OFFSET_PATTERN.search(value):
            fail("bad_precision", "instant precision requires an aware timestamp")
        try:
            instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            fail("bad_precision", "occurred_at is not a real instant")
        if instant.tzinfo is None:
            fail("bad_precision", "occurred_at has no timezone")
        return instant.astimezone(BUSINESS_ZONE).date().isoformat()
    fail("bad_precision", f"unknown precision: {precision!r}")


def validate_payload(event):
    kind, payload = event["event_type"], event["payload"]
    if not isinstance(payload, dict):
        fail("bad_payload", "payload must be an object")
    if kind in ASSESSMENT_TYPES:
        required = {"assessment_id"}
    elif kind in INTERVIEW_TYPES:
        required = {"round_id", "round_kind"}
        if payload.get("round_kind") == "other":
            required.add("stage_hint")
    else:
        required = set()
    if set(payload) != required:
        fail("bad_payload", f"{kind} payload fields must be {sorted(required)}")
    if kind in ASSESSMENT_TYPES:
        require_id(payload["assessment_id"], "assessment_id")
    if kind in INTERVIEW_TYPES:
        require_id(payload["round_id"], "round_id")
        if not isinstance(payload["round_kind"], str) or payload["round_kind"] not in {*ROUND_STAGES, "other"}:
            fail("bad_payload", "round_kind is not recognized")
        if payload["round_kind"] == "other" and (
            not isinstance(payload["stage_hint"], str) or payload["stage_hint"] not in OTHER_STAGES
        ):
            fail("bad_payload", "stage_hint is not a post-application stage")


def validate_event(event, *, job_ids=None):
    if not isinstance(event, dict) or set(event) != EVENT_FIELDS:
        fail("bad_fields", f"event fields must be {sorted(EVENT_FIELDS)}")
    if type(event["schema_version"]) is not int or event["schema_version"] != 1:
        fail("bad_version", "schema_version must be 1")
    require_id(event["event_id"], "event_id")
    if not isinstance(event["job_id"], str) or not JOB_PATTERN.fullmatch(event["job_id"]):
        fail("bad_job", "job_id must be job-NNNN")
    if job_ids is not None and event["job_id"] not in job_ids:
        fail("missing_job", f"unknown job_id: {event['job_id']}")
    if not isinstance(event["event_type"], str) or event["event_type"] not in EVENT_TYPES:
        fail("bad_type", f"unknown event_type: {event['event_type']!r}")
    if not isinstance(event["precision"], str) or event["precision"] not in {"date", "instant", "unknown"}:
        fail("bad_precision", "precision must be date, instant or unknown")
    occurred_date = business_date(event)
    if event["event_type"] in DATED_TYPES and occurred_date is None:
        fail("bad_precision", f"{event['event_type']} requires a known business date")
    if event["event_type"] == "event_voided" and event["precision"] != "unknown":
        fail("bad_precision", "event_voided requires unknown precision")
    recorded = utc_instant(event["recorded_at"], "recorded_at")
    if not isinstance(event["source"], str) or event["source"] not in {"manual", "connector", "migration"}:
        fail("bad_source", "source is not recognized")
    if not isinstance(event["actor"], str) or event["actor"] not in {"user", "agent", "migration"}:
        fail("bad_actor", "actor is not recognized")
    if type(event["confirmed_by_user"]) is not bool:
        fail("bad_confirmation", "confirmed_by_user must be a boolean")
    if event["source"] == "migration":
        if event["actor"] != "migration" or event["confirmed_by_user"]:
            fail("bad_confirmation", "migration events have actor=migration and no user confirmation")
    elif event["actor"] == "migration" or not event["confirmed_by_user"]:
        fail("bad_confirmation", "non-migration events require confirmed_by_user=true")
    reference = event["evidence_ref"]
    if reference is not None and (
        not isinstance(reference, str) or not reference.strip() or len(reference) > 500
        or "\n" in reference or "\r" in reference
    ):
        fail("bad_evidence", "evidence_ref must be a single-line reference or null")
    if event["supersedes"] is not None:
        require_id(event["supersedes"], "supersedes")
    if event["event_type"] == "event_voided" and event["supersedes"] is None:
        fail("bad_supersedes", "event_voided requires supersedes")
    validate_payload(event)
    return recorded


def validate_events(events, *, expected_job_id=None, job_ids=None):
    """Check one job's append-only rows; return them unchanged on success."""
    seen, successor = {}, {}
    previous_order = None
    timeline_job_id = expected_job_id
    for event in events:
        recorded = validate_event(event, job_ids=job_ids)
        if timeline_job_id is None:
            timeline_job_id = event["job_id"]
        elif event["job_id"] != timeline_job_id:
            fail("job_mismatch", "one timeline may contain only one job_id")
        event_id = event["event_id"]
        if event_id in seen:
            fail("duplicate_event", f"duplicate event_id: {event_id}")
        order = (recorded, event_id)
        if previous_order is not None and order <= previous_order:
            fail("bad_order", "rows must ascend by recorded_at and event_id")
        previous_order = order
        parent = event["supersedes"]
        if parent is not None:
            if parent not in seen:
                fail("bad_supersedes", "supersedes must refer to an earlier event in the same job")
            if parent in successor:
                fail("forked_correction", f"event {parent} already has a correction")
            successor[parent] = event_id
        seen[event_id] = event
    return events


def parse_file(path, *, job_ids=None):
    path = Path(path)
    expected = path.stem
    if path.suffix != ".jsonl" or not JOB_PATTERN.fullmatch(expected):
        fail("bad_path", "event file must be named job-NNNN.jsonl")
    try:
        body = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        fail("bad_encoding", f"event file is not UTF-8: {path}")
    if body and not body.endswith("\n"):
        fail("bad_json", f"event file must end with a newline: {path}")
    events = []
    for line_number, line in enumerate(body.splitlines(), 1):
        if not line:
            fail("bad_json", f"{path}:{line_number}: blank lines are forbidden")
        try:
            event = json.loads(line, object_pairs_hook=unique_object)
        except json.JSONDecodeError as error:
            fail("bad_json", f"{path}:{line_number}: {error.msg}")
        events.append(event)
    if not events:
        fail("empty_file", f"event file has no rows: {path}")
    validate_events(events, expected_job_id=expected, job_ids=job_ids)
    return events


def effective_events(events):
    """Return corrected facts in original logical slots, without voided facts."""
    by_id = {event["event_id"]: event for event in events}
    successor = {event["supersedes"]: event["event_id"] for event in events if event["supersedes"]}
    result = []
    for root in events:
        if root["supersedes"] is not None:
            continue
        final_id = root["event_id"]
        while final_id in successor:
            final_id = successor[final_id]
        final = by_id[final_id]
        if final["event_type"] != "event_voided":
            result.append(final)
    return result


def project_events(events, *, job_id=None, job_ids=None):
    """Compute a four-field current snapshot from a validated job timeline."""
    validate_events(events, expected_job_id=job_id, job_ids=job_ids)
    status, stage, applied_at, response_at = "not_started", "None", "", ""
    submitted = False
    rounds = {}
    for event in effective_events(events):
        kind = event["event_type"]
        when = business_date(event)
        if kind == "application_submitted":
            if submitted:
                fail("bad_transition", "a job has more than one effective application submission")
            submitted, status, stage, applied_at = True, "applied", "Applied", when
            continue
        if not submitted:
            fail("bad_transition", f"{kind} occurs before application_submitted")
        if kind in SUBSTANTIVE_TYPES and (not response_at or when < response_at):
            response_at = when
        if kind == "assessment_invited" or kind == "assessment_completed":
            next_stage = "Test task"
        elif kind in {"interview_scheduled", "interview_completed"}:
            payload = event["payload"]
            next_stage = ROUND_STAGES.get(payload["round_kind"], payload.get("stage_hint"))
            round_id = payload["round_id"]
            signature = (payload["round_kind"], next_stage)
            if round_id in rounds and rounds[round_id][0] != signature:
                fail("bad_transition", "one round_id cannot change kind or stage")
            if kind == "interview_completed" and round_id in rounds and not rounds[round_id][1]:
                fail("bad_transition", "a cancelled round must be rescheduled before completion")
            if kind == "interview_scheduled":
                rounds[round_id] = (signature, True)
        elif kind == "interview_cancelled":
            payload = event["payload"]
            round_id = payload["round_id"]
            cancelled_stage = ROUND_STAGES.get(payload["round_kind"], payload.get("stage_hint"))
            signature = (payload["round_kind"], cancelled_stage)
            if round_id not in rounds or rounds[round_id] != (signature, True):
                fail("bad_transition", "interview cancellation has no scheduled round")
            rounds[round_id] = (signature, False)
            next_stage = None
        elif kind == "offer_received":
            next_stage = "Offer"
        else:
            next_stage = None
        if status in TERMINAL_STATUSES and kind in (
            ASSESSMENT_TYPES | {"interview_scheduled", "interview_completed", "offer_received", "rejection_received", "candidate_withdrew", "no_response_closed"}
        ):
            fail("bad_transition", f"{kind} follows terminal status {status}")
        if status == "offer" and kind in (
            ASSESSMENT_TYPES | {"interview_scheduled", "interview_completed", "offer_received", "no_response_closed"}
        ):
            fail("bad_transition", f"{kind} follows an offer")
        if next_stage is not None and STAGES.index(next_stage) > STAGES.index(stage):
            stage = next_stage
        if kind in {"interview_scheduled", "interview_completed"}:
            status = "interviewing"
        elif kind == "offer_received":
            status = "offer"
        elif kind == "rejection_received":
            status = "rejected"
        elif kind == "candidate_withdrew":
            status = "withdrawn"
        elif kind == "no_response_closed":
            status = "ghosted"
    return {
        "application_status": status,
        "stage_reached": stage,
        "applied_at": applied_at,
        "response_at": response_at,
    }


def compare_snapshot(projected, current):
    return [
        {"field": field, "expected": value, "actual": current.get(field, "")}
        for field, value in projected.items()
        if current.get(field, "") != value
    ]


def mismatch_report(ledger_dir, snapshots):
    """Validate all event files against a supplied id->snapshot mapping."""
    ledger_dir = Path(ledger_dir)
    if not ledger_dir.is_dir():
        fail("bad_path", f"ledger directory does not exist: {ledger_dir}")
    seen_ids = set()
    report = {}
    for path in sorted(ledger_dir.iterdir()):
        if not path.is_file() or path.suffix != ".jsonl":
            fail("bad_path", f"unexpected ledger entry: {path.name}")
        if path.stem not in snapshots:
            fail("missing_job", f"event file has no snapshot row: {path.stem}")
        events = parse_file(path, job_ids=set(snapshots))
        for event in events:
            if event["event_id"] in seen_ids:
                fail("duplicate_event", f"cross-file event_id collision: {event['event_id']}")
            seen_ids.add(event["event_id"])
        projected = project_events(events, job_id=path.stem)
        differences = compare_snapshot(projected, snapshots[path.stem])
        report[path.stem] = {"events": len(events), "projection": projected, "mismatches": differences}
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", type=Path, help="event ledger directory to inspect")
    parser.add_argument("--jobs-csv", type=Path, required=True, help="snapshot CSV for foreign keys and comparison")
    args = parser.parse_args()
    try:
        with args.jobs_csv.open(newline="", encoding="utf-8") as stream:
            snapshots = {row["id"]: row for row in csv.DictReader(stream)}
        report = mismatch_report(args.ledger, snapshots)
        ok = not any(item["mismatches"] for item in report.values())
        print(json.dumps({"ok": ok, "jobs": report}, sort_keys=True))
        if not ok:
            raise SystemExit(1)
    except (EventValidationError, OSError, KeyError) as error:
        code = error.code if isinstance(error, EventValidationError) else "read_error"
        print(json.dumps({"ok": False, "error": {"code": code, "message": str(error)}}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
