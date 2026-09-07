#!/usr/bin/env python3
import argparse, json, math, re, shutil, sys, tempfile
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
OPERATION_ID_RE = re.compile(r"[a-z0-9][a-z0-9._-]{2,79}\Z")
JOB_ID_RE = re.compile(r"job-\d{4,}\Z")
SINGLE_TOP_LEVEL_FIELDS = {"version","operation_id","command","job_id","expected","args"}
ADD_TOP_LEVEL_FIELDS = {"version","operation_id","command","args"}
BATCH_TOP_LEVEL_FIELDS = {"version","operation_id","command","atomic","operations"}
JOB_CHILD_FIELDS = {"command","job_id","expected","args"}
ADD_CHILD_FIELDS = {"command","client_ref","args"}
VERIFY_REQUIRED_ARGS = {"listing_status","first_party_verified","apply_verified"}
VERIFY_ALLOWED_ARGS = VERIFY_REQUIRED_ARGS | {"original_url","decision_reason","notes","level","remote_policy","stack","salary","match_score","application_status","next_action","next_action_date"}
SET_ALLOWED_ARGS = {"next_action","next_action_date","listing_status"}
SCREEN_REQUIRED_ARGS = {"decision_reason"}
SCREEN_ALLOWED_ARGS = SCREEN_REQUIRED_ARGS | {"notes"}
STATUS_REQUIRED_ARGS = {"application_status","confirmed_by_user"}
STATUS_ALLOWED_ARGS = STATUS_REQUIRED_ARGS | {
    "stage","applied_at","response_at","decision_reason","next_action",
    "next_action_date","cv_version","notes",
}
VERIFY_ENRICHMENT_ARGS = {"level","remote_policy","stack","salary","match_score"}
VERIFY_WORKFLOW_ARGS = {"application_status","next_action","next_action_date"}
ADD_CONTROL_ARGS = {"duplicate_of","force"}
ADD_ALLOWED_ARGS = set(jobs.ADD_INPUT_FIELDS) | ADD_CONTROL_ARGS
ADD_REQUIRED_ARGS = set(jobs.ADD_REQUIRED_INPUT_FIELDS)
ADD_APPLICATION_STATUSES = {"not_started","reviewing"}
ADD_DUPLICATE_ARGS = ADD_REQUIRED_ARGS | {
    "source_url","source_job_id","found_at","duplicate_of","force",
}
ADD_UNKNOWN_ARG_HINTS = {
    "next_action": "create the job first, then send a separate set operation with next_action",
    "next_action_date": "create the job first, then send a separate set operation with next_action_date",
    "verified_at": "verified_at is computed by the runner from verify; do not send it directly",
}
# Closed taxonomy for rejected-result error.code (see docs/agent-write-path-plan-2026-09-07.md, Э1).
ERROR_CODES = frozenset({
    "invalid_json","request_too_large","filename_mismatch","unsupported_command",
    "unknown_top_level_fields","missing_top_level_fields","unknown_args","missing_args",
    "bad_type","bad_enum_value","bad_format","duplicate_add_extra_fields",
    "invariant_violation","unknown_job","result_exists","batch_not_atomic",
})
class OperationError(ValueError):
    def __init__(self,message,*,code="contract_violation",field=None,allowed=None,hint=None,layer="operations"):
        super().__init__(message); self.code=code; self.field=field; self.allowed=allowed; self.hint=hint; self.layer=layer
    def to_payload(self):
        payload={"code":self.code,"layer":self.layer,"message":str(self)}
        if self.field is not None: payload["field"]=self.field
        if self.allowed is not None: payload["allowed"]=self.allowed
        if self.hint is not None: payload["hint"]=self.hint
        return payload
def contract_error(message,*,code,field=None,allowed=None,hint=None,layer="operations"):
    if code not in ERROR_CODES: raise ValueError(f"unknown OperationError code: {code!r}")
    return OperationError(message,code=code,field=field,allowed=allowed,hint=hint,layer=layer)
class BatchConflict(OperationError):
    def __init__(self, details):
        super().__init__(details.get("reason", "batch_child_conflict")); self.details=details
def die(message):
    print(f"error: {message}", file=sys.stderr); raise SystemExit(1)
def print_json(value): print(json.dumps(value, ensure_ascii=False, sort_keys=True))
def utc_now(): return utc_timestamp()
def clean_text(value, field):
    if not isinstance(value,str): raise OperationError(f"{field} must be a string")
    if "\n" in value or "\r" in value: raise OperationError(f"{field} must not contain a newline")
    return value
def resolve_request_path(value):
    path=Path(value)
    if not path.is_absolute(): path=ROOT/path
    try:
        resolved=path.resolve(strict=True); relative=resolved.relative_to(REQUESTS_DIR.resolve())
    except (OSError,ValueError) as error: raise OperationError("request must be an existing file inside data/operations/requests") from error
    if relative.parent!=Path(".") or resolved.suffix!=".json": raise OperationError("request must be a direct .json file in data/operations/requests")
    return resolved
