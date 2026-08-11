#!/usr/bin/env python3
"""Execute one declarative agent operation through the tracker write-path.

This is the trusted half of the connector workflow.  It deliberately accepts a
small domain schema instead of a shell command and delegates every canonical
write to the existing ``jobs.py`` functions.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

try:  # Direct CLI execution places scripts/ on sys.path.
    import jobs
except ModuleNotFoundError:  # Unit tests may import the file as scripts.agent_operations.
    from scripts import jobs


ROOT = Path(__file__).resolve().parent.parent
REQUESTS_DIR = ROOT / "data" / "operations" / "requests"
RESULTS_DIR = ROOT / "data" / "operations" / "results"
OPERATION_VERSION = 1
MAX_REQUEST_BYTES = 64 * 1024
OPERATION_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,79}\Z")
JOB_ID_RE = re.compile(r"job-\d{4,}\Z")
TOP_LEVEL_FIELDS = {"version", "operation_id", "command", "job_id", "expected", "args"}
VERIFY_REQUIRED_ARGS = {"listing_status", "first_party_verified", "apply_verified"}
VERIFY_ALLOWED_ARGS = VERIFY_REQUIRED_ARGS | {
    "original_url", "decision_reason", "notes", "level", "remote_policy", "stack",
    "salary", "match_score",
}
SET_ALLOWED_ARGS = {"next_action", "next_action_date", "listing_status"}
VERIFY_ENRICHMENT_ARGS = {"level", "remote_policy", "stack", "salary", "match_score"}


class OperationError(ValueError):
    """The operation is malformed or forbidden by the runner policy."""


def die(message):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def print_json(value):
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def clean_text(value, field):
    if not isinstance(value, str):
        raise OperationError(f"{field} must be a string")
    if "\n" in value or "\r" in value:
        raise OperationError(f"{field} must not contain a newline")
    return value


def resolve_request_path(value):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    try:
        resolved = path.resolve(strict=True)
        relative = resolved.relative_to(REQUESTS_DIR.resolve())
    except (OSError, ValueError) as error:
        raise OperationError("request must be an existing file inside data/operations/requests") from error
    if relative.parent != Path(".") or resolved.suffix != ".json":
        raise OperationError("request must be a direct .json file in data/operations/requests")
    return resolved


def result_path(operation_id):
    return RESULTS_DIR / f"{operation_id}.json"


def load_operation(path):
    path = resolve_request_path(path)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise OperationError(f"cannot read request: {error}") from error
    if len(raw) > MAX_REQUEST_BYTES:
        raise OperationError(f"request exceeds {MAX_REQUEST_BYTES} bytes")
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise OperationError(f"request is not valid UTF-8 JSON: {error}") from error
    operation = validate_operation(value)
    if path.name != f"{operation['operation_id']}.json":
        raise OperationError("request filename must equal operation_id + '.json'")
    return operation


def validate_expected(expected):
    if not isinstance(expected, dict) or not expected:
        raise OperationError("expected must be a non-empty object")
    unknown = sorted(set(expected) - (set(jobs.FIELDS) - {"id"}))
    if unknown:
        raise OperationError("expected contains unknown or protected fields: " + ", ".join(unknown))
    result = {}
    for key, value in expected.items():
        result[key] = clean_text(value, f"expected.{key}")
    return result


def validate_verify_args(args):
    if not isinstance(args, dict):
        raise OperationError("args must be an object")
    unknown = sorted(set(args) - VERIFY_ALLOWED_ARGS)
    missing = sorted(VERIFY_REQUIRED_ARGS - set(args))
    if unknown or missing:
        pieces = []
        if unknown:
            pieces.append("unknown verify args: " + ", ".join(unknown))
        if missing:
            pieces.append("missing verify args: " + ", ".join(missing))
        raise OperationError("; ".join(pieces))
    normalized = {}
    for key, value in args.items():
        if key == "match_score":
            if not isinstance(value, (str, int, float)) or isinstance(value, bool):
                raise OperationError("args.match_score must be a string or number")
            normalized[key] = str(value)
        else:
            normalized[key] = clean_text(value, f"args.{key}")
    if normalized["listing_status"] not in {"open", "closed"}:
        raise OperationError("args.listing_status must be open or closed")
    for key in ("first_party_verified", "apply_verified"):
        if normalized[key] not in {"yes", "no"}:
            raise OperationError(f"args.{key} must be yes or no")
    if "decision_reason" in normalized and normalized["decision_reason"] not in jobs.PRE_APPLICATION_REASONS - {"duplicate_listing"}:
        raise OperationError("args.decision_reason is not allowed for verify")
    if "level" in normalized and normalized["level"] not in jobs.LEVELS:
        raise OperationError("args.level is not a known level")
    if "remote_policy" in normalized and normalized["remote_policy"] not in jobs.REMOTE:
        raise OperationError("args.remote_policy is not a known remote policy")
    if "original_url" in normalized and normalized["original_url"] and not jobs.valid_http_url(normalized["original_url"]):
        raise OperationError("args.original_url must be an absolute http(s) URL")
    return normalized


def validate_set_args(args):
    if not isinstance(args, dict) or not args:
        raise OperationError("set args must be a non-empty object")
    unknown = sorted(set(args) - SET_ALLOWED_ARGS)
    if unknown:
        raise OperationError("unknown set args: " + ", ".join(unknown))
    normalized = {key: clean_text(value, f"args.{key}") for key, value in args.items()}
    if "next_action" in normalized and not normalized["next_action"].strip():
        raise OperationError("args.next_action must not be empty")
    if "next_action_date" in normalized:
        try:
            datetime.strptime(normalized["next_action_date"], "%Y-%m-%d")
        except ValueError as error:
            raise OperationError("args.next_action_date must be YYYY-MM-DD") from error
    if "listing_status" in normalized and normalized["listing_status"] != "closed":
        raise OperationError("agent set may only record listing_status=closed")
    return normalized


def validate_operation(value):
    if not isinstance(value, dict):
        raise OperationError("request must be a JSON object")
    unknown = sorted(set(value) - TOP_LEVEL_FIELDS)
    missing = sorted(TOP_LEVEL_FIELDS - set(value))
    if unknown or missing:
        pieces = []
        if unknown:
            pieces.append("unknown top-level fields: " + ", ".join(unknown))
        if missing:
            pieces.append("missing top-level fields: " + ", ".join(missing))
        raise OperationError("; ".join(pieces))
    if value["version"] != OPERATION_VERSION:
        raise OperationError(f"version must be {OPERATION_VERSION}")
    operation_id = clean_text(value["operation_id"], "operation_id")
    if not OPERATION_ID_RE.fullmatch(operation_id):
        raise OperationError("operation_id must use lowercase letters, digits, '.', '_' or '-'")
    command = clean_text(value["command"], "command")
    if command not in {"verify", "set"}:
        raise OperationError("command must be verify or set in Phase A")
    job_id = clean_text(value["job_id"], "job_id")
    if not JOB_ID_RE.fullmatch(job_id):
        raise OperationError("job_id must be job-NNNN")
    expected = validate_expected(value["expected"])
    args = validate_verify_args(value["args"]) if command == "verify" else validate_set_args(value["args"])
    return {
        "version": OPERATION_VERSION,
        "operation_id": operation_id,
        "command": command,
        "job_id": job_id,
        "expected": expected,
        "args": args,
    }


def read_job(job_id):
    for row in jobs.load():
        if row["id"] == job_id:
            return row
    raise OperationError(f"job {job_id} was not found")


def precondition_mismatches(row, expected):
    return {
        key: {"expected": value, "actual": row.get(key, "")}
        for key, value in expected.items()
        if row.get(key, "") != value
    }


def classify_risk(operation, row):
    if operation["command"] == "set":
        return "low"
    args = operation["args"]
    passed = (
        args["listing_status"] == "open"
        and args["first_party_verified"] == "yes"
        and args["apply_verified"] == "yes"
    )
    if VERIFY_ENRICHMENT_ARGS & set(args):
        return "medium"
    if passed and row["application_status"] == "not_started":
        return "medium"
    return "low"


def apply_operation(operation, row):
    if operation["command"] == "verify":
        result = jobs.verify_job(operation["job_id"], **operation["args"])
        return result["job"], result["warnings"], result["outcome"]

    if "listing_status" in operation["args"] and row["application_status"] not in jobs.NEEDS_APPLIED_AT:
        raise OperationError("listing_status=closed through set is allowed only after an application exists")
    result = jobs.set_job(operation["job_id"], list(operation["args"].items()))
    return result["job"], result["warnings"], "updated"


def operation_result(operation, *, status, risk, details):
    return {
        "version": OPERATION_VERSION,
        "operation_id": operation["operation_id"],
        "status": status,
        "executed_at": utc_now(),
        "risk": risk,
        "command": operation["command"],
        "job_id": operation["job_id"],
        "result": details,
    }


def write_result(operation, result):
    path = result_path(operation["operation_id"])
    if path.exists():
        raise OperationError(f"operation_id already has a result: {path.relative_to(ROOT)}")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(result, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
    except OSError as error:
        raise OperationError(f"cannot write operation result: {error}") from error
    return path


def execute(path):
    """Execute once, or record a conflict without touching canonical files."""
    operation = load_operation(path)
    if result_path(operation["operation_id"]).exists():
        raise OperationError(f"operation_id already has a result: {result_path(operation['operation_id']).relative_to(ROOT)}")
    row = read_job(operation["job_id"])
    risk = classify_risk(operation, row)
    mismatches = precondition_mismatches(row, operation["expected"])
    if mismatches:
        result = operation_result(
            operation,
            status="conflict",
            risk=risk,
            details={"reason": "stale_operation", "mismatches": mismatches},
        )
        return result, write_result(operation, result)

    updated, warnings, outcome = apply_operation(operation, row)
    errors, validation_warnings = jobs.validate_dataset(jobs.load(), jobs.load_job_sources())
    if errors:
        raise OperationError("post-operation dataset validation failed: " + "; ".join(errors))
    result = operation_result(
        operation,
        status="completed",
        risk=risk,
        details={
            "outcome": outcome,
            "application_status": updated["application_status"],
            "listing_status": updated["listing_status"],
            "warnings": [*warnings, *validation_warnings],
        },
    )
    return result, write_result(operation, result)


def main():
    parser = argparse.ArgumentParser(description="Execute a declarative Phase A agent operation")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="validate an operation without writing")
    validate.add_argument("request", type=Path)
    validate.add_argument("--format", choices=("text", "json"), default="text")
    apply = subparsers.add_parser("apply", help="apply one operation and write its immutable result")
    apply.add_argument("request", type=Path)
    apply.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    try:
        if args.command == "validate":
            operation = load_operation(args.request)
            payload = {"ok": True, "command": "validate", "operation": operation}
        else:
            result, result_path_value = execute(args.request)
            payload = {
                "ok": True,
                "command": "apply",
                "operation_id": result["operation_id"],
                "status": result["status"],
                "risk": result["risk"],
                "result_path": result_path_value.relative_to(ROOT).as_posix(),
                "result": result,
            }
    except OperationError as error:
        die(str(error))
    if args.format == "json":
        print_json(payload)
    elif args.command == "validate":
        print(f"valid operation: {payload['operation']['operation_id']}")
    else:
        print(f"{payload['operation_id']}  {payload['status']}  risk={payload['risk']}")


if __name__ == "__main__":
    main()
