#!/usr/bin/env python3
import argparse
import hashlib
import json
import math
import re
import shutil
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

try:
    import jobs
except ModuleNotFoundError:
    from scripts import jobs
try:
    from tracker_time import utc_timestamp
except ModuleNotFoundError:
    from scripts.tracker_time import utc_timestamp
ROOT = Path(__file__).resolve().parent.parent
REQUESTS_DIR = ROOT / "data" / "operations" / "requests"
RESULTS_DIR = ROOT / "data" / "operations" / "results"
OPERATION_VERSION = 1
MAX_REQUEST_BYTES = 64 * 1024
MAX_BATCH_OPERATIONS = 100
# atomic:true batches roll back entirely on a single child conflict, so the
# blast radius of one bad child is capped tighter than atomic:false, which
# keeps whatever children succeed (Э4, docs/agent-write-path-plan-2026-09-07.md).
MAX_ATOMIC_BATCH_OPERATIONS = 10
OPERATION_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,79}\Z")
JOB_ID_RE = re.compile(r"job-\d{4,}\Z")
SINGLE_TOP_LEVEL_FIELDS = {"version", "operation_id", "command", "job_id", "expected", "args"}
ADD_TOP_LEVEL_FIELDS = {"version", "operation_id", "command", "args"}
BATCH_TOP_LEVEL_FIELDS = {"version", "operation_id", "command", "atomic", "operations"}
JOB_CHILD_FIELDS = {"command", "job_id", "expected", "args"}
ADD_CHILD_FIELDS = {"command", "client_ref", "args"}
VERIFY_REQUIRED_ARGS = {"listing_status", "first_party_verified", "apply_verified"}
VERIFY_ALLOWED_ARGS = VERIFY_REQUIRED_ARGS | {
    "original_url",
    "decision_reason",
    "notes",
    "level",
    "remote_policy",
    "stack",
    "salary",
    "match_score",
    "application_status",
    "next_action",
    "next_action_date",
}
SET_ALLOWED_ARGS = {"next_action", "next_action_date", "listing_status"}
SCREEN_REQUIRED_ARGS = {"decision_reason"}
SCREEN_ALLOWED_ARGS = SCREEN_REQUIRED_ARGS | {"notes"}
STATUS_REQUIRED_ARGS = {"application_status", "confirmed_by_user"}
STATUS_ALLOWED_ARGS = STATUS_REQUIRED_ARGS | {
    "stage",
    "applied_at",
    "response_at",
    "decision_reason",
    "next_action",
    "next_action_date",
    "cv_version",
    "notes",
}
VERIFY_ENRICHMENT_ARGS = {"level", "remote_policy", "stack", "salary", "match_score"}
VERIFY_WORKFLOW_ARGS = {"application_status", "next_action", "next_action_date"}
ADD_CONTROL_ARGS = {"duplicate_of", "force"}
ADD_ALLOWED_ARGS = set(jobs.ADD_INPUT_FIELDS) | ADD_CONTROL_ARGS
ADD_REQUIRED_ARGS = set(jobs.ADD_REQUIRED_INPUT_FIELDS)
# Named differently from jobs.ADD_APPLICATION_STATUSES: the connector may not
# set application_status=apply directly (that transition needs a passed
# verification), so this allowlist is a strict subset of the CLI's.
CONNECTOR_ADD_APPLICATION_STATUSES = {"not_started", "reviewing"}
ADD_DUPLICATE_ARGS = ADD_REQUIRED_ARGS | {
    "source_url",
    "source_job_id",
    "found_at",
    "duplicate_of",
    "force",
}
# Shared with render-contract so the generated table can never name a
# decision_reason value the validator itself would reject.
ADD_VERIFY_DECISION_REASONS = jobs.PRE_APPLICATION_REASONS - {"duplicate_listing"}
STATUS_DECISION_REASONS = {"no_response_timeout", "withdrawn_by_me"}
ADD_UNKNOWN_ARG_HINTS = {
    "next_action": "create the job first, then send a separate set operation with next_action",
    "next_action_date": "create the job first, then send a separate set operation with next_action_date",
    "verified_at": "verified_at is computed by the runner from verify; do not send it directly",
}
# Closed taxonomy for rejected-result error.code (see docs/agent-write-path-plan-2026-09-07.md, Э1).
ERROR_CODES = frozenset(
    {
        "invalid_json",
        "request_too_large",
        "filename_mismatch",
        "unsupported_command",
        "unknown_top_level_fields",
        "missing_top_level_fields",
        "unknown_args",
        "missing_args",
        "bad_type",
        "bad_enum_value",
        "bad_format",
        "duplicate_add_extra_fields",
        "invariant_violation",
        "unknown_job",
        "result_exists",
        "batch_not_atomic",
        # Written only by scripts/maintenance/backfill_missing_results.py (Э1b): a
        # historical request that passes contract validation today but has no
        # result file, i.e. it was lost before the runner ever applied it.
        "lost_before_apply",
        # OperationError's own default when raised without an explicit code: the
        # validate_verify_args/validate_set_args/validate_screen_args/clean_text/
        # validate_expected branches that Э1's wave 1 did not migrate yet. A
        # future wave replaces each remaining bare `raise OperationError(...)`
        # with `contract_error(..., code=...)` and this becomes unreachable.
        "contract_violation",
    }
)


class OperationError(ValueError):
    """A connector-facing rejection; execute() catches it and writes a
    `rejected` result via to_payload() instead of letting the process die."""

    def __init__(
        self, message, *, code="contract_violation", field=None, allowed=None, hint=None, layer="operations"
    ):
        super().__init__(message)
        self.code = code
        self.field = field
        self.allowed = allowed
        self.hint = hint
        self.layer = layer

    def to_payload(self):
        """Serialize to the `error` object of a rejected/conflict result."""
        payload = {"code": self.code, "layer": self.layer, "message": str(self)}
        if self.field is not None:
            payload["field"] = self.field
        if self.allowed is not None:
            payload["allowed"] = self.allowed
        if self.hint is not None:
            payload["hint"] = self.hint
        return payload


def contract_error(message, *, code, field=None, allowed=None, hint=None, layer="operations"):
    """Build an OperationError with a code checked against the closed taxonomy."""
    if code not in ERROR_CODES:
        raise ValueError(f"unknown OperationError code: {code!r}")
    return OperationError(message, code=code, field=field, allowed=allowed, hint=hint, layer=layer)


class BatchConflict(OperationError):
    """Raised for one child of an atomic batch; apply_operation() rolls the
    whole batch back so no partial write survives."""

    def __init__(self, details):
        super().__init__(details.get("reason", "batch_child_conflict"))
        self.details = details


def die(message):
    """Print to stderr and exit 1, matching jobs.py's own CLI error convention."""
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def print_json(value):
    """Print one line of deterministic (sorted-key) JSON for machine reading."""
    print(json.dumps(value, ensure_ascii=False, sort_keys=True))


def utc_now():
    """Return the current instant as an ISO-8601 UTC timestamp string."""
    return utc_timestamp()


def clean_text(value, field):
    """Reject anything but a single-line string for a connector-supplied field."""
    if not isinstance(value, str):
        raise OperationError(f"{field} must be a string")
    if "\n" in value or "\r" in value:
        raise OperationError(f"{field} must not contain a newline")
    return value


def resolve_request_path(value):
    """Resolve a request path and confirm it is a direct .json file inside
    data/operations/requests, rejecting traversal outside that directory."""
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
    """Path a result for this operation_id would live at, existing or not."""
    return RESULTS_DIR / f"{operation_id}.json"