def result_path(operation_id): return RESULTS_DIR/f"{operation_id}.json"
def validate_expected(expected,prefix="expected"):
    if not isinstance(expected,dict) or not expected: raise OperationError(f"{prefix} must be a non-empty object")
    unknown=sorted(set(expected)-(set(jobs.FIELDS)-{"id"}))
    if unknown: raise OperationError(f"{prefix} contains unknown or protected fields: "+", ".join(unknown))
    return {k:clean_text(v,f"{prefix}.{k}") for k,v in expected.items()}
def validate_verify_args(args,prefix="args"):
    if not isinstance(args,dict): raise OperationError(f"{prefix} must be an object")
    unknown=sorted(set(args)-VERIFY_ALLOWED_ARGS); missing=sorted(VERIFY_REQUIRED_ARGS-set(args))
    if unknown or missing:
        parts=[]
        if unknown: parts.append("unknown verify args: "+", ".join(unknown))
        if missing: parts.append("missing verify args: "+", ".join(missing))
        raise OperationError("; ".join(parts))
    out={}
    for k,v in args.items():
        if k=="match_score":
            if not isinstance(v,(str,int,float)) or isinstance(v,bool): raise OperationError(f"{prefix}.match_score must be a string or number")
            out[k]=str(v)
        else: out[k]=clean_text(v,f"{prefix}.{k}")
    if out["listing_status"] not in {"open","closed"}: raise contract_error(f"{prefix}.listing_status must be open or closed",code="bad_enum_value",field=f"{prefix}.listing_status",allowed=["open","closed"])
    for k in ("first_party_verified","apply_verified"):
        if out[k] not in {"yes","no"}: raise OperationError(f"{prefix}.{k} must be yes or no")
    if "decision_reason" in out and out["decision_reason"] not in jobs.PRE_APPLICATION_REASONS-{"duplicate_listing"}: raise OperationError(f"{prefix}.decision_reason is not allowed for verify")
    workflow=VERIFY_WORKFLOW_ARGS & set(out)
    if "decision_reason" in out and workflow: raise OperationError("workflow args cannot be combined with decision_reason")
    if "application_status" in out:
        if out["application_status"]!="apply": raise OperationError("verify may set application_status only to apply")
        if not out.get("next_action","").strip(): raise OperationError("application_status=apply requires a non-empty next_action")
        if not (out["listing_status"]=="open" and out["first_party_verified"]=="yes" and out["apply_verified"]=="yes"): raise OperationError("application_status=apply requires a passed open verification")
    elif workflow: raise OperationError("next_action and next_action_date require application_status=apply")
    if "next_action_date" in out:
        try: datetime.strptime(out["next_action_date"],"%Y-%m-%d")
        except ValueError as error: raise OperationError(f"{prefix}.next_action_date must be YYYY-MM-DD") from error
    if "level" in out and out["level"] not in jobs.LEVELS: raise OperationError(f"{prefix}.level is not a known level")
    if "remote_policy" in out and out["remote_policy"] not in jobs.REMOTE: raise OperationError(f"{prefix}.remote_policy is not a known remote policy")
    if "original_url" in out and out["original_url"] and not jobs.valid_http_url(out["original_url"]): raise OperationError(f"{prefix}.original_url must be an absolute http(s) URL")
    return out
def validate_set_args(args,prefix="args"):
    if not isinstance(args,dict) or not args: raise OperationError(f"{prefix} must be a non-empty object")
    unknown=sorted(set(args)-SET_ALLOWED_ARGS)
    if unknown: raise OperationError("unknown set args: "+", ".join(unknown))
    out={k:clean_text(v,f"{prefix}.{k}") for k,v in args.items()}
    if "next_action" in out and not out["next_action"].strip(): raise OperationError(f"{prefix}.next_action must not be empty")
    if "next_action_date" in out:
        try: datetime.strptime(out["next_action_date"],"%Y-%m-%d")
        except ValueError as error: raise OperationError(f"{prefix}.next_action_date must be YYYY-MM-DD") from error
    if "listing_status" in out and out["listing_status"]!="closed": raise OperationError("agent set may only record listing_status=closed")
    return out
def validate_screen_args(args,prefix="args"):
    if not isinstance(args,dict): raise OperationError(f"{prefix} must be an object")
    unknown=sorted(set(args)-SCREEN_ALLOWED_ARGS); missing=sorted(SCREEN_REQUIRED_ARGS-set(args))
    if unknown or missing:
        parts=[]
        if unknown: parts.append("unknown screen args: "+", ".join(unknown))
        if missing: parts.append("missing screen args: "+", ".join(missing))
        raise OperationError("; ".join(parts))
    out={k:clean_text(v,f"{prefix}.{k}") for k,v in args.items()}
    if out["decision_reason"] not in jobs.SCREEN_REASONS: raise OperationError(f"{prefix}.decision_reason is not allowed for screen")
    if out["decision_reason"]=="other" and not out.get("notes","").strip(): raise OperationError("screen decision_reason=other requires non-empty notes")
    return out
def validate_status_args(args,prefix="args"):
    if not isinstance(args,dict): raise contract_error(f"{prefix} must be an object",code="bad_type",field=prefix)
    unknown=sorted(set(args)-STATUS_ALLOWED_ARGS); missing=sorted(STATUS_REQUIRED_ARGS-set(args))
    if unknown: raise contract_error("unknown status args: "+", ".join(unknown),code="unknown_args",field=f"{prefix}.{unknown[0]}",allowed=sorted(STATUS_ALLOWED_ARGS))
    if missing: raise contract_error("missing status args: "+", ".join(missing),code="missing_args",field=f"{prefix}.{missing[0]}",allowed=sorted(STATUS_REQUIRED_ARGS))
    if args["confirmed_by_user"] is not True: raise contract_error(f"{prefix}.confirmed_by_user must be true",code="bad_type",field=f"{prefix}.confirmed_by_user",hint="set confirmed_by_user to true only after the human sends the operation")
    out={"confirmed_by_user":True}
    for k,v in args.items():
        if k=="confirmed_by_user": continue
        out[k]=clean_text(v,f"{prefix}.{k}")
    if out["application_status"] not in jobs.APPLICATION_STATUSES: raise contract_error(f"{prefix}.application_status is not a known status",code="bad_enum_value",field=f"{prefix}.application_status",allowed=sorted(jobs.APPLICATION_STATUSES))
    if "stage" in out and out["stage"] not in jobs.STAGES: raise contract_error(f"{prefix}.stage is not a known stage",code="bad_enum_value",field=f"{prefix}.stage",allowed=sorted(jobs.STAGES))
    if "decision_reason" in out and out["decision_reason"] not in {"no_response_timeout","withdrawn_by_me"}: raise contract_error(f"{prefix}.decision_reason is not allowed for status",code="bad_enum_value",field=f"{prefix}.decision_reason",allowed=["no_response_timeout","withdrawn_by_me"])
    for k in ("applied_at","response_at","next_action_date"):
        if k in out and out[k]:
            try: datetime.strptime(out[k],"%Y-%m-%d")
            except ValueError as error: raise contract_error(f"{prefix}.{k} must be YYYY-MM-DD",code="bad_format",field=f"{prefix}.{k}",hint="use YYYY-MM-DD") from error
    return out