def validate_expected(expected, prefix="expected"):
    """Check the optimistic-locking `expected` object's shape (non-empty dict)."""
    if not isinstance(expected, dict) or not expected:
        raise OperationError(f"{prefix} must be a non-empty object")
    unknown = sorted(set(expected) - (set(jobs.FIELDS) - {"id"}))
    if unknown:
        raise OperationError(f"{prefix} contains unknown or protected fields: " + ", ".join(unknown))
    return {k: clean_text(v, f"{prefix}.{k}") for k, v in expected.items()}


def validate_verify_args(args, prefix="args"):
    """Validate a `verify` command's args against VERIFY_*_ARGS and the
    field invariants (original_url, workflow args, enum values)."""
    if not isinstance(args, dict):
        raise OperationError(f"{prefix} must be an object")
    unknown = sorted(set(args) - VERIFY_ALLOWED_ARGS)
    missing = sorted(VERIFY_REQUIRED_ARGS - set(args))
    if unknown or missing:
        parts = []
        if unknown:
            parts.append("unknown verify args: " + ", ".join(unknown))
        if missing:
            parts.append("missing verify args: " + ", ".join(missing))
        raise OperationError("; ".join(parts))
    out = {}
    for k, v in args.items():
        if k == "match_score":
            if not isinstance(v, (str, int, float)) or isinstance(v, bool):
                raise OperationError(f"{prefix}.match_score must be a string or number")
            out[k] = str(v)
        else:
            out[k] = clean_text(v, f"{prefix}.{k}")
    if out["listing_status"] not in {"open", "closed"}:
        raise contract_error(
            f"{prefix}.listing_status must be open or closed",
            code="bad_enum_value",
            field=f"{prefix}.listing_status",
            allowed=["open", "closed"],
        )
    for k in ("first_party_verified", "apply_verified"):
        if out[k] not in {"yes", "no"}:
            raise OperationError(f"{prefix}.{k} must be yes or no")
    if "decision_reason" in out and out["decision_reason"] not in ADD_VERIFY_DECISION_REASONS:
        raise OperationError(f"{prefix}.decision_reason is not allowed for verify")
    workflow = VERIFY_WORKFLOW_ARGS & set(out)
    if "decision_reason" in out and workflow:
        raise OperationError("workflow args cannot be combined with decision_reason")
    if "application_status" in out:
        if out["application_status"] != "apply":
            raise OperationError("verify may set application_status only to apply")
        if not out.get("next_action", "").strip():
            raise OperationError("application_status=apply requires a non-empty next_action")
        if not (
            out["listing_status"] == "open"
            and out["first_party_verified"] == "yes"
            and out["apply_verified"] == "yes"
        ):
            raise OperationError("application_status=apply requires a passed open verification")
    elif workflow:
        raise OperationError("next_action and next_action_date require application_status=apply")
    if "next_action_date" in out:
        try:
            datetime.strptime(out["next_action_date"], "%Y-%m-%d")
        except ValueError as error:
            raise OperationError(f"{prefix}.next_action_date must be YYYY-MM-DD") from error
    if "level" in out and out["level"] not in jobs.LEVELS:
        raise OperationError(f"{prefix}.level is not a known level")
    if "remote_policy" in out and out["remote_policy"] not in jobs.REMOTE:
        raise OperationError(f"{prefix}.remote_policy is not a known remote policy")
    if "original_url" in out and out["original_url"] and not jobs.valid_http_url(out["original_url"]):
        raise OperationError(f"{prefix}.original_url must be an absolute http(s) URL")
    if out["first_party_verified"] == "yes" and not out.get("original_url", "").strip():
        raise contract_error(
            "first_party_verified=yes requires original_url",
            code="invariant_violation",
            field=f"{prefix}.original_url",
        )
    return out


def validate_set_args(args, prefix="args"):
    """Validate a `set` command's args against the small SET_ALLOWED_ARGS list."""
    if not isinstance(args, dict) or not args:
        raise OperationError(f"{prefix} must be a non-empty object")
    unknown = sorted(set(args) - SET_ALLOWED_ARGS)
    if unknown:
        raise OperationError("unknown set args: " + ", ".join(unknown))
    out = {k: clean_text(v, f"{prefix}.{k}") for k, v in args.items()}
    if "next_action" in out and not out["next_action"].strip():
        raise OperationError(f"{prefix}.next_action must not be empty")
    if "next_action_date" in out:
        try:
            datetime.strptime(out["next_action_date"], "%Y-%m-%d")
        except ValueError as error:
            raise OperationError(f"{prefix}.next_action_date must be YYYY-MM-DD") from error
    if "listing_status" in out and out["listing_status"] != "closed":
        raise OperationError("agent set may only record listing_status=closed")
    return out


def validate_screen_args(args, prefix="args"):
    """Validate a `screen` command's args: required decision_reason plus
    notes required when the reason is `other`."""
    if not isinstance(args, dict):
        raise OperationError(f"{prefix} must be an object")
    unknown = sorted(set(args) - SCREEN_ALLOWED_ARGS)
    missing = sorted(SCREEN_REQUIRED_ARGS - set(args))
    if unknown or missing:
        parts = []
        if unknown:
            parts.append("unknown screen args: " + ", ".join(unknown))
        if missing:
            parts.append("missing screen args: " + ", ".join(missing))
        raise OperationError("; ".join(parts))
    out = {k: clean_text(v, f"{prefix}.{k}") for k, v in args.items()}
    if out["decision_reason"] not in jobs.SCREEN_REASONS:
        raise OperationError(f"{prefix}.decision_reason is not allowed for screen")
    if out["decision_reason"] == "other" and not out.get("notes", "").strip():
        raise OperationError("screen decision_reason=other requires non-empty notes")
    return out


def validate_status_args(args, prefix="args"):
    """Validate a `status` command's args, requiring confirmed_by_user=true
    since a status lifecycle event may only be recorded after a human confirms it."""
    if not isinstance(args, dict):
        raise contract_error(f"{prefix} must be an object", code="bad_type", field=prefix)
    unknown = sorted(set(args) - STATUS_ALLOWED_ARGS)
    missing = sorted(STATUS_REQUIRED_ARGS - set(args))
    if unknown:
        raise contract_error(
            "unknown status args: " + ", ".join(unknown),
            code="unknown_args",
            field=f"{prefix}.{unknown[0]}",
            allowed=sorted(STATUS_ALLOWED_ARGS),
        )
    if missing:
        raise contract_error(
            "missing status args: " + ", ".join(missing),
            code="missing_args",
            field=f"{prefix}.{missing[0]}",
            allowed=sorted(STATUS_REQUIRED_ARGS),
        )
    if args["confirmed_by_user"] is not True:
        raise contract_error(
            f"{prefix}.confirmed_by_user must be true",
            code="bad_type",
            field=f"{prefix}.confirmed_by_user",
            hint="set confirmed_by_user to true only after the human sends the operation",
        )
    out = {"confirmed_by_user": True}
    for k, v in args.items():
        if k == "confirmed_by_user":
            continue
        out[k] = clean_text(v, f"{prefix}.{k}")
    if out["application_status"] not in jobs.APPLICATION_STATUSES:
        raise contract_error(
            f"{prefix}.application_status is not a known status",
            code="bad_enum_value",
            field=f"{prefix}.application_status",
            allowed=sorted(jobs.APPLICATION_STATUSES),
        )
    if "stage" in out and out["stage"] not in jobs.STAGES:
        raise contract_error(
            f"{prefix}.stage is not a known stage",
            code="bad_enum_value",
            field=f"{prefix}.stage",
            allowed=sorted(jobs.STAGES),
        )
    if "decision_reason" in out and out["decision_reason"] not in STATUS_DECISION_REASONS:
        raise contract_error(
            f"{prefix}.decision_reason is not allowed for status",
            code="bad_enum_value",
            field=f"{prefix}.decision_reason",
            allowed=sorted(STATUS_DECISION_REASONS),
        )
    for k in ("applied_at", "response_at", "next_action_date"):
        if k in out and out[k]:
            try:
                datetime.strptime(out[k], "%Y-%m-%d")
            except ValueError as error:
                raise contract_error(
                    f"{prefix}.{k} must be YYYY-MM-DD",
                    code="bad_format",
                    field=f"{prefix}.{k}",
                    hint="use YYYY-MM-DD",
                ) from error
    return out