def validate_add_args(args,prefix="args"):
    if not isinstance(args,dict): raise contract_error(f"{prefix} must be an object",code="bad_type",field=prefix)
    unknown=sorted(set(args)-ADD_ALLOWED_ARGS); missing=sorted(ADD_REQUIRED_ARGS-set(args))
    if unknown:
        first=unknown[0]
        raise contract_error("unknown add args: "+", ".join(unknown),code="unknown_args",field=f"{prefix}.{first}",allowed=sorted(ADD_ALLOWED_ARGS),hint=ADD_UNKNOWN_ARG_HINTS.get(first))
    if missing: raise contract_error("missing add args: "+", ".join(missing),code="missing_args",field=f"{prefix}.{missing[0]}",allowed=sorted(ADD_REQUIRED_ARGS))
    out={}
    for k,v in args.items():
        if k=="force":
            if not isinstance(v,bool): raise contract_error(f"{prefix}.force must be a boolean",code="bad_type",field=f"{prefix}.force")
            out[k]=v
        elif k=="match_score":
            if not isinstance(v,(str,int,float)) or isinstance(v,bool): raise contract_error(f"{prefix}.match_score must be a string or number",code="bad_type",field=f"{prefix}.match_score")
            out[k]=str(v)
        else: out[k]=clean_text(v,f"{prefix}.{k}")
    for k in ADD_REQUIRED_ARGS:
        if not out[k].strip(): raise contract_error(f"{prefix}.{k} must not be empty",code="bad_format",field=f"{prefix}.{k}")
    if out["source"] not in jobs.SOURCES: raise contract_error(f"{prefix}.source is not a known source",code="bad_enum_value",field=f"{prefix}.source",allowed=sorted(jobs.SOURCES))
    if out.get("application_status","not_started") not in ADD_APPLICATION_STATUSES: raise contract_error("add may set application_status only to not_started or reviewing",code="bad_enum_value",field=f"{prefix}.application_status",allowed=sorted(ADD_APPLICATION_STATUSES))
    for k,allowed in (
        ("listing_status",jobs.LISTING_STATUSES),
        ("first_party_verified",jobs.VERIFICATION),
        ("apply_verified",jobs.VERIFICATION),
        ("level",jobs.LEVELS),
        ("remote_policy",jobs.REMOTE),
    ):
        if k in out and out[k] not in allowed: raise contract_error(f"{prefix}.{k} is not a known value",code="bad_enum_value",field=f"{prefix}.{k}",allowed=sorted(allowed))
    for k in ("original_url","source_url"):
        if out.get(k) and not jobs.valid_http_url(out[k]): raise contract_error(f"{prefix}.{k} must be an absolute http(s) URL",code="bad_format",field=f"{prefix}.{k}")
    for k in ("posted_at","found_at"):
        if out.get(k):
            try: datetime.strptime(out[k],"%Y-%m-%d")
            except ValueError as error: raise contract_error(f"{prefix}.{k} must be YYYY-MM-DD",code="bad_format",field=f"{prefix}.{k}",hint="use YYYY-MM-DD") from error
    if out.get("match_score",""):
        try: score=float(out["match_score"])
        except ValueError as error: raise contract_error(f"{prefix}.match_score must be a number from 1 to 10",code="bad_format",field=f"{prefix}.match_score") from error
        if not math.isfinite(score) or not 1<=score<=10: raise contract_error(f"{prefix}.match_score must be a number from 1 to 10",code="bad_format",field=f"{prefix}.match_score")
    reason=out.get("decision_reason","")
    allowed_reasons=jobs.PRE_APPLICATION_REASONS-{"duplicate_listing"}
    if reason and reason not in allowed_reasons: raise contract_error(f"{prefix}.decision_reason is not allowed for add",code="bad_enum_value",field=f"{prefix}.decision_reason",allowed=sorted(allowed_reasons))
    if reason=="other" and not out.get("notes","").strip(): raise contract_error("add decision_reason=other requires non-empty notes",code="invariant_violation",field=f"{prefix}.notes")
    status=out.get("application_status","not_started")
    if reason and status!="not_started": raise contract_error("add decision_reason requires application_status=not_started",code="invariant_violation",field=f"{prefix}.decision_reason")
    listing=out.get("listing_status","unknown")
    if reason=="closed_before_application" and listing!="closed": raise contract_error("closed_before_application requires listing_status=closed",code="invariant_violation",field=f"{prefix}.listing_status")
    if listing=="closed" and status=="not_started" and reason!="closed_before_application": raise contract_error("listing_status=closed before application requires decision_reason=closed_before_application",code="invariant_violation",field=f"{prefix}.decision_reason")
    first_party=out.get("first_party_verified","unknown")
    apply_verified=out.get("apply_verified","unknown")
    if first_party=="yes" and not out.get("original_url",""): raise contract_error("first_party_verified=yes requires original_url",code="invariant_violation",field=f"{prefix}.original_url")
    if apply_verified=="yes" and first_party!="yes": raise contract_error("apply_verified=yes requires first_party_verified=yes",code="invariant_violation",field=f"{prefix}.apply_verified")
    if out["source"] not in jobs.SOURCES_WITHOUT_EXTERNAL_REFERENCE and not (out.get("source_url","").strip() or out.get("source_job_id","").strip()): raise contract_error("external add requires source_url or source_job_id",code="invariant_violation",field=f"{prefix}.source_url")
    duplicate_of=out.get("duplicate_of","")
    if "duplicate_of" in out and not duplicate_of: raise contract_error(f"{prefix}.duplicate_of must not be empty",code="bad_format",field=f"{prefix}.duplicate_of")
    if duplicate_of:
        if not JOB_ID_RE.fullmatch(duplicate_of): raise contract_error(f"{prefix}.duplicate_of must be job-NNNN",code="bad_format",field=f"{prefix}.duplicate_of",hint="use job-NNNN")
        ignored=sorted(set(out)-ADD_DUPLICATE_ARGS)
        if ignored: raise contract_error("duplicate add contains canonical fields that would be ignored: "+", ".join(ignored),code="duplicate_add_extra_fields",field=f"{prefix}.{ignored[0]}",allowed=sorted(ADD_DUPLICATE_ARGS),hint="a duplicate add only takes source_url/source_job_id (plus force); canonical fields belong to the original job")
        if not (out.get("source_url","").strip() or out.get("source_job_id","").strip()): raise contract_error("duplicate add requires source_url or source_job_id",code="invariant_violation",field=f"{prefix}.source_url")
    return out
def require_field_set(value,allowed,required,prefix):
    unknown=sorted(set(value)-allowed); missing=sorted(required-set(value))
    if unknown: raise contract_error(f"{prefix}: unknown fields: "+", ".join(unknown),code="unknown_top_level_fields",field=f"{prefix}.{unknown[0]}",allowed=sorted(allowed))
    if missing: raise contract_error(f"{prefix}: missing fields: "+", ".join(missing),code="missing_top_level_fields",field=f"{prefix}.{missing[0]}",allowed=sorted(required))