def validate_add_args(args, prefix="args"):
    """Validate an `add` command's args: allowed/required fields, enum
    values, URL and date formats, and the match_score range."""
    if not isinstance(args, dict):
        raise contract_error(f"{prefix} must be an object", code="bad_type", field=prefix)
    unknown = sorted(set(args) - ADD_ALLOWED_ARGS)
    missing = sorted(ADD_REQUIRED_ARGS - set(args))
    if unknown:
        first = unknown[0]
        raise contract_error(
            "unknown add args: " + ", ".join(unknown),
            code="unknown_args",
            field=f"{prefix}.{first}",
            allowed=sorted(ADD_ALLOWED_ARGS),
            hint=ADD_UNKNOWN_ARG_HINTS.get(first),
        )
    if missing:
        raise contract_error(
            "missing add args: " + ", ".join(missing),
            code="missing_args",
            field=f"{prefix}.{missing[0]}",
            allowed=sorted(ADD_REQUIRED_ARGS),
        )
    out = {}
    for k, v in args.items():
        if k == "force":
            if not isinstance(v, bool):
                raise contract_error(
                    f"{prefix}.force must be a boolean", code="bad_type", field=f"{prefix}.force"
                )
            out[k] = v
        elif k == "match_score":
            if not isinstance(v, (str, int, float)) or isinstance(v, bool):
                raise contract_error(
                    f"{prefix}.match_score must be a string or number",
                    code="bad_type",
                    field=f"{prefix}.match_score",
                )
            out[k] = str(v)
        else:
            out[k] = clean_text(v, f"{prefix}.{k}")
    for k in ADD_REQUIRED_ARGS:
        if not out[k].strip():
            raise contract_error(f"{prefix}.{k} must not be empty", code="bad_format", field=f"{prefix}.{k}")
    if out["source"] not in jobs.SOURCES:
        raise contract_error(
            f"{prefix}.source is not a known source",
            code="bad_enum_value",
            field=f"{prefix}.source",
            allowed=sorted(jobs.SOURCES),
        )
    if out.get("application_status", "not_started") not in CONNECTOR_ADD_APPLICATION_STATUSES:
        raise contract_error(
            "add may set application_status only to not_started or reviewing",
            code="bad_enum_value",
            field=f"{prefix}.application_status",
            allowed=sorted(CONNECTOR_ADD_APPLICATION_STATUSES),
        )
    for k, allowed in (
        ("listing_status", jobs.LISTING_STATUSES),
        ("first_party_verified", jobs.VERIFICATION),
        ("apply_verified", jobs.VERIFICATION),
        ("level", jobs.LEVELS),
        ("remote_policy", jobs.REMOTE),
    ):
        if k in out and out[k] not in allowed:
            raise contract_error(
                f"{prefix}.{k} is not a known value",
                code="bad_enum_value",
                field=f"{prefix}.{k}",
                allowed=sorted(allowed),
            )
    for k in ("original_url", "source_url"):
        if out.get(k) and not jobs.valid_http_url(out[k]):
            raise contract_error(
                f"{prefix}.{k} must be an absolute http(s) URL", code="bad_format", field=f"{prefix}.{k}"
            )
    for k in ("posted_at", "found_at"):
        if out.get(k):
            try:
                datetime.strptime(out[k], "%Y-%m-%d")
            except ValueError as error:
                raise contract_error(
                    f"{prefix}.{k} must be YYYY-MM-DD",
                    code="bad_format",
                    field=f"{prefix}.{k}",
                    hint="use YYYY-MM-DD",
                ) from error
    if out.get("match_score", ""):
        try:
            score = float(out["match_score"])
        except ValueError as error:
            raise contract_error(
                f"{prefix}.match_score must be a number from 1 to 10",
                code="bad_format",
                field=f"{prefix}.match_score",
            ) from error
        if not math.isfinite(score) or not 1 <= score <= 10:
            raise contract_error(
                f"{prefix}.match_score must be a number from 1 to 10",
                code="bad_format",
                field=f"{prefix}.match_score",
            )
    reason = out.get("decision_reason", "")
    if reason and reason not in ADD_VERIFY_DECISION_REASONS:
        raise contract_error(
            f"{prefix}.decision_reason is not allowed for add",
            code="bad_enum_value",
            field=f"{prefix}.decision_reason",
            allowed=sorted(ADD_VERIFY_DECISION_REASONS),
        )
    if reason == "other" and not out.get("notes", "").strip():
        raise contract_error(
            "add decision_reason=other requires non-empty notes",
            code="invariant_violation",
            field=f"{prefix}.notes",
        )
    status = out.get("application_status", "not_started")
    if reason and status != "not_started":
        raise contract_error(
            "add decision_reason requires application_status=not_started",
            code="invariant_violation",
            field=f"{prefix}.decision_reason",
        )
    listing = out.get("listing_status", "unknown")
    if reason == "closed_before_application" and listing != "closed":
        raise contract_error(
            "closed_before_application requires listing_status=closed",
            code="invariant_violation",
            field=f"{prefix}.listing_status",
        )
    if listing == "closed" and status == "not_started" and reason != "closed_before_application":
        raise contract_error(
            "listing_status=closed before application requires decision_reason=closed_before_application",
            code="invariant_violation",
            field=f"{prefix}.decision_reason",
        )
    first_party = out.get("first_party_verified", "unknown")
    apply_verified = out.get("apply_verified", "unknown")
    if first_party == "yes" and not out.get("original_url", ""):
        raise contract_error(
            "first_party_verified=yes requires original_url",
            code="invariant_violation",
            field=f"{prefix}.original_url",
        )
    if apply_verified == "yes" and first_party != "yes":
        raise contract_error(
            "apply_verified=yes requires first_party_verified=yes",
            code="invariant_violation",
            field=f"{prefix}.apply_verified",
        )
    if out["source"] not in jobs.SOURCES_WITHOUT_EXTERNAL_REFERENCE and not (
        out.get("source_url", "").strip() or out.get("source_job_id", "").strip()
    ):
        raise contract_error(
            "external add requires source_url or source_job_id",
            code="invariant_violation",
            field=f"{prefix}.source_url",
        )
    duplicate_of = out.get("duplicate_of", "")
    if "duplicate_of" in out and not duplicate_of:
        raise contract_error(
            f"{prefix}.duplicate_of must not be empty", code="bad_format", field=f"{prefix}.duplicate_of"
        )
    if duplicate_of:
        if not JOB_ID_RE.fullmatch(duplicate_of):
            raise contract_error(
                f"{prefix}.duplicate_of must be job-NNNN",
                code="bad_format",
                field=f"{prefix}.duplicate_of",
                hint="use job-NNNN",
            )
        ignored = sorted(set(out) - ADD_DUPLICATE_ARGS)
        if ignored:
            raise contract_error(
                "duplicate add contains canonical fields that would be ignored: " + ", ".join(ignored),
                code="duplicate_add_extra_fields",
                field=f"{prefix}.{ignored[0]}",
                allowed=sorted(ADD_DUPLICATE_ARGS),
                hint="a duplicate add only takes source_url/source_job_id (plus force); canonical fields belong to the original job",
            )
        if not (out.get("source_url", "").strip() or out.get("source_job_id", "").strip()):
            raise contract_error(
                "duplicate add requires source_url or source_job_id",
                code="invariant_violation",
                field=f"{prefix}.source_url",
            )
    return out


def require_field_set(value, allowed, required, prefix):
    """Reject any top-level field outside `allowed` or missing from `required`."""
    unknown = sorted(set(value) - allowed)
    missing = sorted(required - set(value))
    if unknown:
        raise contract_error(
            f"{prefix}: unknown fields: " + ", ".join(unknown),
            code="unknown_top_level_fields",
            field=f"{prefix}.{unknown[0]}",
            allowed=sorted(allowed),
        )
    if missing:
        raise contract_error(
            f"{prefix}: missing fields: " + ", ".join(missing),
            code="missing_top_level_fields",
            field=f"{prefix}.{missing[0]}",
            allowed=sorted(required),
        )


def validate_child(value, index=None):
    """Validate one batch child (or a lone non-batch operation) and return
    its normalized {command, job_id/client_ref, expected, args}."""
    prefix = f"operations[{index}]" if index is not None else "operation"
    if not isinstance(value, dict):
        raise contract_error(f"{prefix} must be an object", code="bad_type", field=prefix)
    command = clean_text(value.get("command"), f"{prefix}.command") if "command" in value else None
    if command == "add":
        require_field_set(value, ADD_CHILD_FIELDS, ADD_CHILD_FIELDS, prefix)
        client_ref = clean_text(value["client_ref"], f"{prefix}.client_ref").strip()
        if not client_ref:
            raise contract_error(
                f"{prefix}.client_ref must not be empty", code="bad_format", field=f"{prefix}.client_ref"
            )
        if len(client_ref) > 200:
            raise contract_error(
                f"{prefix}.client_ref must not exceed 200 characters",
                code="bad_format",
                field=f"{prefix}.client_ref",
            )
        return {
            "command": "add",
            "client_ref": client_ref,
            "args": validate_add_args(value["args"], f"{prefix}.args"),
        }
    require_field_set(value, JOB_CHILD_FIELDS, JOB_CHILD_FIELDS, prefix)
    if command not in {"screen", "verify", "set", "status"}:
        raise contract_error(
            f"{prefix}.command must be screen, verify, set or status",
            code="unsupported_command",
            field=f"{prefix}.command",
            allowed=["screen", "verify", "set", "status"],
        )
    job_id = clean_text(value["job_id"], f"{prefix}.job_id")
    if not JOB_ID_RE.fullmatch(job_id):
        raise contract_error(
            f"{prefix}.job_id must be job-NNNN",
            code="bad_format",
            field=f"{prefix}.job_id",
            hint="use job-NNNN",
        )
    expected = validate_expected(value["expected"], f"{prefix}.expected")
    if command == "verify":
        args = validate_verify_args(value["args"], f"{prefix}.args")
    elif command == "screen":
        args = validate_screen_args(value["args"], f"{prefix}.args")
    elif command == "status":
        args = validate_status_args(value["args"], f"{prefix}.args")
    else:
        args = validate_set_args(value["args"], f"{prefix}.args")
    return {"command": command, "job_id": job_id, "expected": expected, "args": args}


def validate_operation(value):
    """Validate a whole request's top-level shape and dispatch to the
    per-command/batch-child validators; returns the normalized operation."""
    if not isinstance(value, dict):
        raise contract_error("request must be a JSON object", code="bad_type", field="request")
    if value.get("version") != OPERATION_VERSION:
        raise contract_error(
            f"version must be {OPERATION_VERSION}",
            code="bad_enum_value",
            field="version",
            allowed=[OPERATION_VERSION],
        )
    operation_id = clean_text(value.get("operation_id"), "operation_id") if "operation_id" in value else None
    if operation_id is None or not OPERATION_ID_RE.fullmatch(operation_id):
        raise contract_error(
            "operation_id must use lowercase letters, digits, '.', '_' or '-'",
            code="bad_format",
            field="operation_id",
        )
    command = clean_text(value.get("command"), "command") if "command" in value else None
    if command == "add":
        require_field_set(value, ADD_TOP_LEVEL_FIELDS, ADD_TOP_LEVEL_FIELDS, "operation")
        return {
            "version": OPERATION_VERSION,
            "operation_id": operation_id,
            "command": "add",
            "args": validate_add_args(value["args"]),
        }
    if command == "batch":
        require_field_set(value, BATCH_TOP_LEVEL_FIELDS, BATCH_TOP_LEVEL_FIELDS, "operation")
        atomic = value["atomic"]
        if not isinstance(atomic, bool):
            raise contract_error(
                "batch.atomic must be a boolean",
                code="batch_not_atomic",
                field="atomic",
                allowed=[True, False],
            )
        entries = value["operations"]
        if not isinstance(entries, list) or not entries:
            raise contract_error(
                "batch.operations must be a non-empty array", code="bad_type", field="operations"
            )
        limit = MAX_ATOMIC_BATCH_OPERATIONS if atomic else MAX_BATCH_OPERATIONS
        if len(entries) > limit:
            hint = (
                f"atomic batches are capped at {MAX_ATOMIC_BATCH_OPERATIONS} entries; split it up or set atomic=false"
                if atomic
                else f"split into batches of at most {MAX_BATCH_OPERATIONS}"
            )
            raise contract_error(
                f"batch.operations exceeds {limit} entries", code="bad_format", field="operations", hint=hint
            )
        operations = [validate_child(entry, i) for i, entry in enumerate(entries)]
        ids = [x["job_id"] for x in operations if x["command"] != "add"]
        if len(ids) != len(set(ids)):
            raise contract_error(
                "batch may contain each job_id only once", code="invariant_violation", field="operations"
            )
        client_refs = [x["client_ref"] for x in operations if x["command"] == "add"]
        if len(client_refs) != len(set(client_refs)):
            raise contract_error(
                "batch may contain each add client_ref only once",
                code="invariant_violation",
                field="operations",
            )
        return {
            "version": OPERATION_VERSION,
            "operation_id": operation_id,
            "command": "batch",
            "atomic": atomic,
            "operations": operations,
        }
    require_field_set(value, SINGLE_TOP_LEVEL_FIELDS, SINGLE_TOP_LEVEL_FIELDS, "operation")
    if command not in {"screen", "verify", "set", "status"}:
        raise contract_error(
            "command must be add, screen, verify, set, status, or batch",
            code="unsupported_command",
            field="command",
            allowed=["add", "screen", "verify", "set", "status", "batch"],
        )
    child = validate_child(
        {"command": command, "job_id": value["job_id"], "expected": value["expected"], "args": value["args"]}
    )
    return {"version": OPERATION_VERSION, "operation_id": operation_id, **child}


def load_operation(path):
    """Read, size-check and JSON-parse a request file, then validate it."""
    path = resolve_request_path(path)
    try:
        raw = path.read_bytes()
    except OSError as error:
        raise OperationError(f"cannot read request: {error}") from error
    if len(raw) > MAX_REQUEST_BYTES:
        raise contract_error(
            f"request exceeds {MAX_REQUEST_BYTES} bytes",
            code="request_too_large",
            hint=f"keep the request under {MAX_REQUEST_BYTES} bytes",
        )
    try:
        value = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise contract_error(f"request is not valid UTF-8 JSON: {error}", code="invalid_json") from error
    operation = validate_operation(value)
    if path.name != f"{operation['operation_id']}.json":
        raise contract_error(
            "request filename must equal operation_id + '.json'",
            code="filename_mismatch",
            field="operation_id",
            hint="name the file <operation_id>.json",
        )
    return operation


def read_job(job_id):
    """Look up one canonical row by id, or raise the `unknown_job` rejection."""
    for row in jobs.load():
        if row["id"] == job_id:
            return row
    raise contract_error(f"job {job_id} was not found", code="unknown_job", field="job_id")


def precondition_mismatches(row, expected):
    """Diff `expected` against the live row for optimistic-locking; empty
    means the row still matches what the operation was written against."""
    return {k: {"expected": v, "actual": row.get(k, "")} for k, v in expected.items() if row.get(k, "") != v}