def validate_child(value,index=None):
    prefix=f"operations[{index}]" if index is not None else "operation"
    if not isinstance(value,dict): raise contract_error(f"{prefix} must be an object",code="bad_type",field=prefix)
    command=clean_text(value.get("command"),f"{prefix}.command") if "command" in value else None
    if command=="add":
        require_field_set(value,ADD_CHILD_FIELDS,ADD_CHILD_FIELDS,prefix)
        client_ref=clean_text(value["client_ref"],f"{prefix}.client_ref").strip()
        if not client_ref: raise contract_error(f"{prefix}.client_ref must not be empty",code="bad_format",field=f"{prefix}.client_ref")
        if len(client_ref)>200: raise contract_error(f"{prefix}.client_ref must not exceed 200 characters",code="bad_format",field=f"{prefix}.client_ref")
        return {"command":"add","client_ref":client_ref,"args":validate_add_args(value["args"],f"{prefix}.args")}
    require_field_set(value,JOB_CHILD_FIELDS,JOB_CHILD_FIELDS,prefix)
    if command not in {"screen","verify","set","status"}: raise contract_error(f"{prefix}.command must be screen, verify, set or status",code="unsupported_command",field=f"{prefix}.command",allowed=["screen","verify","set","status"])
    job_id=clean_text(value["job_id"],f"{prefix}.job_id")
    if not JOB_ID_RE.fullmatch(job_id): raise contract_error(f"{prefix}.job_id must be job-NNNN",code="bad_format",field=f"{prefix}.job_id",hint="use job-NNNN")
    expected=validate_expected(value["expected"],f"{prefix}.expected")
    if command=="verify": args=validate_verify_args(value["args"],f"{prefix}.args")
    elif command=="screen": args=validate_screen_args(value["args"],f"{prefix}.args")
    elif command=="status": args=validate_status_args(value["args"],f"{prefix}.args")
    else: args=validate_set_args(value["args"],f"{prefix}.args")
    return {"command":command,"job_id":job_id,"expected":expected,"args":args}
def validate_operation(value):
    if not isinstance(value,dict): raise contract_error("request must be a JSON object",code="bad_type",field="request")
    if value.get("version")!=OPERATION_VERSION: raise contract_error(f"version must be {OPERATION_VERSION}",code="bad_enum_value",field="version",allowed=[OPERATION_VERSION])
    operation_id=clean_text(value.get("operation_id"),"operation_id") if "operation_id" in value else None
    if operation_id is None or not OPERATION_ID_RE.fullmatch(operation_id): raise contract_error("operation_id must use lowercase letters, digits, '.', '_' or '-'",code="bad_format",field="operation_id")
    command=clean_text(value.get("command"),"command") if "command" in value else None
    if command=="add":
        require_field_set(value,ADD_TOP_LEVEL_FIELDS,ADD_TOP_LEVEL_FIELDS,"operation")
        return {"version":OPERATION_VERSION,"operation_id":operation_id,"command":"add","args":validate_add_args(value["args"])}
    if command=="batch":
        require_field_set(value,BATCH_TOP_LEVEL_FIELDS,BATCH_TOP_LEVEL_FIELDS,"operation")
        if value["atomic"] is not True: raise contract_error("batch.atomic must be true",code="batch_not_atomic",field="atomic",allowed=[True],hint="partial (atomic=false) batches are not supported yet")
        entries=value["operations"]
        if not isinstance(entries,list) or not entries: raise contract_error("batch.operations must be a non-empty array",code="bad_type",field="operations")
        if len(entries)>MAX_BATCH_OPERATIONS: raise contract_error(f"batch.operations exceeds {MAX_BATCH_OPERATIONS} entries",code="bad_format",field="operations",hint=f"split into batches of at most {MAX_BATCH_OPERATIONS}")
        operations=[validate_child(entry,i) for i,entry in enumerate(entries)]
        ids=[x["job_id"] for x in operations if x["command"]!="add"]
        if len(ids)!=len(set(ids)): raise contract_error("batch may contain each job_id only once",code="invariant_violation",field="operations")
        client_refs=[x["client_ref"] for x in operations if x["command"]=="add"]
        if len(client_refs)!=len(set(client_refs)): raise contract_error("batch may contain each add client_ref only once",code="invariant_violation",field="operations")
        return {"version":OPERATION_VERSION,"operation_id":operation_id,"command":"batch","atomic":True,"operations":operations}
    require_field_set(value,SINGLE_TOP_LEVEL_FIELDS,SINGLE_TOP_LEVEL_FIELDS,"operation")
    if command not in {"screen","verify","set","status"}: raise contract_error("command must be add, screen, verify, set, status, or batch",code="unsupported_command",field="command",allowed=["add","screen","verify","set","status","batch"])
    child=validate_child({"command":command,"job_id":value["job_id"],"expected":value["expected"],"args":value["args"]})
    return {"version":OPERATION_VERSION,"operation_id":operation_id,**child}