def classify_child_risk(operation, row):
    """Classify one job-targeting command's write risk (low/medium) from
    its command and, for verify, whether it just passed a first-party check."""
    if operation["command"] == "add":
        return "medium"
    if operation["command"] == "status":
        return "medium"
    if operation["command"] in {"screen", "set"}:
        return "low"
    args = operation["args"]
    passed = (
        args["listing_status"] == "open"
        and args["first_party_verified"] == "yes"
        and args["apply_verified"] == "yes"
    )
    if (VERIFY_ENRICHMENT_ARGS | VERIFY_WORKFLOW_ARGS) & set(args):
        return "medium"
    if passed and row["application_status"] == "not_started":
        return "medium"
    return "low"


def classify_risk(operation, rows_by_id=None):
    """Classify a whole operation's risk: a batch is medium if any child is."""
    if operation["command"] == "add":
        return "medium"
    if operation["command"] != "batch":
        row = rows_by_id[operation["job_id"]] if rows_by_id is not None else read_job(operation["job_id"])
        return classify_child_risk(operation, row)
    rows_by_id = rows_by_id or {row["id"]: row for row in jobs.load()}
    return (
        "medium"
        if any(
            classify_child_risk(child, rows_by_id.get(child.get("job_id"))) == "medium"
            for child in operation["operations"]
        )
        else "low"
    )


def apply_operation(operation, row):
    """Dispatch a validated, precondition-checked job-targeting command to
    the matching jobs.py write function and normalize its result shape."""
    if operation["command"] == "verify":
        result = jobs.verify_job(operation["job_id"], **operation["args"])
        return {
            "job": result["job"],
            "warnings": result["warnings"],
            "outcome": result["outcome"],
            "application_path": result.get("application_path"),
        }
    if operation["command"] == "screen":
        result = jobs.screen_job(operation["job_id"], **operation["args"])
        return {
            "job": result["job"],
            "warnings": result["warnings"],
            "outcome": result["outcome"],
            "application_path": None,
        }
    if operation["command"] == "status":
        args = dict(operation["args"])
        args.pop("confirmed_by_user")
        result = jobs.status_job(operation["job_id"], **args)
        return {
            "job": result["job"],
            "warnings": result["warnings"],
            "outcome": result["outcome"],
            "application_path": result.get("application_path"),
        }
    if "listing_status" in operation["args"] and row["application_status"] not in jobs.NEEDS_APPLIED_AT:
        raise contract_error(
            "listing_status=closed through set is allowed only after an application exists",
            code="invariant_violation",
            field="args.listing_status",
        )
    result = jobs.set_job(operation["job_id"], list(operation["args"].items()))
    return {
        "job": result["job"],
        "warnings": result["warnings"],
        "outcome": "updated",
        "application_path": None,
    }


def operation_result(operation, *, status, risk, details, job_id=None):
    """Build the version/operation_id/status/risk envelope common to every
    result, adding job_id or the batch's child job ids as appropriate."""
    result = {
        "version": OPERATION_VERSION,
        "operation_id": operation["operation_id"],
        "status": status,
        "executed_at": utc_now(),
        "risk": risk,
        "command": operation["command"],
        "result": details,
    }
    if operation["command"] == "add":
        if job_id:
            result["job_id"] = job_id
    elif operation["command"] == "batch":
        result["jobs"] = [child["job_id"] for child in operation["operations"] if child["command"] != "add"]
    else:
        result["job_id"] = operation["job_id"]
    return result


def write_result(result):
    """Write a result immutably: `x` mode refuses to overwrite an existing one."""
    path = result_path(result["operation_id"])
    if path.exists():
        raise contract_error(
            f"operation_id already has a result: {path.relative_to(ROOT)}",
            code="result_exists",
            field="operation_id",
            hint="retry with a new operation_id; results are immutable",
        )
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(result, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
    except OSError as error:
        raise OperationError(f"cannot write operation result: {error}") from error
    return path


@contextmanager
def temporary_tracker_workspace(*, include_card_revisions=False):
    """Repoint jobs.PATHS at a scratch copy of the tracker for one operation.

    docs/agent-write-path-plan-2026-09-07.md, Э10: jobs.py derives every path
    (csv_path, apps_dir, template_path, ...) from `PATHS.root`, so reassigning
    that one field is enough; nothing here has to know the individual derived
    paths.
    """
    original_root = jobs.PATHS.root
    with tempfile.TemporaryDirectory(prefix="agent-batch-") as directory:
        temp_root = Path(directory)
        temp_data = temp_root / "data"
        temp_apps = temp_root / "applications"
        temp_data.mkdir(parents=True)
        with jobs.dataset_write_lock():
            shutil.copy2(original_root / "data" / "jobs.csv", temp_data / "jobs.csv")
            shutil.copy2(original_root / "data" / "job_sources.csv", temp_data / "job_sources.csv")
            shutil.copytree(original_root / "applications", temp_apps)
        card_revisions = {
            path.relative_to(temp_root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
            for path in temp_apps.glob("job-*.md")
        }
        try:
            jobs.PATHS.root = temp_root
            yield (temp_root, card_revisions) if include_card_revisions else temp_root
        finally:
            jobs.PATHS.root = original_root


def changed_application_writes(temp_root, card_revisions):
    """Find application cards the temporary workspace created or changed,
    so they can be copied back into the real applications/ directory."""
    writes = []
    for temp_path in sorted((temp_root / "applications").glob("job-*.md")):
        relative = temp_path.relative_to(temp_root)
        target = ROOT / relative
        body = temp_path.read_text(encoding="utf-8")
        prior_revision = card_revisions.get(relative.as_posix())
        if hashlib.sha256(body.encode("utf-8")).hexdigest() != prior_revision:
            writes.append((target, body, prior_revision))
    return writes


def batch_preconditions(operation, rows_by_id):
    """Return per-child optimistic-lock conflicts (stale `expected`) for
    every job-targeting child, keyed by job_id."""
    conflicts = []
    for child in operation["operations"]:
        if child["command"] == "add":
            continue
        row = rows_by_id.get(child["job_id"])
        if row is None:
            raise contract_error(f"job {child['job_id']} was not found", code="unknown_job", field="job_id")
        mismatches = precondition_mismatches(row, child["expected"])
        if mismatches:
            conflicts.append(
                {
                    "job_id": child["job_id"],
                    "command": child["command"],
                    "mismatches": mismatches,
                    "retry": stale_retry_fragment(
                        child["command"], child["job_id"], child["expected"], child["args"], mismatches
                    ),
                }
            )
    return conflicts


def add_retry_fragments(args, error, client_ref=None):
    """Ready-to-send `add` requests for a duplicate/source-reference conflict
    (P5, Э4): as_separate always resends the same args with force=true;
    as_duplicate attaches a source reference to the one job the conflict
    unambiguously points at, and is omitted when a fuzzy duplicate matched
    more than one candidate (the caller must pick)."""
    base = {k: v for k, v in args.items() if k not in ("force", "duplicate_of")}

    def shape(inner_args):
        fragment = {"command": "add", "args": inner_args}
        if client_ref is not None:
            fragment["client_ref"] = client_ref
        return fragment

    fragments = {"as_separate": shape({**base, "force": True})}
    if isinstance(error, jobs.UnresolvedDuplicate):
        candidate_ids = list(error.candidates.keys())
        duplicate_of = candidate_ids[0] if len(candidate_ids) == 1 else None
    else:
        duplicate_of = error.existing["job_id"]
    if duplicate_of:
        dup_args = {k: v for k, v in base.items() if k in ADD_DUPLICATE_ARGS}
        dup_args["duplicate_of"] = duplicate_of
        fragments["as_duplicate"] = shape(dup_args)
    return fragments


def add_conflict_details(error, args, client_ref=None):
    """Build the `result` object for an add that hit a duplicate or
    source-reference conflict, including its retry fragments."""
    if isinstance(error, jobs.UnresolvedDuplicate):
        candidates = [
            {
                "id": row["id"],
                "company": row["company"],
                "role": row["role"],
                "application_status": row["application_status"],
                "listing_status": row["listing_status"],
                "reason": reason_en,
            }
            for row, _reason_ru, reason_en in error.candidates.values()
        ]
        details = {"reason": "unresolved_duplicate", "candidates": candidates}
    else:
        details = {
            "reason": "source_reference_conflict",
            "message": error.message_en,
            "existing": error.existing,
        }
    details["retry"] = add_retry_fragments(args, error, client_ref=client_ref)
    return details


def refreshed_expected(expected, mismatches):
    """The same optimistic lock with each stale field replaced by its current
    actual value, so a stale_operation retry fragment is valid without the
    caller having to re-derive it (P5, Э4)."""
    return {**expected, **{k: v["actual"] for k, v in mismatches.items()}}


def stale_retry_fragment(command, job_id, expected, args, mismatches):
    """A ready-to-send retry for one child that failed its optimistic lock."""
    return {
        "command": command,
        "job_id": job_id,
        "expected": refreshed_expected(expected, mismatches),
        "args": args,
    }


def apply_add(operation):
    """Run a validated `add` (single or batch child) and shape its result,
    resolving duplicate_of to a source reference when given."""
    args = dict(operation["args"])
    force = args.pop("force", False)
    duplicate_of = args.pop("duplicate_of", None)
    if duplicate_of and not any(row["id"] == duplicate_of for row in jobs.load()):
        raise contract_error(
            f"job {duplicate_of} was not found", code="unknown_job", field="args.duplicate_of"
        )
    applied = jobs.add_job(args, force=force, duplicate_of=duplicate_of, no_file=False)
    updated = applied["job"]
    return updated, {
        "outcome": "source_reference_added" if applied.get("duplicate_of") else "job_added",
        "job_id": updated["id"],
        "application_status": updated["application_status"],
        "listing_status": updated["listing_status"],
        "application_path": applied.get("application_path"),
        "source_reference": applied.get("source_reference"),
        "warnings": applied["warnings"],
    }


def execute_batch(operation, atomic, stale_conflicts):
    """Applies every batch child inside one isolated transaction.

    atomic=True keeps the original all-or-nothing behavior: any child conflict
    raises BatchConflict, which aborts before the transaction is ever
    committed. atomic=False instead records a conflicting child with its own
    status and excludes it from the applied set (P6, Э4); `stale_conflicts`
    (job_id -> precomputed batch_preconditions() entry) lets it skip a stale
    non-add child without recomputing its mismatches.
    """
    child_results = []
    applied = 0
    base_rows, base_sources, expected_revisions = jobs.load_for_write()
    with temporary_tracker_workspace(include_card_revisions=True) as (temp_root, card_revisions):
        if jobs.load() != base_rows or jobs.load_job_sources() != base_sources:
            raise jobs.ValidationError(
                "dataset changed while preparing the batch workspace",
                code="stale_operation",
            )
        for index, child in enumerate(operation["operations"]):
            if child["command"] == "add":
                try:
                    updated, details = apply_add(child)
                except (jobs.UnresolvedDuplicate, jobs.SourceReferenceConflict) as error:
                    conflict = add_conflict_details(error, child["args"], client_ref=child["client_ref"])
                    if atomic:
                        raise BatchConflict(
                            {
                                "reason": "batch_child_conflict",
                                "index": index,
                                "command": "add",
                                "client_ref": child["client_ref"],
                                "conflict": conflict,
                            }
                        ) from error
                    child_results.append(
                        {
                            "client_ref": child["client_ref"],
                            "command": "add",
                            "status": "conflict",
                            "conflict": conflict,
                        }
                    )
                    continue
                child_results.append(
                    {"client_ref": child["client_ref"], "command": "add", "status": "completed", **details}
                )
                applied += 1
                continue
            if child["job_id"] in stale_conflicts:
                conflict = stale_conflicts[child["job_id"]]
                child_results.append(
                    {
                        "job_id": child["job_id"],
                        "command": child["command"],
                        "status": "conflict",
                        "reason": "stale_operation",
                        "mismatches": conflict["mismatches"],
                        "retry": conflict["retry"],
                    }
                )
                continue
            current = read_job(child["job_id"])
            applied_child = apply_operation(child, current)
            updated = applied_child["job"]
            child_results.append(
                {
                    "job_id": child["job_id"],
                    "command": child["command"],
                    "status": "completed",
                    "outcome": applied_child["outcome"],
                    "application_status": updated["application_status"],
                    "listing_status": updated["listing_status"],
                    "stage_reached": updated["stage_reached"],
                    "warnings": applied_child["warnings"],
                }
            )
            applied += 1
        temp_rows = [dict(row) for row in jobs.load()]
        temp_sources = [dict(row) for row in jobs.load_job_sources()]
        errors, warnings = jobs.validate_dataset(temp_rows, temp_sources)
        if errors:
            raise contract_error(
                "batch dataset validation failed: " + "; ".join(errors),
                code="invariant_violation",
                layer="jobs",
            )
        app_writes = changed_application_writes(temp_root, card_revisions)
    if applied:
        jobs.apply_dataset_transaction(
            temp_rows, temp_sources, app_writes, expected_revisions=expected_revisions
        )
    return child_results, warnings, applied


def _execute_operation(operation):
    """Apply a validated operation (add / batch / single job command) and
    write its result; the top-level dispatcher `execute()` catches everything
    this can raise and turns it into a `rejected` result instead."""
    if operation["command"] == "add":
        risk = "medium"
        try:
            updated, details = apply_add(operation)
        except jobs.UnresolvedDuplicate as error:
            result = operation_result(
                operation,
                status="conflict",
                risk=risk,
                details=add_conflict_details(error, operation["args"]),
            )
            return result, write_result(result)
        except jobs.SourceReferenceConflict as error:
            result = operation_result(
                operation,
                status="conflict",
                risk=risk,
                details=add_conflict_details(error, operation["args"]),
            )
            return result, write_result(result)
        errors, validation_warnings = jobs.validate_dataset(jobs.load(), jobs.load_job_sources())
        if errors:
            raise contract_error(
                "post-operation dataset validation failed: " + "; ".join(errors),
                code="invariant_violation",
                layer="jobs",
            )
        details["warnings"] = [*details["warnings"], *validation_warnings]
        result = operation_result(
            operation, status="completed", risk=risk, details=details, job_id=updated["id"]
        )
        return result, write_result(result)
    if operation["command"] == "batch":
        atomic = operation["atomic"]
        rows_by_id = {row["id"]: row for row in jobs.load()}
        conflicts = batch_preconditions(operation, rows_by_id)
        risk = classify_risk(operation, rows_by_id)
        if atomic:
            if conflicts:
                result = operation_result(
                    operation,
                    status="conflict",
                    risk=risk,
                    details={"reason": "stale_operation", "conflicts": conflicts},
                )
                return result, write_result(result)
            try:
                children, warnings, _applied = execute_batch(operation, atomic=True, stale_conflicts={})
            except BatchConflict as error:
                result = operation_result(operation, status="conflict", risk=risk, details=error.details)
                return result, write_result(result)
            result = operation_result(
                operation,
                status="completed",
                risk=risk,
                details={
                    "outcome": "atomic_batch_applied",
                    "count": len(children),
                    "total": len(children),
                    "operations": children,
                    "warnings": warnings,
                },
            )
            return result, write_result(result)
        stale_by_job_id = {conflict["job_id"]: conflict for conflict in conflicts}
        children, warnings, applied = execute_batch(operation, atomic=False, stale_conflicts=stale_by_job_id)
        total = len(children)
        conflicted = total - applied
        if applied == 0:
            status, outcome = "conflict", "batch_fully_conflicted"
        elif conflicted == 0:
            status, outcome = "completed", "batch_applied"
        else:
            status, outcome = "partial", "partial_batch_applied"
        result = operation_result(
            operation,
            status=status,
            risk=risk,
            details={
                "outcome": outcome,
                "count": applied,
                "total": total,
                "operations": children,
                "warnings": warnings,
            },
        )
        return result, write_result(result)
    row = read_job(operation["job_id"])
    risk = classify_risk(operation, {row["id"]: row})
    mismatches = precondition_mismatches(row, operation["expected"])
    if mismatches:
        retry = stale_retry_fragment(
            operation["command"], operation["job_id"], operation["expected"], operation["args"], mismatches
        )
        result = operation_result(
            operation,
            status="conflict",
            risk=risk,
            details={"reason": "stale_operation", "mismatches": mismatches, "retry": retry},
        )
        return result, write_result(result)
    applied = apply_operation(operation, row)
    updated = applied["job"]
    errors, validation_warnings = jobs.validate_dataset(jobs.load(), jobs.load_job_sources())
    if errors:
        raise contract_error(
            "post-operation dataset validation failed: " + "; ".join(errors),
            code="invariant_violation",
            layer="jobs",
        )
    result = operation_result(
        operation,
        status="completed",
        risk=risk,
        details={
            "outcome": applied["outcome"],
            "application_status": updated["application_status"],
            "listing_status": updated["listing_status"],
            "stage_reached": updated["stage_reached"],
            "application_path": applied.get("application_path"),
            "warnings": [*applied["warnings"], *validation_warnings],
        },
    )
    return result, write_result(result)


def derive_operation_id(path):
    """The result path is keyed by the request's filename, not its JSON
    body: an unparseable or mismatched request still gets a rejected result."""
    stem = Path(path).stem
    return stem if OPERATION_ID_RE.fullmatch(stem) else None


def peek_command(path):
    """Best-effort top-level command for a rejected result, read independently
    of load_operation() so a bad args block still reports which command it was."""
    try:
        value = json.loads(Path(path).read_bytes().decode("utf-8"))
        command = value.get("command")
        return command if isinstance(command, str) else "unknown"
    except Exception:
        return "unknown"


def error_payload(error):
    """The `error` object for a rejected result, from whichever layer raised."""
    if isinstance(error, (OperationError, jobs.ValidationError)):
        return error.to_payload()
    return {"code": "invariant_violation", "layer": "jobs", "message": str(error)}


def rejected_result(operation_id, command, error):
    """A `status: rejected` result: canonical data is untouched by contract."""
    return {
        "version": OPERATION_VERSION,
        "operation_id": operation_id,
        "status": "rejected",
        "command": command,
        "executed_at": utc_now(),
        "risk": "none",
        "error": error_payload(error),
    }


def execute(path):
    """Top-level entry point: load, validate and apply one request, catching
    every OperationError/ValidationError/SystemExit into a rejected result
    (docs/agent-write-path-plan-2026-09-07.md, Э1) instead of letting the
    process die with no result file."""
    with jobs.dataset_write_lock():
        pass  # Recover any interrupted canonical publication before inspecting state.
    operation_id = derive_operation_id(path)
    if operation_id is not None and result_path(operation_id).exists():
        raise contract_error(
            f"operation_id already has a result: {result_path(operation_id).relative_to(ROOT)}",
            code="result_exists",
            field="operation_id",
            hint="retry with a new operation_id; results are immutable",
        )
    command = peek_command(path)
    operation = None
    try:
        operation = load_operation(path)
        command = operation["command"]
        return _execute_operation(operation)
    except (OperationError, jobs.ValidationError) as error:
        if operation_id is None:
            raise
        if operation is not None and isinstance(error, jobs.ValidationError) and error.code == "stale_operation":
            retry_keys = (
                ("command", "args") if operation["command"] == "add"
                else ("command", "atomic", "operations") if operation["command"] == "batch"
                else ("command", "job_id", "expected", "args")
            )
            result = operation_result(
                operation,
                status="conflict",
                risk="medium",
                details={
                    "reason": "stale_operation",
                    "message": "dataset changed while the operation was being prepared; retry on current data",
                    "retry": {key: operation[key] for key in retry_keys},
                },
            )
            return result, write_result(result)
        result = rejected_result(operation_id, command, error)
        return result, write_result(result)
    except SystemExit as error:
        if operation_id is None:
            raise
        wrapped = OperationError(
            f"unexpected process exit while applying the operation: {error}",
            code="invariant_violation",
            layer="jobs",
        )
        result = rejected_result(operation_id, command, wrapped)
        return result, write_result(result)


# --- render-contract (docs/agent-write-path-plan-2026-09-07.md, Э2) ---
# The tables below are assembled from the same allowlists validate_*_args()
# enforces, so contract.md cannot silently drift from what the runner accepts.
CONTRACT_PATH = ROOT / "data" / "operations" / "contract.md"
FIELD_TYPE_OVERRIDES = {
    "match_score": "number (1-10)",
    "force": "boolean",
    "confirmed_by_user": "boolean",
    "duplicate_of": "job-NNNN",
    "job_id": "job-NNNN",
    "expected": "object (subset of canonical fields, non-empty)",
    "client_ref": "text (caller-assigned, unique per request)",
    "posted_at": "date (YYYY-MM-DD)",
    "found_at": "date (YYYY-MM-DD)",
    "applied_at": "date (YYYY-MM-DD)",
    "response_at": "date (YYYY-MM-DD)",
    "next_action_date": "date (YYYY-MM-DD)",
    "original_url": "URL",
    "source_url": "URL",
}
FIELD_NOTES = {
    "force": "explicitly resolves a fuzzy duplicate candidate or a shared discovery URL",
    "duplicate_of": "attaches a new source reference to an existing job instead of creating one",
    "client_ref": "maps this child's assigned job_id back to the caller inside the result",
    "confirmed_by_user": "must be the literal boolean true; set only after the human reports or requests the event",
    "notes": "single line; long context belongs in applications/<id>.md",
    "match_score": "decimal values are allowed, e.g. 7.5",
    "stage": "stage_reached only increases; a lower stage is rejected",
    "expected": "optimistic lock; must include last_update and the fields the decision depends on",
    "job_id": "must match job-NNNN and already exist",
    "remote_policy": 'a bare "Remote" with no country list is not a valid value; use Unclear',
}
ADD_FIELD_ENUMS = {
    "source": jobs.SOURCES,
    "application_status": sorted(CONNECTOR_ADD_APPLICATION_STATUSES),
    "listing_status": jobs.LISTING_STATUSES,
    "first_party_verified": jobs.VERIFICATION,
    "apply_verified": jobs.VERIFICATION,
    "level": jobs.LEVELS,
    "remote_policy": jobs.REMOTE,
    "decision_reason": sorted(ADD_VERIFY_DECISION_REASONS),
}
VERIFY_FIELD_ENUMS = {
    "listing_status": ["open", "closed"],
    "first_party_verified": ["yes", "no"],
    "apply_verified": ["yes", "no"],
    "level": jobs.LEVELS,
    "remote_policy": jobs.REMOTE,
    "decision_reason": sorted(ADD_VERIFY_DECISION_REASONS),
    "application_status": ["apply"],
}
SCREEN_FIELD_ENUMS = {"decision_reason": sorted(jobs.SCREEN_REASONS)}
SET_FIELD_ENUMS = {"listing_status": ["closed"]}
STATUS_FIELD_ENUMS = {
    "application_status": jobs.APPLICATION_STATUSES,
    "stage": jobs.STAGES,
    "decision_reason": sorted(STATUS_DECISION_REASONS),
}
CONTRACT_INVARIANTS = [
    "`first_party_verified=yes` requires a non-empty `original_url`.",
    "`apply_verified=yes` requires `first_party_verified=yes`.",
    "`listing_status=closed` before an application requires `decision_reason=closed_before_application`.",
    "`application_status=apply` requires a passed open verification and a non-empty `next_action`.",
]
ALL_ARG_ALLOWLISTS = (
    ADD_ALLOWED_ARGS,
    VERIFY_ALLOWED_ARGS,
    SCREEN_ALLOWED_ARGS,
    SET_ALLOWED_ARGS,
    STATUS_ALLOWED_ARGS,
)


def fields_no_command_accepts():
    """Canonical fields no connector command allowlists: runner-computed only."""
    accepted = set().union(*ALL_ARG_ALLOWLISTS)
    return sorted(set(jobs.FIELDS) - accepted)


def markdown_table(headers, rows):
    """Render a plain GitHub-flavored Markdown table from string cells."""
    lines = ["| " + " | ".join(headers) + " |", "| " + " | ".join("---" for _ in headers) + " |"]
    lines += ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join(lines) + "\n"


def contract_table(fields, required, enums, notes_overrides=None):
    """One command's field table for contract.md: type, allowed values,
    required, and a note, sourced from the same allowlists validation uses."""
    notes_overrides = notes_overrides or {}
    rows = []
    for field in sorted(fields):
        allowed_values = enums.get(field)
        allowed_display = ", ".join(f"`{value}`" for value in allowed_values) if allowed_values else "—"
        note = notes_overrides.get(field, FIELD_NOTES.get(field, ""))
        type_label = "enum" if allowed_values is not None else FIELD_TYPE_OVERRIDES.get(field, "text")
        rows.append((f"`{field}`", type_label, allowed_display, "yes" if field in required else "no", note))
    return markdown_table(("Field", "Type", "Allowed values", "Required", "Note"), rows)


def render_contract_markdown():
    """Assemble data/operations/contract.md from the same allowlists/enums
    the validate_*_args() functions enforce (docs/agent-write-path-plan-2026-09-07.md, Э2)."""
    parts = [
        "# Operation field contract\n",
        "> Generated from `scripts/agent_operations.py` and `scripts/jobs.py` by "
        "`python3 scripts/agent_operations.py render-contract`. Do not edit manually.\n",
        "This is the single source of truth for which connector command accepts which "
        "field. It is assembled from the same allowlists the runner enforces, so it "
        "cannot drift silently from actual validation. See "
        "[`README.md`](README.md) for the full request/result contract.\n",
        "## `add`\n",
        contract_table(ADD_ALLOWED_ARGS, ADD_REQUIRED_ARGS, ADD_FIELD_ENUMS),
        "## `add` with `duplicate_of`\n",
        "A duplicate add only attaches a new source reference to an existing job; any "
        "canonical field beside the ones below is rejected (`duplicate_add_extra_fields`).\n",
        contract_table(ADD_DUPLICATE_ARGS, ADD_REQUIRED_ARGS, ADD_FIELD_ENUMS),
        "## `verify`\n",
        contract_table(VERIFY_ALLOWED_ARGS, VERIFY_REQUIRED_ARGS, VERIFY_FIELD_ENUMS),
        "## `screen`\n",
        contract_table(SCREEN_ALLOWED_ARGS, SCREEN_REQUIRED_ARGS, SCREEN_FIELD_ENUMS),
        "## `set`\n",
        "At least one field is required.\n",
        contract_table(
            SET_ALLOWED_ARGS,
            set(),
            SET_FIELD_ENUMS,
            notes_overrides={"listing_status": "allowed only after a human application already exists"},
        ),
        "## `status`\n",
        contract_table(STATUS_ALLOWED_ARGS, STATUS_REQUIRED_ARGS, STATUS_FIELD_ENUMS),
        "## Batch child: `add` (with `client_ref`)\n",
        "Same `args` as `add` above, addressed by `client_ref` instead of `job_id`/`expected`.\n",
        contract_table(
            {"client_ref"} | ADD_ALLOWED_ARGS, {"client_ref"} | ADD_REQUIRED_ARGS, ADD_FIELD_ENUMS
        ),
        "## Batch child: existing job (`screen` / `verify` / `set` / `status`)\n",
        "Every non-`add` batch child carries `job_id` and a non-empty `expected` "
        "optimistic lock in addition to its command-specific `args` (see the matching "
        "section above).\n",
        contract_table({"job_id", "expected"}, {"job_id", "expected"}, {}),
        "## Fields no command accepts\n",
        "Written only by the runner, never by a connector command: "
        + ", ".join(f"`{field}`" for field in fields_no_command_accepts())
        + ".\n",
        "## Invariants across fields\n",
        "\n".join(f"- {line}" for line in CONTRACT_INVARIANTS) + "\n",
        "## Canonical enum values (reference)\n",
        markdown_table(
            ("Field", "Values"),
            [
                (f"`{field}`", ", ".join(f"`{value}`" for value in values))
                for field, values in jobs.ENUMS.items()
            ],
        ),
    ]
    return "\n\n".join(part.rstrip("\n") for part in parts) + "\n"


def write_or_check_contract(markdown, check):
    """Write contract.md, or (check=True) report whether it is already current."""
    expected = markdown.encode("utf-8")
    if check:
        return CONTRACT_PATH.exists() and CONTRACT_PATH.read_bytes() == expected
    CONTRACT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with CONTRACT_PATH.open("wb") as file:
        file.write(expected)
    return True


def main():
    """CLI: `apply`/`validate` a request, or `render-contract` (optionally `--check`)."""
    parser = argparse.ArgumentParser(description="Execute declarative Phase A/B agent operations")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("request", type=Path)
    validate.add_argument("--format", choices=("text", "json"), default="text")
    apply = subparsers.add_parser("apply")
    apply.add_argument("request", type=Path)
    apply.add_argument("--format", choices=("text", "json"), default="text")
    render_contract = subparsers.add_parser(
        "render-contract", help="regenerate data/operations/contract.md from the code-level allowlists"
    )
    render_contract.add_argument("--check", action="store_true", help="check freshness without writing")
    render_contract.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()
    if args.command == "render-contract":
        up_to_date = write_or_check_contract(render_contract_markdown(), args.check)
        payload = {
            "ok": up_to_date if args.check else True,
            "command": "render-contract",
            "path": CONTRACT_PATH.relative_to(ROOT).as_posix(),
            "up_to_date": up_to_date,
        }
        if args.format == "json":
            print_json(payload)
        elif not args.check:
            print("data/operations/contract.md rendered")
        elif up_to_date:
            print("data/operations/contract.md is up to date")
        else:
            print(
                "data/operations/contract.md is out of date; run: python3 scripts/agent_operations.py render-contract",
                file=sys.stderr,
            )
        if args.check and not up_to_date:
            raise SystemExit(1)
        return
    try:
        if args.command == "validate":
            operation = load_operation(args.request)
            payload = {"ok": True, "command": "validate", "operation": operation}
        else:
            result, result_path_value = execute(args.request)
            payload = {
                "ok": result["status"] != "rejected",
                "command": "apply",
                "operation_id": result["operation_id"],
                "status": result["status"],
                "risk": result["risk"],
                "result_path": result_path_value.relative_to(ROOT).as_posix(),
                "result": result,
            }
    except (OperationError, jobs.ValidationError) as error:
        die(str(error))
    if args.format == "json":
        print_json(payload)
    elif args.command == "validate":
        print(f"valid operation: {payload['operation']['operation_id']}")
    else:
        print(f"{payload['operation_id']}  {payload['status']}  risk={payload['risk']}")
    if args.command == "apply" and not payload["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