def load_operation(path):
    path=resolve_request_path(path)
    try: raw=path.read_bytes()
    except OSError as error: raise OperationError(f"cannot read request: {error}") from error
    if len(raw)>MAX_REQUEST_BYTES: raise contract_error(f"request exceeds {MAX_REQUEST_BYTES} bytes",code="request_too_large",hint=f"keep the request under {MAX_REQUEST_BYTES} bytes")
    try: value=json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError,json.JSONDecodeError) as error: raise contract_error(f"request is not valid UTF-8 JSON: {error}",code="invalid_json") from error
    operation=validate_operation(value)
    if path.name!=f"{operation['operation_id']}.json": raise contract_error("request filename must equal operation_id + '.json'",code="filename_mismatch",field="operation_id",hint="name the file <operation_id>.json")
    return operation
def read_job(job_id):
    for row in jobs.load():
        if row["id"]==job_id: return row
    raise contract_error(f"job {job_id} was not found",code="unknown_job",field="job_id")
def precondition_mismatches(row,expected):
    return {k:{"expected":v,"actual":row.get(k,"")} for k,v in expected.items() if row.get(k,"")!=v}
def classify_child_risk(operation,row):
    if operation["command"]=="add": return "medium"
    if operation["command"]=="status": return "medium"
    if operation["command"] in {"screen","set"}: return "low"
    args=operation["args"]
    passed=args["listing_status"]=="open" and args["first_party_verified"]=="yes" and args["apply_verified"]=="yes"
    if (VERIFY_ENRICHMENT_ARGS|VERIFY_WORKFLOW_ARGS)&set(args): return "medium"
    if passed and row["application_status"]=="not_started": return "medium"
    return "low"
def classify_risk(operation,rows_by_id=None):
    if operation["command"]=="add": return "medium"
    if operation["command"]!="batch":
        row=rows_by_id[operation["job_id"]] if rows_by_id is not None else read_job(operation["job_id"])
        return classify_child_risk(operation,row)
    rows_by_id=rows_by_id or {row["id"]:row for row in jobs.load()}
    return "medium" if any(classify_child_risk(child,rows_by_id.get(child.get("job_id")))=="medium" for child in operation["operations"]) else "low"
def apply_operation(operation,row):
    if operation["command"]=="verify":
        result=jobs.verify_job(operation["job_id"],**operation["args"])
        return {"job":result["job"],"warnings":result["warnings"],"outcome":result["outcome"],"application_path":result.get("application_path")}
    if operation["command"]=="screen":
        result=jobs.screen_job(operation["job_id"],**operation["args"])
        return {"job":result["job"],"warnings":result["warnings"],"outcome":result["outcome"],"application_path":None}
    if operation["command"]=="status":
        args=dict(operation["args"]); args.pop("confirmed_by_user")
        result=jobs.status_job(operation["job_id"],**args)
        return {"job":result["job"],"warnings":result["warnings"],"outcome":result["outcome"],"application_path":result.get("application_path")}
    if "listing_status" in operation["args"] and row["application_status"] not in jobs.NEEDS_APPLIED_AT: raise contract_error("listing_status=closed through set is allowed only after an application exists",code="invariant_violation",field="args.listing_status")
    result=jobs.set_job(operation["job_id"],list(operation["args"].items()))
    return {"job":result["job"],"warnings":result["warnings"],"outcome":"updated","application_path":None}
def operation_result(operation,*,status,risk,details,job_id=None):
    result={"version":OPERATION_VERSION,"operation_id":operation["operation_id"],"status":status,"executed_at":utc_now(),"risk":risk,"command":operation["command"],"result":details}
    if operation["command"]=="add":
        if job_id: result["job_id"]=job_id
    elif operation["command"]=="batch": result["jobs"]=[child["job_id"] for child in operation["operations"] if child["command"]!="add"]
    else: result["job_id"]=operation["job_id"]
    return result
def write_result(result):
    path=result_path(result["operation_id"])
    if path.exists(): raise contract_error(f"operation_id already has a result: {path.relative_to(ROOT)}",code="result_exists",field="operation_id",hint="retry with a new operation_id; results are immutable")
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        with path.open("x",encoding="utf-8",newline="\n") as file:
            json.dump(result,file,ensure_ascii=False,indent=2,sort_keys=True); file.write("\n")
    except OSError as error: raise OperationError(f"cannot write operation result: {error}") from error
    return path
@contextmanager
def temporary_tracker_workspace():
    original={"ROOT":jobs.ROOT,"CSV_PATH":jobs.CSV_PATH,"JOB_SOURCES_PATH":jobs.JOB_SOURCES_PATH,"APPS_DIR":jobs.APPS_DIR,"TEMPLATE_PATH":jobs.TEMPLATE_PATH}
    with tempfile.TemporaryDirectory(prefix="agent-batch-") as directory:
        temp_root=Path(directory); temp_data=temp_root/"data"; temp_apps=temp_root/"applications"; temp_data.mkdir(parents=True)
        shutil.copy2(original["CSV_PATH"],temp_data/"jobs.csv"); shutil.copy2(original["JOB_SOURCES_PATH"],temp_data/"job_sources.csv"); shutil.copytree(original["APPS_DIR"],temp_apps)
        try:
            jobs.ROOT=temp_root; jobs.CSV_PATH=temp_data/"jobs.csv"; jobs.JOB_SOURCES_PATH=temp_data/"job_sources.csv"; jobs.APPS_DIR=temp_apps; jobs.TEMPLATE_PATH=temp_apps/"_TEMPLATE.md"
            yield temp_root
        finally:
            for key,value in original.items(): setattr(jobs,key,value)
def changed_application_writes(temp_root):
    writes=[]
    for temp_path in sorted((temp_root/"applications").glob("job-*.md")):
        relative=temp_path.relative_to(temp_root); target=ROOT/relative; body=temp_path.read_text(encoding="utf-8")
        if not target.exists() or target.read_text(encoding="utf-8")!=body: writes.append((target,body))
    return writes
def batch_preconditions(operation,rows_by_id):
    conflicts=[]
    for child in operation["operations"]:
        if child["command"]=="add": continue
        row=rows_by_id.get(child["job_id"])
        if row is None: raise contract_error(f"job {child['job_id']} was not found",code="unknown_job",field="job_id")
        mismatches=precondition_mismatches(row,child["expected"])
        if mismatches: conflicts.append({"job_id":child["job_id"],"command":child["command"],"mismatches":mismatches})
    return conflicts
def add_conflict_details(error):
    if isinstance(error,jobs.UnresolvedDuplicate):
        candidates=[{"id":row["id"],"company":row["company"],"role":row["role"],"application_status":row["application_status"],"listing_status":row["listing_status"],"reason":reason} for row,reason in error.candidates.values()]
        return {"reason":"unresolved_duplicate","candidates":candidates}
    return {"reason":"source_reference_conflict","message":error.message,"existing":error.existing}
def apply_add(operation):
    args=dict(operation["args"]); force=args.pop("force",False); duplicate_of=args.pop("duplicate_of",None)
    if duplicate_of and not any(row["id"]==duplicate_of for row in jobs.load()): raise contract_error(f"job {duplicate_of} was not found",code="unknown_job",field="args.duplicate_of")
    applied=jobs.add_job(args,force=force,duplicate_of=duplicate_of,no_file=False)
    updated=applied["job"]
    return updated,{"outcome":"source_reference_added" if applied.get("duplicate_of") else "job_added","job_id":updated["id"],"application_status":updated["application_status"],"listing_status":updated["listing_status"],"application_path":applied.get("application_path"),"source_reference":applied.get("source_reference"),"warnings":applied["warnings"]}
def execute_batch(operation):
    child_results=[]
    with temporary_tracker_workspace() as temp_root:
        for index,child in enumerate(operation["operations"]):
            if child["command"]=="add":
                try: updated,details=apply_add(child)
                except (jobs.UnresolvedDuplicate,jobs.SourceReferenceConflict) as error:
                    raise BatchConflict({"reason":"batch_child_conflict","index":index,"command":"add","client_ref":child["client_ref"],"conflict":add_conflict_details(error)}) from error
                child_results.append({"client_ref":child["client_ref"],"command":"add",**details})
                continue
            current=read_job(child["job_id"]); applied=apply_operation(child,current); updated=applied["job"]
            child_results.append({"job_id":child["job_id"],"command":child["command"],"outcome":applied["outcome"],"application_status":updated["application_status"],"listing_status":updated["listing_status"],"stage_reached":updated["stage_reached"],"warnings":applied["warnings"]})
        temp_rows=[dict(row) for row in jobs.load()]; temp_sources=[dict(row) for row in jobs.load_job_sources()]
        errors,warnings=jobs.validate_dataset(temp_rows,temp_sources)
        if errors: raise contract_error("batch dataset validation failed: "+"; ".join(errors),code="invariant_violation",layer="jobs")
        app_writes=changed_application_writes(temp_root)
    jobs.apply_dataset_transaction(temp_rows,temp_sources,app_writes)
    return child_results,warnings
def _execute_operation(operation):
    if operation["command"]=="add":
        risk="medium"
        try: updated,details=apply_add(operation)
        except jobs.UnresolvedDuplicate as error:
            result=operation_result(operation,status="conflict",risk=risk,details=add_conflict_details(error))
            return result,write_result(result)
        except jobs.SourceReferenceConflict as error:
            result=operation_result(operation,status="conflict",risk=risk,details=add_conflict_details(error))
            return result,write_result(result)
        errors,validation_warnings=jobs.validate_dataset(jobs.load(),jobs.load_job_sources())
        if errors: raise contract_error("post-operation dataset validation failed: "+"; ".join(errors),code="invariant_violation",layer="jobs")
        details["warnings"]=[*details["warnings"],*validation_warnings]
        result=operation_result(operation,status="completed",risk=risk,details=details,job_id=updated["id"])
        return result,write_result(result)
    if operation["command"]=="batch":
        rows_by_id={row["id"]:row for row in jobs.load()}; conflicts=batch_preconditions(operation,rows_by_id); risk=classify_risk(operation,rows_by_id)
        if conflicts:
            result=operation_result(operation,status="conflict",risk=risk,details={"reason":"stale_operation","conflicts":conflicts})
            return result,write_result(result)
        try: children,warnings=execute_batch(operation)
        except BatchConflict as error:
            result=operation_result(operation,status="conflict",risk=risk,details=error.details)
            return result,write_result(result)
        result=operation_result(operation,status="completed",risk=risk,details={"outcome":"atomic_batch_applied","count":len(children),"operations":children,"warnings":warnings})
        return result,write_result(result)
    row=read_job(operation["job_id"]); risk=classify_risk(operation,{row["id"]:row}); mismatches=precondition_mismatches(row,operation["expected"])
    if mismatches:
        result=operation_result(operation,status="conflict",risk=risk,details={"reason":"stale_operation","mismatches":mismatches})
        return result,write_result(result)
    applied=apply_operation(operation,row); updated=applied["job"]; errors,validation_warnings=jobs.validate_dataset(jobs.load(),jobs.load_job_sources())
    if errors: raise contract_error("post-operation dataset validation failed: "+"; ".join(errors),code="invariant_violation",layer="jobs")
    result=operation_result(operation,status="completed",risk=risk,details={"outcome":applied["outcome"],"application_status":updated["application_status"],"listing_status":updated["listing_status"],"stage_reached":updated["stage_reached"],"application_path":applied.get("application_path"),"warnings":[*applied["warnings"],*validation_warnings]})
    return result,write_result(result)
def derive_operation_id(path):
    stem=Path(path).stem
    return stem if OPERATION_ID_RE.fullmatch(stem) else None
def peek_command(path):
    """Best-effort top-level command for a rejected result, read independently
    of load_operation() so a bad args block still reports which command it was."""
    try:
        value=json.loads(Path(path).read_bytes().decode("utf-8"))
        command=value.get("command")
        return command if isinstance(command,str) else "unknown"
    except Exception: return "unknown"
def error_payload(error):
    if isinstance(error,OperationError): return error.to_payload()
    return {"code":"invariant_violation","layer":"jobs","message":str(error)}
def rejected_result(operation_id,command,error):
    return {"version":OPERATION_VERSION,"operation_id":operation_id,"status":"rejected","command":command,"executed_at":utc_now(),"risk":"none","error":error_payload(error)}
def execute(path):
    operation_id=derive_operation_id(path)
    if operation_id is not None and result_path(operation_id).exists():
        raise contract_error(f"operation_id already has a result: {result_path(operation_id).relative_to(ROOT)}",code="result_exists",field="operation_id",hint="retry with a new operation_id; results are immutable")
    command=peek_command(path)
    try:
        operation=load_operation(path)
        command=operation["command"]
        return _execute_operation(operation)
    except (OperationError,jobs.ValidationError) as error:
        if operation_id is None: raise
        result=rejected_result(operation_id,command,error)
        return result,write_result(result)
    except SystemExit as error:
        if operation_id is None: raise
        wrapped=OperationError(f"unexpected process exit while applying the operation: {error}",code="invariant_violation",layer="jobs")
        result=rejected_result(operation_id,command,wrapped)
        return result,write_result(result)
def main():
    parser=argparse.ArgumentParser(description="Execute declarative Phase A/B agent operations"); subparsers=parser.add_subparsers(dest="command",required=True)
    validate=subparsers.add_parser("validate"); validate.add_argument("request",type=Path); validate.add_argument("--format",choices=("text","json"),default="text")
    apply=subparsers.add_parser("apply"); apply.add_argument("request",type=Path); apply.add_argument("--format",choices=("text","json"),default="text")
    args=parser.parse_args()
    try:
        if args.command=="validate":
            operation=load_operation(args.request); payload={"ok":True,"command":"validate","operation":operation}
        else:
            result,result_path_value=execute(args.request)
            payload={"ok":result["status"]!="rejected","command":"apply","operation_id":result["operation_id"],"status":result["status"],"risk":result["risk"],"result_path":result_path_value.relative_to(ROOT).as_posix(),"result":result}
    except (OperationError,jobs.ValidationError) as error: die(str(error))
    if args.format=="json": print_json(payload)
    elif args.command=="validate": print(f"valid operation: {payload['operation']['operation_id']}")
    else: print(f"{payload['operation_id']}  {payload['status']}  risk={payload['risk']}")
    if args.command=="apply" and not payload["ok"]: raise SystemExit(1)
if __name__=="__main__": main()
