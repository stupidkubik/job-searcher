#!/usr/bin/env python3
"""CLI для data/jobs.csv. Использует только стандартную библиотеку Python."""

import argparse
import csv
import json
import math
import os
import re
import sys
import tempfile
import unicodedata
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from difflib import SequenceMatcher
from io import StringIO
from pathlib import Path
from urllib.parse import parse_qsl, quote, urlencode, urlsplit, urlunsplit

try:  # Direct CLI execution places scripts/ on sys.path.
    from tracker_time import business_date
except ModuleNotFoundError:  # Unit tests may import this module as scripts.jobs.
    from scripts.tracker_time import business_date


ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "jobs.csv"
JOB_SOURCES_PATH = ROOT / "data" / "job_sources.csv"
APPS_DIR = ROOT / "applications"
TEMPLATE_PATH = APPS_DIR / "_TEMPLATE.md"
TRACKER_PATH = ROOT / "docs" / "tracker.md"
INDEX_DIR = ROOT / "data" / "index"
KNOWN_INDEX_PATH = INDEX_DIR / "known.tsv"
KEYS_INDEX_PATH = INDEX_DIR / "keys.tsv"
ACTIVE_INDEX_PATH = INDEX_DIR / "active.csv"

V1_FIELDS = [
    "id", "status", "company", "role", "level", "original_url", "source_url", "source",
    "location", "remote_policy", "stack", "salary", "posted_at", "found_at",
    "match_score", "stage_reached", "decision_reason", "applied_at",
    "response_at", "next_action", "next_action_date", "cv_version",
    "cover_letter", "contact_name", "contact_url", "last_update", "notes",
]
V1_LEGACY_FIELDS = [
    "id", "company", "role", "level", "original_url", "source_url", "source",
    "location", "remote_policy", "stack", "salary", "posted_at", "found_at",
    "match_score", "status", "stage_reached", "decision_reason", "applied_at",
    "response_at", "next_action", "next_action_date", "cv_version",
    "cover_letter", "contact_name", "contact_url", "last_update", "notes",
]
FIELDS = [
    "id", "application_status", "listing_status", "company", "role", "level",
    "original_url", "source_url", "source", "location", "remote_policy", "stack",
    "salary", "posted_at", "found_at", "match_score", "stage_reached",
    "decision_reason", "applied_at", "response_at", "next_action",
    "next_action_date", "cv_version", "cover_letter", "contact_name", "contact_url",
    "verified_at", "first_party_verified", "apply_verified", "last_update", "notes",
]
JOB_SOURCE_FIELDS = ["job_id", "source", "source_url", "source_job_id", "found_at"]
REQUIRED = [
    "id", "company", "role", "source", "found_at", "application_status",
    "listing_status", "stage_reached", "first_party_verified", "apply_verified",
    "last_update",
]
DATE_FIELDS = [
    "posted_at", "found_at", "applied_at", "response_at", "next_action_date",
    "verified_at", "last_update",
]
APPLICATION_STATUSES = [
    "not_started", "reviewing", "apply", "applied", "interviewing", "offer",
    "rejected", "ghosted", "withdrawn",
]
ADD_APPLICATION_STATUSES = ["not_started", "reviewing", "apply"]
ADD_INPUT_FIELDS = {
    "company", "role", "source", "application_status", "listing_status",
    "first_party_verified", "apply_verified", "level", "remote_policy",
    "original_url", "source_url", "location", "stack", "salary", "posted_at",
    "found_at", "match_score", "decision_reason", "notes", "source_job_id",
}
ADD_REQUIRED_INPUT_FIELDS = {"company", "role", "source"}
LISTING_STATUSES = ["open", "closed", "unknown"]
VERIFICATION = ["yes", "no", "unknown"]
STAGES = ["None", "Applied", "Recruiter screen", "Tech interview", "Test task", "Final interview", "Offer"]
LEVELS = ["Intern", "Graduate", "Junior", "Junior+", "Associate", "Junior/Middle", "Middle", "Senior", "Lead", "Unknown"]
REMOTE = ["Global", "Europe", "EMEA", "Serbia", "Country-specific", "Hybrid", "On-site", "Unclear"]
SOURCES = [
    "Hirify", "Jaabz", "LinkedIn", "Welcome to the Jungle", "We Work Remotely",
    "HiringCafe", "Hacker News — Who is Hiring?", "Hacker News — Who Wants to Be Hired?",
    "YC Work at a Startup", "Wellfound", "HelloWorld.rs", "Reactiflux Discord",
    "Find My Remote / Telegram", "Telegram", "Himalayas", "Startit Jobs", "Hired Valley",
    "Relocate.me", "Remote OK", "Geekjob", "TalentMove", "Company Careers",
    "Referral", "Manual", "Other",
]
SOURCES_ALLOWING_SHARED_DISCOVERY_URLS = {"Telegram"}
REASONS = [
    "geo_restriction", "work_authorization", "seniority_too_high", "seniority_too_low",
    "stack_mismatch", "role_not_frontend", "salary_too_low", "company_not_interesting",
    "closed_before_application", "already_applied", "duplicate_listing",
    "no_response_timeout", "withdrawn_by_me", "other",
]
NEEDS_APPLIED_AT = {"applied", "interviewing", "offer", "rejected", "ghosted", "withdrawn"}
RESPONDED_APPLICATION_STATUSES = {"interviewing", "offer", "rejected"}
PRE_APPLICATION_REASONS = set(REASONS) - {"no_response_timeout", "withdrawn_by_me"}
SCREEN_REASONS = PRE_APPLICATION_REASONS - {"closed_before_application", "duplicate_listing"}
SET_PROTECTED = {
    "id", "stage_reached", "verified_at", "last_update",
    "application_status", "applied_at", "response_at", "decision_reason",
}
VERIFY_ENRICHMENT_FIELDS = {"level", "remote_policy", "stack", "salary", "match_score"}
ENUMS = {
    "application_status": APPLICATION_STATUSES,
    "listing_status": LISTING_STATUSES,
    "first_party_verified": VERIFICATION,
    "apply_verified": VERIFICATION,
    "stage_reached": STAGES,
    "level": LEVELS,
    "remote_policy": REMOTE,
    "source": SOURCES,
    "decision_reason": REASONS,
}
GHOST_AFTER_DAYS = 30
SOURCES_WITHOUT_EXTERNAL_REFERENCE = {"Manual", "Referral"}
TERMINAL_APPLICATION_STATUSES = {"rejected", "ghosted", "withdrawn"}
PRE_APPLICATION_STATUSES = {"not_started", "reviewing", "apply"}
# Pre-application statuses that mean work is still in progress on our side.
# A decision reason or a closed listing terminates that work, so it belongs to
# `not_started` instead; keeping both would leave the row outside every view.
IN_PROGRESS_APPLICATION_STATUSES = {"reviewing", "apply"}
DEFAULT_STALE_DAYS = 7
INGEST_RESOLUTION_VERSION = 1
INGEST_RESOLUTION_DECISIONS = {"separate", "duplicate"}
TODO_SECTION_ORDER = (
    ("overdue", "Просрочено"),
    ("today", "Сегодня"),
    ("follow_ups", "Follow-ups"),
    ("apply_not_submitted", "Apply not submitted"),
    ("stale_review", "Stale review"),
    ("verification_queue", "Verification queue"),
    ("upcoming_interview_test", "Upcoming interview / test"),
)
TRACKER_SECTION_ORDER = ("action_now", "applications", "to_verify", "archive")
TRACKER_SECTION_TITLES = {
    "action_now": "Action now",
    "applications": "Applications",
    "to_verify": "To verify",
    "archive": "Archive",
}
TRACKER_APPLICATION_STATUS_ORDER = {
    "offer": 0,
    "interviewing": 1,
    "applied": 2,
    "rejected": 3,
    "ghosted": 4,
    "withdrawn": 5,
}

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

HIMALAYAS_SCREENING_REPAIR_EXCLUSIONS = {
    "job-0102", "job-0110", "job-0111", "job-0124",
}
HIMALAYAS_SCREENING_REPAIR_IDS = tuple(
    f"job-{number:04d}"
    for number in range(99, 127)
    if f"job-{number:04d}" not in HIMALAYAS_SCREENING_REPAIR_EXCLUSIONS
)
HIMALAYAS_SCREENING_REPAIR_FIELDS = (
    "listing_status", "first_party_verified", "apply_verified", "verified_at",
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


class JobsArgumentParser(argparse.ArgumentParser):
    """Argparse с едиными кодами завершения для CLI."""

    def error(self, message):
        self.print_usage(sys.stderr)
        die(message)


class UnresolvedDuplicate(Exception):
    """Нужна явная команда пользователя: duplicate или force."""

    def __init__(self, candidates):
        self.candidates = candidates


class SourceReferenceConflict(Exception):
    """Source reference already belongs to another canonical job."""

    def __init__(self, message, existing):
        self.message = message
        self.existing = existing


class ValidationError(Exception):
    """A rejected write reachable from the connector path.

    Raised instead of calling die() so agent_operations.execute() can catch it
    and record a machine-readable rejected result; the CLI still catches this
    at the top of main() and prints the same "error: ..." text via die().
    """


@dataclass(frozen=True)
class JobIdRange:
    start: int
    end: int

    def contains(self, job_id):
        match = re.fullmatch(r"job-(\d{4,})", job_id or "")
        return bool(match and self.start <= int(match.group(1)) <= self.end)

    def display(self):
        return f"job-{self.start:04d}:job-{self.end:04d}"


@dataclass
class AddPlan:
    rows: list
    source_rows: list
    row: dict
    warnings: list
    app_path: Path | None
    app_body: str | None
    source_reference: dict | None
    source_reference_created: bool


@dataclass
class IngestPlan:
    batch_id: str | None
    resolution_path: str | None
    resolutions_used: int
    rows: list
    source_rows: list
    outcomes: list
    summary: dict
    errors: list
    warnings: list
    invalid: bool
    fuzzy: bool
    jobs_created: int
    source_references_created: int


def today():
    return business_date().isoformat()


def positive_int(value):
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("ожидается положительное целое число") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("ожидается положительное целое число")
    return parsed


def iso_date_argument(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise argparse.ArgumentTypeError("ожидается дата YYYY-MM-DD") from error


def job_id_range_argument(value):
    match = re.fullmatch(r"job-(\d{4,}):job-(\d{4,})", value or "")
    if not match:
        raise argparse.ArgumentTypeError("ожидается диапазон job-NNNN:job-NNNN")
    start, end = (int(part) for part in match.groups())
    if start > end:
        raise argparse.ArgumentTypeError("начало id-range не может быть больше конца")
    return JobIdRange(start, end)


def die(message):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def read_csv():
    if not CSV_PATH.exists():
        die(f"не найден {CSV_PATH}")
    with CSV_PATH.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames, list(reader)


def read_job_sources_csv():
    if not JOB_SOURCES_PATH.exists():
        die(f"не найден {JOB_SOURCES_PATH}")
    with JOB_SOURCES_PATH.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames, list(reader)


def load():
    header, rows = read_csv()
    if header != FIELDS:
        die("заголовок jobs.csv не совпадает со схемой v2; для v1 используйте migrate-v2")
    return rows


def load_v1():
    header, rows = read_csv()
    if tuple(header or []) not in {tuple(V1_FIELDS), tuple(V1_LEGACY_FIELDS)}:
        if header == FIELDS:
            die("jobs.csv уже использует схему v2; migrate-v2 больше не требуется")
        die("заголовок jobs.csv не является поддерживаемой схемой v1")
    return rows


def load_job_sources(allow_missing=False):
    if allow_missing and not JOB_SOURCES_PATH.exists():
        return []
    header, rows = read_job_sources_csv()
    if header != JOB_SOURCE_FIELDS:
        die("заголовок job_sources.csv не совпадает со схемой; см. data/schema.md")
    return rows


def save(rows):
    """Атомарно заменяет CSV, чтобы ошибка не оставила обрезанный файл."""
    descriptor, temporary_name = tempfile.mkstemp(prefix="jobs-", suffix=".csv", dir=CSV_PATH.parent)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: row.get(key) or "" for key in FIELDS} for row in rows)
        os.replace(temporary_name, CSV_PATH)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def save_job_sources(rows):
    descriptor, temporary_name = tempfile.mkstemp(prefix="job-sources-", suffix=".csv", dir=JOB_SOURCES_PATH.parent)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=JOB_SOURCE_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: row.get(key) or "" for key in JOB_SOURCE_FIELDS} for row in rows)
        os.replace(temporary_name, JOB_SOURCES_PATH)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def norm(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return re.sub(r"\s+", " ", "".join(char if char.isalnum() else " " for char in text)).strip()


def norm_url(value):
    if not value:
        return ""
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return value.strip()
    query = [
        (key, val)
        for key, val in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in {"ref", "referrer"}
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(query), ""))


COMPANY_NOISE = {"ltd", "limited", "inc", "incorporated", "llc", "llp", "plc", "gmbh", "ag", "bv", "nv", "ab", "oy", "oyj", "as", "sa", "sas", "srl", "spa", "doo", "ooo", "corp", "corporation", "co", "company", "group", "holding", "holdings", "the"}
ROLE_NOISE = {"developer", "engineer", "software", "web", "senior", "junior", "middle", "mid", "associate", "graduate", "intern", "internship", "remote", "m", "f", "d", "x", "the", "and"}
# Undisclosed/anonymized listings all read as the same company to SequenceMatcher
# (company_score=1.00 against each other), which turned every such pair into a
# false duplicate candidate. See docs/agent-write-path-plan-2026-09-07.md, Э5/P7.
PLACEHOLDER_COMPANY_RE = re.compile(r"^(undisclosed|unknown|confidential|n/?a)\b", re.IGNORECASE)


def without_noise(text, noise):
    normalized = norm(text)
    result = " ".join(word for word in normalized.split() if word not in noise)
    return result or normalized


def similarity(first, second):
    return SequenceMatcher(None, first, second).ratio()


def slug(value):
    return norm(value).replace(" ", "-")[:28].strip("-")


def next_id(rows):
    numbers = [int(match.group(1)) for row in rows if (match := re.fullmatch(r"job-(\d{4,})", row["id"] or ""))]
    return f"job-{max(numbers, default=0) + 1:04d}"


def find(rows, job_id):
    for row in rows:
        if row["id"] == job_id:
            return row
    die(f"запись {job_id} не найдена")


def valid_http_url(value):
    try:
        parts = urlsplit(value)
        return parts.scheme in {"http", "https"} and bool(parts.netloc)
    except ValueError:
        return False


def validate_rows(rows):
    errors, warnings, ids, urls, duplicate_refs = [], [], {}, {}, []

    def error(line, message):
        errors.append(f"строка {line}: {message}")

    for line, row in enumerate(rows, start=2):
        identifier = row.get("id") or "<пусто>"
        if None in row:
            error(line, f"{identifier}: лишние CSV-колонки: {row[None]}")
        for key in REQUIRED:
            if not (row.get(key) or "").strip():
                error(line, f"{identifier}: пустое обязательное поле {key}")
        if row.get("id") and not re.fullmatch(r"job-\d{4,}", row["id"]):
            error(line, f"{identifier}: id должен быть вида job-NNNN")
        if row.get("id") in ids:
            error(line, f"{identifier}: дубль id (уже в строке {ids[row['id']]})")
        ids[row.get("id")] = line
        for key, allowed in ENUMS.items():
            value = (row.get(key) or "").strip()
            if value and value not in allowed:
                error(line, f"{identifier}: {key}={value!r} не входит в {allowed}")
        for key in DATE_FIELDS:
            value = (row.get(key) or "").strip()
            if not value:
                continue
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                error(line, f"{identifier}: {key}={value!r} — ожидается YYYY-MM-DD")
            else:
                if key != "next_action_date" and parsed > business_date():
                    warnings.append(f"строка {line}: {identifier}: {key}={value} в будущем — опечатка в годе?")
        score = (row.get("match_score") or "").strip()
        if score:
            try:
                parsed_score = float(score)
                if not math.isfinite(parsed_score) or not 1 <= parsed_score <= 10:
                    error(line, f"{identifier}: match_score вне диапазона 1–10")
            except ValueError:
                error(line, f"{identifier}: match_score не число: {score!r}")
        original_url = (row.get("original_url") or "").strip()
        if original_url:
            if not valid_http_url(original_url):
                error(line, f"{identifier}: original_url не является http(s) URL: {original_url!r}")
            else:
                urls.setdefault(norm_url(original_url), []).append((line, row))
        cover_letter = (row.get("cover_letter") or "").strip()
        if cover_letter and cover_letter != "no" and "/" not in cover_letter:
            error(line, f"{identifier}: cover_letter должен быть 'no' или путём (например cv/cover-letters/...), получено {cover_letter!r}")
        application_status = row.get("application_status") or ""
        listing_status = row.get("listing_status") or ""
        reason = row.get("decision_reason") or ""
        verified_at = row.get("verified_at") or ""
        first_party_verified = row.get("first_party_verified") or ""
        apply_verified = row.get("apply_verified") or ""
        if application_status in NEEDS_APPLIED_AT and not (row.get("applied_at") or "").strip():
            error(line, f"{identifier}: application_status={application_status} требует applied_at")
        if application_status in RESPONDED_APPLICATION_STATUSES and not (row.get("response_at") or "").strip():
            error(line, f"{identifier}: application_status={application_status} требует response_at")
        if application_status in {"not_started", "reviewing", "apply"} and (row.get("applied_at") or "").strip():
            error(line, f"{identifier}: application_status={application_status} несовместим с applied_at")
        if application_status == "withdrawn" and not reason:
            error(line, f"{identifier}: application_status=withdrawn требует decision_reason")
        if reason == "other" and not (row.get("notes") or "").strip():
            error(line, f"{identifier}: decision_reason=other требует пояснения в notes")
        if reason and application_status in IN_PROGRESS_APPLICATION_STATUSES:
            error(line, f"{identifier}: decision_reason={reason} несовместим с application_status={application_status}; закрытое решение хранится как not_started")
        elif reason in PRE_APPLICATION_REASONS and application_status != "not_started":
            error(line, f"{identifier}: decision_reason={reason} требует application_status=not_started")
        if reason == "closed_before_application":
            if listing_status != "closed":
                error(line, f"{identifier}: closed_before_application требует listing_status=closed")
            if (row.get("applied_at") or "").strip():
                error(line, f"{identifier}: closed_before_application несовместим с applied_at")
        if listing_status == "closed" and application_status in PRE_APPLICATION_STATUSES:
            if application_status != "not_started":
                error(line, f"{identifier}: listing_status=closed до отклика требует application_status=not_started")
            elif reason != "closed_before_application":
                error(line, f"{identifier}: closed before application требует decision_reason=closed_before_application")
        if reason == "duplicate_listing":
            if application_status != "not_started":
                error(line, f"{identifier}: duplicate_listing требует application_status=not_started")
            match = re.search(r"\bjob-\d{4,}\b", row.get("notes") or "")
            if not match:
                error(line, f"{identifier}: duplicate_listing требует id оригинала в notes")
            else:
                duplicate_refs.append((line, identifier, match.group(0)))
        if first_party_verified == "yes" and not original_url:
            error(line, f"{identifier}: first_party_verified=yes требует original_url")
        if apply_verified == "yes" and first_party_verified != "yes":
            error(line, f"{identifier}: apply_verified=yes требует first_party_verified=yes")
        if (first_party_verified in {"yes", "no"} or apply_verified in {"yes", "no"}) and not verified_at:
            error(line, f"{identifier}: verification yes/no требует verified_at")
        if apply_verified == "yes" and not verified_at:
            error(line, f"{identifier}: apply_verified=yes требует verified_at")
        if application_status in NEEDS_APPLIED_AT and (row.get("stage_reached") or "None") == "None":
            error(line, f"{identifier}: application_status={application_status}, но stage_reached=None")
        if row.get("stage_reached") == "Offer" and application_status not in {"offer", "rejected", "withdrawn"}:
            warnings.append(f"строка {line}: {identifier}: stage=Offer при application_status={application_status}")
        try:
            if row.get("response_at") and row.get("applied_at") and datetime.strptime(row["response_at"], "%Y-%m-%d") < datetime.strptime(row["applied_at"], "%Y-%m-%d"):
                error(line, f"{identifier}: response_at раньше applied_at")
        except ValueError:
            pass
        if "\n" in (row.get("notes") or ""):
            error(line, f"{identifier}: перевод строки в notes; длинный текст → applications/{identifier}.md")
    for canonical, entries in urls.items():
        if len(entries) > 1 and len([row for _, row in entries if row.get("decision_reason") != "duplicate_listing"]) != 1:
            labels = ", ".join(f"{row['id']}@{line}" for line, row in entries)
            errors.append(f"canonical original_url={canonical!r}: ожидается ровно одна оригинальная запись, получено: {labels}")
    for line, identifier, original in duplicate_refs:
        if original == identifier:
            error(line, f"{identifier}: duplicate_listing ссылается сам на себя")
        elif original not in ids:
            error(line, f"{identifier}: оригинал {original} не найден")
    return errors, warnings


def temporal_notices(rows):
    """Return hints that depend on today's date rather than on row content.

    A row can start producing one without anyone touching the dataset, so these
    never become errors or warnings: they would turn `validate --strict`, every
    write path and CI red on a calendar boundary. They are reported next to
    validation output instead.
    """
    notices = []
    for line, row in enumerate(rows, start=2):
        identifier = row.get("id") or "<пусто>"
        applied_at = (row.get("applied_at") or "").strip()
        if (row.get("application_status") or "") != "applied" or not applied_at:
            continue
        if (row.get("response_at") or "").strip():
            continue
        try:
            applied = datetime.strptime(applied_at, "%Y-%m-%d").date()
        except ValueError:
            continue
        days = (business_date() - applied).days
        if days > GHOST_AFTER_DAYS:
            notices.append(f"строка {line}: {identifier}: {days} дней без ответа → application_status=ghosted?")
    return notices


def validate_job_sources(job_rows, source_rows):
    errors, warnings = [], []
    job_ids = {row["id"] for row in job_rows}
    source_ids = {}
    source_urls = {}

    def error(line, message):
        errors.append(f"job_sources.csv:{line}: {message}")

    for line, row in enumerate(source_rows, start=2):
        identifier = row.get("job_id") or "<пусто>"
        if None in row:
            error(line, f"{identifier}: лишние CSV-колонки: {row[None]}")
        for key in ("job_id", "source", "found_at"):
            if not (row.get(key) or "").strip():
                error(line, f"{identifier}: пустое обязательное поле {key}")
        job_id = (row.get("job_id") or "").strip()
        source = (row.get("source") or "").strip()
        source_url = (row.get("source_url") or "").strip()
        source_job_id = (row.get("source_job_id") or "").strip()
        found_at = (row.get("found_at") or "").strip()
        if job_id and job_id not in job_ids:
            error(line, f"{identifier}: job_id не найден в jobs.csv")
        if source and source not in SOURCES:
            error(line, f"{identifier}: source={source!r} не входит в {SOURCES}")
        if not source_url and not source_job_id:
            error(line, f"{identifier}: нужен source_url или source_job_id")
        if source_url and not valid_http_url(source_url):
            error(line, f"{identifier}: source_url не является http(s) URL: {source_url!r}")
        if found_at:
            try:
                parsed = datetime.strptime(found_at, "%Y-%m-%d").date()
            except ValueError:
                error(line, f"{identifier}: found_at={found_at!r} — ожидается YYYY-MM-DD")
            else:
                if parsed > business_date():
                    warnings.append(f"job_sources.csv:{line}: {identifier}: found_at={found_at} в будущем — опечатка в годе?")
        if "\n" in source_job_id:
            error(line, f"{identifier}: source_job_id содержит перевод строки")
        if source_job_id:
            key = (source, source_job_id)
            if key in source_ids:
                error(line, f"{identifier}: дубль source + source_job_id (уже в строке {source_ids[key]})")
            source_ids[key] = line
        if source_url:
            key = (job_id, source, norm_url(source_url))
            if key in source_urls:
                error(line, f"{identifier}: дубль source_url для той же вакансии (уже в строке {source_urls[key]})")
            source_urls[key] = line
    return errors, warnings


def validate_dataset(job_rows, source_rows):
    job_errors, job_warnings = validate_rows(job_rows)
    source_errors, source_warnings = validate_job_sources(job_rows, source_rows)
    return job_errors + source_errors, job_warnings + source_warnings


def ensure_valid(rows, emit_warnings=True):
    errors, warnings = validate_rows(rows)
    if errors:
        die("изменение отклонено:\n  " + "\n  ".join(errors))
    if emit_warnings:
        for warning in warnings:
            print(f"warn:  {warning}")
    return warnings


def ensure_dataset_valid(job_rows, source_rows, emit_warnings=True):
    errors, warnings = validate_dataset(job_rows, source_rows)
    if errors:
        raise ValidationError("изменение отклонено:\n  " + "\n  ".join(errors))
    if emit_warnings:
        for warning in warnings:
            print(f"warn:  {warning}")
    return warnings


def migrate_v1_rows(rows):
    migrated = []
    for line, legacy in enumerate(rows, start=2):
        status = legacy.get("status") or ""
        if status not in V1_STATUS_MAPPING:
            die(f"строка {line}: неизвестный v1 status={status!r}")
        application_status, listing_status = V1_STATUS_MAPPING[status]
        row = {key: legacy.get(key) or "" for key in FIELDS}
        row.update({
            "application_status": application_status,
            "listing_status": listing_status,
            "verified_at": "",
            "first_party_verified": "unknown",
            "apply_verified": "unknown",
        })
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
        "decision_reason_duplicate_listing": sum(row["decision_reason"] == "duplicate_listing" for row in rows),
    }


def migration_summary(rows):
    payload = migration_summary_payload(rows)
    return [
        f"строк: {payload['rows']}",
        f"уникальных id: {payload['unique_ids']}",
        f"с applied_at: {payload['with_applied_at']}",
        f"listing_status=closed: {payload['listing_status_closed']}",
        f"decision_reason=duplicate_listing: {payload['decision_reason_duplicate_listing']}",
    ]


def cmd_migrate_v2(args):
    rows = migrate_v1_rows(load_v1())
    ensure_valid(rows)
    if args.format == "json":
        payload = {
            "ok": True,
            "command": "migrate-v2",
            "mode": "check" if args.check else "migrate",
            "summary": migration_summary_payload(rows),
        }
        if not args.check:
            save(rows)
        payload["saved"] = not args.check
        print_json(payload)
        return
    mode = "проверка" if args.check else "миграция выполнена"
    print(f"v1 → v2: {mode}")
    for line in migration_summary(rows):
        print(line)
    if args.check:
        print("jobs.csv не изменён")
        return
    save(rows)
    print("data/jobs.csv атомарно обновлён")


def himalayas_screening_repair_state(row):
    snapshot = {field: row[field] for field in HIMALAYAS_SCREENING_REPAIR_FIELDS}
    if snapshot == HIMALAYAS_SCREENING_REPAIR_FROM:
        return "pending"
    if snapshot == HIMALAYAS_SCREENING_REPAIR_TO:
        return "repaired"
    return "unexpected"


def repair_himalayas_screening(*, check=False):
    """Repair the exact legacy Himalayas screening batch without reclassifying it."""
    rows = load()
    source_rows = load_job_sources()
    by_id = {row["id"]: row for row in rows}
    required_ids = set(HIMALAYAS_SCREENING_REPAIR_IDS) | HIMALAYAS_SCREENING_REPAIR_EXCLUSIONS
    missing = sorted(required_ids - by_id.keys())
    if missing:
        die("repair-himalayas-screening: отсутствуют ожидаемые записи: " + ", ".join(missing))

    targets = [by_id[job_id] for job_id in HIMALAYAS_SCREENING_REPAIR_IDS]
    wrong_batch = [
        row["id"] for row in targets
        if row["source"] != "Himalayas"
        or row["application_status"] != "not_started"
        or not row["decision_reason"]
        or not row["notes"]
    ]
    if wrong_batch:
        die(
            "repair-himalayas-screening: записи не соответствуют старому screening batch: "
            + ", ".join(wrong_batch)
        )
    wrong_exclusions = sorted(
        job_id for job_id in HIMALAYAS_SCREENING_REPAIR_EXCLUSIONS
        if by_id[job_id]["source"] != "Himalayas"
    )
    if wrong_exclusions:
        die(
            "repair-himalayas-screening: исключения больше не относятся к Himalayas: "
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
        die("repair-himalayas-screening: смешанное или неожиданное состояние; " + "; ".join(details))

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
        changed_fields = {field for field in FIELDS if row[field] != before[field]}
        if changed_fields != set(HIMALAYAS_SCREENING_REPAIR_FIELDS):
            die(f"repair-himalayas-screening: нарушен набор изменений для {row['id']}")
        if row["decision_reason"] != before["decision_reason"] or row["notes"] != before["notes"]:
            die(f"repair-himalayas-screening: decision_reason/notes изменены для {row['id']}")
    if any(by_id[job_id] != before for job_id, before in excluded_before.items()):
        die("repair-himalayas-screening: одно из исключений было изменено")

    warnings = ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    apply_dataset_transaction(rows, source_rows)
    payload.update({"status": "applied", "changed": len(targets), "warnings": warnings})
    return payload


def cmd_repair_himalayas_screening(args):
    result = repair_himalayas_screening(check=args.check)
    if args.format == "json":
        print_json(result)
        return
    print(
        f"Himalayas screening repair: {result['status']}; "
        f"targets={result['target_count']}; changed={result['changed']}"
    )
    print("excluded: " + ", ".join(result["excluded_ids"]))
    if args.check:
        print("data/jobs.csv не изменён")


def clean_value(value):
    return str(value or "").replace("\n", " ")


def find_duplicate_candidates(rows, company, role, original_url):
    hits = {}
    if original_url:
        for row in rows:
            if row["original_url"] and norm_url(row["original_url"]) == norm_url(original_url):
                hits[row["id"]] = (row, "совпадение canonical original_url")
    if not PLACEHOLDER_COMPANY_RE.match(company.strip()):
        company_norm, role_norm = without_noise(company, COMPANY_NOISE), without_noise(role, ROLE_NOISE)
        for row in rows:
            if PLACEHOLDER_COMPANY_RE.match(row["company"].strip()):
                continue
            company_score = similarity(company_norm, without_noise(row["company"], COMPANY_NOISE))
            role_score = similarity(role_norm, without_noise(row["role"], ROLE_NOISE))
            if company_score >= .85 and role_score >= .75:
                hits.setdefault(row["id"], (row, f"похоже: company {company_score:.2f}, role {role_score:.2f}"))
    return hits


def print_duplicate_candidates(candidates):
    print("возможные дубли:")
    for row, reason_text in candidates.values():
        print(f"  {row['id']}  {row['company']} — {row['role']}  [{row['application_status']}; {row['listing_status']}]  ({reason_text})")
    print("\nэто дубль -> повторите с --duplicate-of job-NNNN\nэто другая вакансия -> повторите с --force")


def build_add_row(rows, values):
    company = clean_value(values.get("company")).strip()
    role = clean_value(values.get("role")).strip()
    source = clean_value(values.get("source")).strip()
    if not company or not role or not source:
        raise ValidationError("company, role и source обязательны при создании вакансии")
    if source not in SOURCES:
        raise ValidationError(f"source: недопустимое значение {source!r}")
    application_status = clean_value(values.get("application_status") or "not_started")
    listing_status = clean_value(values.get("listing_status") or "unknown")
    first_party_verified = clean_value(values.get("first_party_verified") or "unknown")
    apply_verified = clean_value(values.get("apply_verified") or "unknown")
    level = clean_value(values.get("level") or "Unknown")
    remote_policy = clean_value(values.get("remote_policy") or "Unclear")
    decision_reason = clean_value(values.get("decision_reason"))
    if application_status not in ADD_APPLICATION_STATUSES:
        raise ValidationError(f"application_status: недопустимое значение {application_status!r} для add")
    for key, value, allowed in (
        ("listing_status", listing_status, LISTING_STATUSES),
        ("first_party_verified", first_party_verified, VERIFICATION),
        ("apply_verified", apply_verified, VERIFICATION),
        ("level", level, LEVELS),
        ("remote_policy", remote_policy, REMOTE),
    ):
        if value not in allowed:
            raise ValidationError(f"{key}: недопустимое значение {value!r}")
    if decision_reason and decision_reason not in REASONS:
        raise ValidationError(f"decision_reason: недопустимое значение {decision_reason!r}")
    notes = clean_value(values.get("notes"))
    identifier = next_id(rows)
    verification_touched = (
        listing_status != "unknown"
        or first_party_verified != "unknown"
        or apply_verified != "unknown"
    )
    row = {key: "" for key in FIELDS}
    row.update({
        "id": identifier,
        "application_status": application_status,
        "listing_status": listing_status,
        "company": company,
        "role": role,
        "level": level,
        "original_url": clean_value(values.get("original_url")),
        "source_url": clean_value(values.get("source_url")),
        "source": source,
        "location": clean_value(values.get("location")),
        "remote_policy": remote_policy,
        "stack": clean_value(values.get("stack")),
        "salary": clean_value(values.get("salary")) or "Unknown",
        "posted_at": clean_value(values.get("posted_at")),
        "found_at": clean_value(values.get("found_at")) or today(),
        "match_score": clean_value(values.get("match_score")),
        "stage_reached": "None",
        "decision_reason": decision_reason,
        "first_party_verified": first_party_verified,
        "apply_verified": apply_verified,
        "verified_at": today() if verification_touched else "",
        "last_update": today(),
        "notes": notes,
    })
    return row


def build_source_reference(job_id, values, default_found_at):
    source = clean_value(values.get("source")).strip()
    source_url = clean_value(values.get("source_url")).strip()
    source_job_id = clean_value(values.get("source_job_id")).strip()
    found_at = clean_value(values.get("found_at")).strip() or default_found_at
    if not source:
        raise ValidationError("source обязателен для source reference")
    if source not in SOURCES:
        raise ValidationError(f"source: недопустимое значение {source!r}")
    if not source_url and not source_job_id:
        raise ValidationError("для внешнего источника нужен --source-url или --source-job-id")
    return {
        "job_id": job_id,
        "source": source,
        "source_url": source_url,
        "source_job_id": source_job_id,
        "found_at": found_at,
    }


def prepare_source_reference(source_rows, reference, force=False):
    source = reference["source"]
    source_url = reference["source_url"]
    source_job_id = reference["source_job_id"]
    if source_job_id:
        for existing in source_rows:
            if (existing["source"], existing["source_job_id"]) == (source, source_job_id):
                if existing["job_id"] == reference["job_id"]:
                    return existing, False
                raise SourceReferenceConflict(
                    f"source + source_job_id уже принадлежат {existing['job_id']}", existing,
                )
    if source_url:
        normalized = norm_url(source_url)
        for existing in source_rows:
            if existing["source_url"] and norm_url(existing["source_url"]) == normalized:
                if existing["job_id"] == reference["job_id"] and existing["source"] == source:
                    return existing, False
                if (
                    source in SOURCES_ALLOWING_SHARED_DISCOVERY_URLS
                    and existing["source"] == source
                    and source_job_id
                    and existing["source_job_id"]
                    and existing["source_job_id"] != source_job_id
                ):
                    continue
                if not force:
                    raise SourceReferenceConflict(
                        f"source_url уже принадлежит {existing['job_id']}; используйте --force для shared discovery URL",
                        existing,
                    )
    return reference, True


def source_reference_payload(reference, created):
    return {"reference": reference, "created": created}


def legacy_duplicate_origin(row):
    match = re.search(r"\bjob-\d{4,}\b", row["notes"] or "")
    if not match:
        die(f"{row['id']}: legacy duplicate_listing не содержит id оригинала")
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
        reference = build_source_reference(job_id, job, job["found_at"])
        normalized = norm_url(reference["source_url"])
        shared_url = any(
            existing["source_url"] and norm_url(existing["source_url"]) == normalized
            and existing["job_id"] != job_id
            for existing in prepared_rows
        )
        reference, created = prepare_source_reference(prepared_rows, reference, force=True)
        if created:
            prepared_rows.append(reference)
            summary["created"] += 1
            if shared_url:
                summary["shared_urls"] += 1
        else:
            summary["existing"] += 1
    return prepared_rows, summary


def print_backfill_summary(summary, changed):
    mode = "проверка" if not changed else "backfill выполнен"
    print(f"source references: {mode}")
    print(f"просмотрено job: {summary['scanned']}")
    print(f"создано references: {summary['created']}")
    print(f"существовало references: {summary['existing']}")
    print(f"legacy duplicate redirects: {summary['legacy_redirects']}")
    print(f"явно разрешено shared discovery URL: {summary['shared_urls']}")


def cmd_backfill_sources(args):
    job_rows = load()
    source_rows = load_job_sources(allow_missing=True)
    new_source_rows, summary = backfill_source_references(job_rows, source_rows)
    ensure_dataset_valid(job_rows, new_source_rows)
    if args.format == "json":
        if not args.check:
            save_job_sources(new_source_rows)
        print_json({
            "ok": True,
            "command": "backfill-sources",
            "mode": "check" if args.check else "apply",
            "summary": summary,
            "saved": not args.check,
        })
        return
    print_backfill_summary(summary, changed=not args.check)
    if args.check:
        print("data/job_sources.csv не изменён")
        return
    save_job_sources(new_source_rows)
    print("data/job_sources.csv атомарно обновлён")


def should_create_application_card(row, no_file):
    return not no_file and not (
        row["application_status"] == "not_started" and row["decision_reason"]
    )


APPLICATION_CARD_FRONT_MATTER_FIELDS = (
    "id", "company", "role", "original_url", "verified_at", "listing_status",
    "first_party_verified", "apply_verified",
)


def sync_application_card_front_matter(body, row, app_path):
    """Update current fields and add fields missing from a legacy card."""
    lines = body.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        die(f"{app_path}: отсутствует начало front matter")
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"),
        None,
    )
    if closing_index is None:
        die(f"{app_path}: отсутствует конец front matter")

    missing = []
    for key in APPLICATION_CARD_FRONT_MATTER_FIELDS:
        matches = [
            index for index in range(1, closing_index)
            if re.match(rf"^{re.escape(key)}\s*:", lines[index])
        ]
        if len(matches) > 1:
            die(f"{app_path}: front matter поле {key} указано несколько раз")
        replacement = f"{key}: {row[key]}\n"
        if matches:
            lines[matches[0]] = replacement
        else:
            missing.append(replacement)

    if missing:
        lines[closing_index:closing_index] = missing
    return "".join(lines)


def application_card_path(row):
    return APPS_DIR / f"{row['id']}-{slug(row['company'])}-{slug(row['role'])}.md"


def render_application_card(row, update_existing=False):
    app_path = application_card_path(row)
    if app_path.exists():
        if not update_existing:
            return app_path, None
        original_body = app_path.read_text(encoding="utf-8")
        body = sync_application_card_front_matter(original_body, row, app_path)
        return app_path, body if body != original_body else None
    if not TEMPLATE_PATH.exists():
        die(f"не найден шаблон {TEMPLATE_PATH}")
    body = TEMPLATE_PATH.read_text(encoding="utf-8").replace("{{company}}", row["company"]).replace("{{role}}", row["role"])
    body = sync_application_card_front_matter(body, row, TEMPLATE_PATH)
    return app_path, body


def prepare_add(values, force=False, no_file=False):
    rows = load()
    source_rows = load_job_sources()
    company = clean_value(values.get("company")).strip()
    role = clean_value(values.get("role")).strip()
    original_url = clean_value(values.get("original_url"))
    candidates = find_duplicate_candidates(rows, company, role, original_url)
    if candidates and not force:
        raise UnresolvedDuplicate(candidates)
    row = build_add_row(rows, values)
    new_rows = [*rows, row]
    new_source_rows = list(source_rows)
    source_reference, source_reference_created = None, False
    source_job_id = clean_value(values.get("source_job_id")).strip()
    if row["source_url"] or source_job_id:
        candidate_reference = build_source_reference(row["id"], values, row["found_at"])
        source_reference, source_reference_created = prepare_source_reference(
            source_rows, candidate_reference, force=force,
        )
        if source_reference_created:
            new_source_rows.append(source_reference)
    elif row["source"] not in SOURCES_WITHOUT_EXTERNAL_REFERENCE:
        raise ValidationError(f"source={row['source']} требует source_url или source_job_id")
    app_path, app_body = (None, None)
    if should_create_application_card(row, no_file):
        app_path, app_body = render_application_card(row)
    return AddPlan(
        rows=new_rows,
        source_rows=new_source_rows,
        row=row,
        warnings=ensure_dataset_valid(new_rows, new_source_rows, emit_warnings=False),
        app_path=app_path,
        app_body=app_body,
        source_reference=source_reference,
        source_reference_created=source_reference_created,
    )


def persist_add(plan):
    application_writes = ((plan.app_path, plan.app_body),) if plan.app_body is not None else ()
    apply_dataset_transaction(plan.rows, plan.source_rows, application_writes)
    return plan.app_path if plan.app_body is not None else None


def add_duplicate_source_reference(values, duplicate_of, force=False):
    rows = load()
    source_rows = load_job_sources()
    canonical_job = find(rows, duplicate_of)
    reference = build_source_reference(canonical_job["id"], values, today())
    reference, created = prepare_source_reference(source_rows, reference, force=force)
    new_source_rows = [*source_rows, reference] if created else source_rows
    warnings = ensure_dataset_valid(rows, new_source_rows, emit_warnings=False)
    if created:
        save_job_sources(new_source_rows)
    return {
        "job": canonical_job,
        "warnings": warnings,
        "application_path": None,
        "duplicate_of": canonical_job["id"],
        "source_reference": source_reference_payload(reference, created),
    }


def add_job(values, force=False, duplicate_of=None, no_file=False):
    if duplicate_of:
        return add_duplicate_source_reference(values, duplicate_of, force=force)
    plan = prepare_add(values, force=force, no_file=no_file)
    created_path = persist_add(plan)
    return {
        "job": plan.row,
        "warnings": plan.warnings,
        "application_path": created_path.relative_to(ROOT).as_posix() if created_path else None,
        "source_reference": source_reference_payload(plan.source_reference, plan.source_reference_created)
        if plan.source_reference else None,
    }


def ingest_job_values(rows, fields, decision_reason="", next_action=""):
    """Build an unverified canonical job from a normalized raw record."""
    row = build_add_row(rows, {
        **fields,
        "decision_reason": decision_reason,
    })
    row["next_action"] = next_action
    row["next_action_date"] = ""
    return row


def add_ingest_reference(source_rows, job_id, fields):
    reference = build_source_reference(job_id, fields, fields["found_at"])
    reference, created = prepare_source_reference(source_rows, reference)
    if created:
        source_rows.append(reference)
    return reference, created


def ingest_summary(outcomes):
    summary = {"input": len(outcomes), "invalid": 0, "noise": 0, "skipped": 0, "duplicates": 0, "pending": 0}
    mapping = {
        "invalid": "invalid",
        "noise": "noise",
        "skipped": "skipped",
        "duplicate": "duplicates",
        "pending": "pending",
    }
    for outcome in outcomes:
        summary[mapping[outcome["outcome"]]] += 1
    return summary


def load_ingest_resolutions(path, batch_id):
    """Read explicit fuzzy decisions without ever changing the raw batch."""
    if path is None:
        return {}, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {}, [f"resolution {path}: не удалось прочитать JSON: {error}"]

    errors = []
    if not isinstance(payload, dict):
        return {}, [f"resolution {path}: ожидается JSON object"]
    expected_fields = {"version", "batch_id", "resolutions"}
    if set(payload) != expected_fields:
        errors.append(
            f"resolution {path}: поля должны быть ровно {', '.join(sorted(expected_fields))}"
        )
    if payload.get("version") != INGEST_RESOLUTION_VERSION:
        errors.append(f"resolution {path}: version должен быть {INGEST_RESOLUTION_VERSION}")
    if payload.get("batch_id") != batch_id:
        errors.append(f"resolution {path}: batch_id не совпадает с входным batch")
    entries = payload.get("resolutions")
    if not isinstance(entries, list):
        errors.append(f"resolution {path}: resolutions должен быть массивом")
        return {}, errors

    decisions = {}
    for index, entry in enumerate(entries, start=1):
        label = f"resolution {path} #{index}"
        if not isinstance(entry, dict) or set(entry) != {"line", "candidate", "decision"}:
            errors.append(f"{label}: поля должны быть ровно candidate, decision, line")
            continue
        line = entry["line"]
        if not isinstance(line, int) or isinstance(line, bool) or line <= 0:
            errors.append(f"{label}: line должен быть положительным целым числом")
            continue
        if line in decisions:
            errors.append(f"{label}: line {line} указан повторно")
            continue
        decision = entry["decision"]
        if decision not in INGEST_RESOLUTION_DECISIONS:
            errors.append(f"{label}: decision должен быть separate или duplicate")
            continue
        candidate = entry["candidate"]
        if not isinstance(candidate, dict):
            errors.append(f"{label}: candidate должен быть object")
            continue
        if set(candidate) == {"line"}:
            candidate_line = candidate["line"]
            if not isinstance(candidate_line, int) or isinstance(candidate_line, bool) or candidate_line <= 0:
                errors.append(f"{label}: candidate.line должен быть положительным целым числом")
                continue
            candidate_value = {"line": candidate_line}
        elif set(candidate) == {"job_id"}:
            job_id = candidate["job_id"]
            if not isinstance(job_id, str) or not job_id:
                errors.append(f"{label}: candidate.job_id должен быть непустой строкой")
                continue
            candidate_value = {"job_id": job_id}
        else:
            errors.append(f"{label}: candidate должен содержать ровно line или job_id")
            continue
        decisions[line] = {"decision": decision, "candidate": candidate_value}
    return (decisions if not errors else {}), errors


def resolution_candidate_id(resolution, candidates, job_lines):
    """Resolve a sidecar candidate identity against the current deterministic plan."""
    if "job_id" in resolution["candidate"]:
        target_id = resolution["candidate"]["job_id"]
    else:
        target_line = resolution["candidate"]["line"]
        target_id = next(
            (candidate["id"] for candidate in candidates if job_lines.get(candidate["id"]) == target_line),
            None,
        )
    if target_id not in {candidate["id"] for candidate in candidates}:
        return None
    return target_id


def plan_ingest(path, resolution_path=None):
    """Classify an immutable raw batch without changing canonical files."""
    try:  # Direct CLI execution places scripts/ on sys.path.
        from ingestion import (
            deterministic_duplicate, fuzzy_candidates, load_batch, normalize_record,
            relevance_or_hard_filter,
        )
    except ModuleNotFoundError:  # Unit tests may import this module as scripts.jobs.
        from scripts.ingestion import (
            deterministic_duplicate, fuzzy_candidates, load_batch, normalize_record,
            relevance_or_hard_filter,
        )

    batch = load_batch(path)
    resolutions, resolution_errors = load_ingest_resolutions(resolution_path, batch["batch_id"])
    rows = [dict(row) for row in load()]
    source_rows = [dict(row) for row in load_job_sources()]
    original_job_count = len(rows)
    original_reference_count = len(source_rows)
    outcomes = []
    errors = [*batch["errors"], *resolution_errors]
    source_references_created = 0
    fuzzy = False
    resolutions_used = set()
    job_lines = {}

    for entry in batch["entries"]:
        line_number = entry["line"]
        if entry["errors"]:
            outcomes.append({
                "line": line_number,
                "outcome": "invalid",
                "reason": "raw_validation",
                "errors": entry["errors"],
            })
            continue
        record = entry["record"]
        fields = normalize_record(record)
        if fields["source"] not in SOURCES:
            outcomes.append({
                "line": line_number,
                "outcome": "invalid",
                "reason": "canonical_source_unknown",
                "errors": [f"line {line_number}: source={fields['source']!r} не входит в canonical source enum"],
            })
            continue

        relevance, filter_reason = relevance_or_hard_filter(record, norm(fields["role"]))
        if relevance == "noise":
            outcomes.append({"line": line_number, "outcome": "noise", "reason": filter_reason})
            continue

        duplicate = deterministic_duplicate(
            fields,
            rows,
            source_rows,
            norm,
            norm_url,
            shared_source_url_sources=SOURCES_ALLOWING_SHARED_DISCOVERY_URLS,
        )
        if duplicate:
            job_id, reason = duplicate
            if line_number in resolutions:
                resolutions_used.add(line_number)
            try:
                _reference, created = add_ingest_reference(source_rows, job_id, fields)
            except SourceReferenceConflict as error:
                outcomes.append({
                    "line": line_number,
                    "outcome": "invalid",
                    "reason": "source_reference_conflict",
                    "errors": [f"line {line_number}: {error.message}"],
                })
                continue
            source_references_created += int(created)
            outcomes.append({
                "line": line_number,
                "outcome": "duplicate",
                "reason": reason,
                "job_id": job_id,
                "source_reference_created": created,
            })
            continue

        if relevance == "skipped":
            row = ingest_job_values(rows, fields, decision_reason=filter_reason)
            try:
                _reference, created = add_ingest_reference(source_rows, row["id"], fields)
            except SourceReferenceConflict as error:
                outcomes.append({
                    "line": line_number,
                    "outcome": "invalid",
                    "reason": "source_reference_conflict",
                    "errors": [f"line {line_number}: {error.message}"],
                })
                continue
            rows.append(row)
            job_lines[row["id"]] = line_number
            source_references_created += int(created)
            outcomes.append({
                "line": line_number,
                "outcome": "skipped",
                "reason": filter_reason,
                "job_id": row["id"],
            })
            continue

        candidates = fuzzy_candidates(
            fields, rows, without_noise, similarity, COMPANY_NOISE, ROLE_NOISE,
        )
        resolved_separate = False
        if candidates:
            resolution = resolutions.get(line_number)
            if resolution is None:
                fuzzy = True
                outcomes.append({
                    "line": line_number,
                    "outcome": "pending",
                    "reason": "fuzzy_duplicate_requires_resolution",
                    "candidates": candidates,
                })
                continue
            target_id = resolution_candidate_id(resolution, candidates, job_lines)
            if target_id is None:
                outcomes.append({
                    "line": line_number,
                    "outcome": "invalid",
                    "reason": "fuzzy_resolution_candidate_mismatch",
                    "errors": [f"line {line_number}: resolution candidate не совпадает с fuzzy candidate"],
                })
                continue
            resolutions_used.add(line_number)
            if resolution["decision"] == "duplicate":
                try:
                    _reference, created = add_ingest_reference(source_rows, target_id, fields)
                except SourceReferenceConflict as error:
                    outcomes.append({
                        "line": line_number,
                        "outcome": "invalid",
                        "reason": "source_reference_conflict",
                        "errors": [f"line {line_number}: {error.message}"],
                    })
                    continue
                source_references_created += int(created)
                outcomes.append({
                    "line": line_number,
                    "outcome": "duplicate",
                    "reason": "fuzzy_resolution",
                    "resolution": "duplicate",
                    "job_id": target_id,
                    "source_reference_created": created,
                })
                continue
            resolved_separate = True

        row = ingest_job_values(rows, fields, next_action="verify first-party")
        try:
            _reference, created = add_ingest_reference(source_rows, row["id"], fields)
        except SourceReferenceConflict as error:
            outcomes.append({
                "line": line_number,
                "outcome": "invalid",
                "reason": "source_reference_conflict",
                "errors": [f"line {line_number}: {error.message}"],
            })
            continue
        rows.append(row)
        job_lines[row["id"]] = line_number
        source_references_created += int(created)
        outcome = {
            "line": line_number,
            "outcome": "pending",
            "reason": "verify_first_party",
            "job_id": row["id"],
        }
        if resolved_separate:
            outcome["resolution"] = "separate"
        outcomes.append(outcome)

    summary = ingest_summary(outcomes)
    for line_number in sorted(set(resolutions) - resolutions_used):
        errors.append(f"resolution line {line_number}: не применима к fuzzy candidate в этом batch")
    invalid = bool(errors) or bool(summary["invalid"])
    validation_errors, warnings = validate_dataset(rows, source_rows)
    if validation_errors:
        invalid = True
        errors.extend(validation_errors)
    return IngestPlan(
        batch_id=batch["batch_id"],
        resolution_path=str(resolution_path) if resolution_path else None,
        resolutions_used=len(resolutions_used),
        rows=rows,
        source_rows=source_rows,
        outcomes=outcomes,
        summary=summary,
        errors=errors,
        warnings=warnings,
        invalid=invalid,
        fuzzy=fuzzy,
        jobs_created=len(rows) - original_job_count,
        source_references_created=source_references_created or len(source_rows) - original_reference_count,
    )


@contextmanager
def dataset_write_lock():
    """Serialize the multi-file ingest replacement on platforms with flock."""
    lock_path = CSV_PATH.parent / ".ingest.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        try:
            import fcntl
        except ImportError:
            yield
            return
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def stage_csv(target, fields, rows):
    descriptor, temporary_name = tempfile.mkstemp(prefix=f"{target.stem}-ingest-", suffix=".csv", dir=target.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: row.get(key) or "" for key in fields} for row in rows)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def stage_text(target, body):
    descriptor, temporary_name = tempfile.mkstemp(prefix=f"{target.stem}-ingest-", suffix=target.suffix, dir=target.parent)
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(body)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def backup_file(target):
    if not target.exists():
        return None
    descriptor, temporary_name = tempfile.mkstemp(prefix=f"{target.stem}-backup-", suffix=target.suffix, dir=target.parent)
    backup_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(target.read_bytes())
    except BaseException:
        backup_path.unlink(missing_ok=True)
        raise
    return backup_path


def apply_dataset_transaction(rows, source_rows, application_writes=()):
    """Replace an already validated dataset or restore every replaced file."""
    validation_errors, _warnings = validate_dataset(rows, source_rows)
    if validation_errors:
        raise ValidationError("ingest transaction отклонена:\n  " + "\n  ".join(validation_errors))
    with dataset_write_lock():
        staged, backups, replaced = [], {}, []
        failure_after = os.environ.get("JOBS_INGEST_FAIL_AFTER_REPLACE")
        try:
            failure_after = int(failure_after) if failure_after else None
        except ValueError:
            failure_after = None
        try:
            staged = [
                (CSV_PATH, stage_csv(CSV_PATH, FIELDS, rows)),
                (JOB_SOURCES_PATH, stage_csv(JOB_SOURCES_PATH, JOB_SOURCE_FIELDS, source_rows)),
            ]
            staged.extend((path, stage_text(path, body)) for path, body in application_writes)
            for target, _temporary in staged:
                backups[target] = backup_file(target)
            for index, (target, temporary) in enumerate(staged):
                if failure_after is not None and index >= failure_after:
                    raise OSError("injected ingest replacement failure")
                os.replace(temporary, target)
                replaced.append(target)
            post_errors, _post_warnings = validate_dataset(load(), load_job_sources())
            if post_errors:
                raise OSError("post-commit dataset validation failed: " + "; ".join(post_errors))
        except BaseException:
            for target in reversed(replaced):
                backup = backups[target]
                try:
                    if backup:
                        os.replace(backup, target)
                        backups[target] = None
                    else:
                        target.unlink(missing_ok=True)
                except OSError:
                    pass
            raise
        finally:
            for _target, temporary in staged:
                temporary.unlink(missing_ok=True)
            for backup in backups.values():
                if backup:
                    backup.unlink(missing_ok=True)


def apply_ingest_plan(plan):
    if not plan.jobs_created and not plan.source_references_created:
        return {"jobs_created": 0, "source_references_created": 0, "application_cards_created": 0}
    apply_dataset_transaction(plan.rows, plan.source_rows)
    return {
        "jobs_created": plan.jobs_created,
        "source_references_created": plan.source_references_created,
        "application_cards_created": 0,
    }


def ingest_payload(plan, mode, applied=None, error=None):
    return {
        "ok": error is None,
        "command": "ingest",
        "mode": mode,
        "batch_id": plan.batch_id,
        "resolution": {
            "path": plan.resolution_path,
            "used": plan.resolutions_used,
        } if plan.resolution_path else None,
        "summary": plan.summary,
        "outcomes": plan.outcomes,
        "errors": plan.errors,
        "warnings": plan.warnings,
        "applied": applied,
        "error": error,
    }


def print_ingest_text(payload):
    print(f"batch_id: {payload['batch_id']}")
    for outcome in payload["outcomes"]:
        print(f"line {outcome['line']}: {outcome['outcome']} — {outcome['reason']}")
    summary = payload["summary"]
    print(
        "summary: " + ", ".join(
            f"{key}={summary[key]}" for key in ("input", "invalid", "noise", "skipped", "duplicates", "pending")
        )
    )
    for error in payload["errors"]:
        print(f"error: {error}", file=sys.stderr)


def cmd_ingest(args):
    plan = plan_ingest(args.path, args.resolutions)
    mode = "dry_run" if args.dry_run else "apply"
    error, exit_code, applied = None, 0, None
    if plan.invalid:
        error, exit_code = "invalid_batch", 1
    elif plan.fuzzy:
        error, exit_code = "fuzzy_duplicate_requires_resolution", 2
    elif not args.dry_run:
        try:
            applied = apply_ingest_plan(plan)
        except OSError as apply_error:
            plan.errors.append(f"ingest transaction не применена: {apply_error}")
            error, exit_code = "apply_failed", 1
    payload = ingest_payload(plan, mode, applied=applied, error=error)
    if args.format == "json":
        print_json(payload)
    else:
        print_ingest_text(payload)
    if exit_code:
        raise SystemExit(exit_code)


def add_values_from_args(args):
    return {
        "company": args.company,
        "role": args.role,
        "source": args.source,
        "application_status": args.application_status,
        "listing_status": args.listing_status,
        "first_party_verified": args.first_party_verified,
        "apply_verified": args.apply_verified,
        "level": args.level,
        "remote_policy": args.remote_policy,
        "original_url": args.original_url,
        "source_url": args.source_url,
        "source_job_id": args.source_job_id,
        "location": args.location,
        "stack": args.stack,
        "salary": args.salary,
        "posted_at": args.posted_at,
        "found_at": args.found_at,
        "match_score": args.match_score,
        "decision_reason": args.decision_reason,
        "notes": args.notes,
    }


def parse_add_json(raw, source_name):
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as error:
        die(f"{source_name}: некорректный JSON: {error.msg}")
    if not isinstance(values, dict):
        die(f"{source_name}: ожидается один JSON object")
    unknown = sorted(set(values) - ADD_INPUT_FIELDS)
    if unknown:
        die(f"{source_name}: неизвестные или управляемые поля JSON: {', '.join(unknown)}")
    missing = sorted(key for key in ADD_REQUIRED_INPUT_FIELDS if not values.get(key))
    if missing:
        die(f"{source_name}: обязательные JSON-поля: {', '.join(missing)}")
    for key, value in values.items():
        if key == "match_score":
            valid_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if not isinstance(value, str) and not valid_number:
                die(f"{source_name}: match_score должен быть строкой или числом")
        elif not isinstance(value, str):
            die(f"{source_name}: {key} должен быть строкой")
    return values


def load_add_values(args):
    cli_values = add_values_from_args(args)
    if args.json_path or args.stdin:
        supplied = sorted(key for key, value in cli_values.items() if value is not None)
        if supplied:
            die("--json/--stdin нельзя совмещать с полями вакансии из CLI: " + ", ".join(supplied))
        if args.json_path:
            path = Path(args.json_path)
            try:
                raw = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                die(f"не удалось прочитать JSON {path}: {error}")
            return parse_add_json(raw, str(path))
        return parse_add_json(sys.stdin.read(), "stdin")
    missing = sorted(key for key in ADD_REQUIRED_INPUT_FIELDS if not cli_values.get(key))
    if missing:
        die("для add без --json/--stdin обязательны: " + ", ".join(missing))
    return cli_values


def duplicate_candidates_payload(candidates):
    return [
        {
            "id": row["id"],
            "company": row["company"],
            "role": row["role"],
            "application_status": row["application_status"],
            "listing_status": row["listing_status"],
            "reason": reason,
        }
        for row, reason in candidates.values()
    ]


def cmd_add(args):
    try:
        result = add_job(
            load_add_values(args), force=args.force, duplicate_of=args.duplicate_of,
            no_file=args.no_file,
        )
    except UnresolvedDuplicate as error:
        if args.format == "json":
            print_json({
                "ok": False,
                "command": "add",
                "error": "unresolved_duplicate",
                "candidates": duplicate_candidates_payload(error.candidates),
            })
        else:
            print_duplicate_candidates(error.candidates)
        raise SystemExit(2)
    except SourceReferenceConflict as error:
        if args.format == "json":
            print_json({
                "ok": False,
                "command": "add",
                "error": "source_reference_conflict",
                "message": error.message,
                "existing": error.existing,
            })
        else:
            print(f"source reference conflict: {error.message}")
            print("это отдельная reference -> повторите с --force")
        raise SystemExit(2)
    if args.format == "json":
        print_json({"ok": True, "command": "add", **result})
        return
    for warning in result["warnings"]:
        print(f"warn:  {warning}")
    if result.get("duplicate_of"):
        reference = result["source_reference"]
        state = "добавлена" if reference["created"] else "уже существует"
        print(f"{result['duplicate_of']}  source reference {state}: {reference['reference']['source_url'] or reference['reference']['source_job_id']}")
        return
    if result["application_path"]:
        print(f"создан {result['application_path']}")
    row = result["job"]
    print(f"{row['id']}  {row['company']} — {row['role']}  [{row['application_status']}; {row['listing_status']}]")


def parse_field_assignments(pairs):
    assignments = []
    for pair in pairs:
        if "=" not in pair:
            die(f"ожидается field=value, получено: {pair}")
        key, value = pair.split("=", 1)
        assignments.append((key, value))
    return assignments


def apply_job_changes(row, assignments, stage=None, *, enforce_protected=True):
    """enforce_protected=False is only for internal callers (status_job) that have
    already run the human-confirmed lifecycle gate in apply_status_change."""
    if not assignments and not stage:
        raise ValidationError("нечего менять: укажите field=value и/или --stage")
    verification_touched = False
    for key, raw_value in assignments:
        value = clean_value(raw_value)
        if key not in FIELDS:
            raise ValidationError(f"неизвестное поле: {key}")
        if enforce_protected and key in SET_PROTECTED:
            raise ValidationError(f"поле {key} управляется скриптом и не меняется через field=value")
        if key == "decision_reason" and value == "duplicate_listing" and row["decision_reason"] != "duplicate_listing":
            raise ValidationError("duplicate_listing создаётся только командой add --duplicate-of JOB_ID")
        if key in ENUMS and value and value not in ENUMS[key]:
            raise ValidationError(f"{key}: недопустимое значение {value!r}")
        row[key] = value.replace("\n", " ")
        verification_touched = verification_touched or key in {
            "listing_status", "first_party_verified", "apply_verified",
        }
    if stage:
        if stage not in STAGES:
            raise ValidationError(f"недопустимая стадия: {stage}")
        current = row["stage_reached"] or "None"
        if STAGES.index(stage) < STAGES.index(current):
            raise ValidationError(f"stage_reached нельзя понижать: {current} -> {stage}")
        row["stage_reached"] = stage
        if STAGES.index("Recruiter screen") <= STAGES.index(stage) <= STAGES.index("Final interview") and row["application_status"] == "applied":
            row["application_status"] = "interviewing"
        if stage == "Offer" and row["application_status"] in {"applied", "interviewing"}:
            row["application_status"] = "offer"
    if row["application_status"] in NEEDS_APPLIED_AT and not row["applied_at"]:
        row["applied_at"] = today()
    if row["application_status"] in NEEDS_APPLIED_AT and (row["stage_reached"] or "None") == "None":
        row["stage_reached"] = "Applied"
    if row["application_status"] == "offer":
        row["stage_reached"] = "Offer"
    if row["application_status"] in RESPONDED_APPLICATION_STATUSES and not row["response_at"]:
        row["response_at"] = today()
    if verification_touched:
        row["verified_at"] = today()
    row["last_update"] = today()
    return verification_touched


def set_job(job_id, assignments, stage=None):
    rows = load()
    source_rows = load_job_sources()
    row = find(rows, job_id)
    apply_job_changes(row, assignments, stage=stage)
    warnings = ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    apply_dataset_transaction(rows, source_rows)
    return {"job": row, "warnings": warnings}


def cmd_set(args):
    result = set_job(args.id, parse_field_assignments(args.field), stage=args.stage)
    if args.format == "json":
        print_json({"ok": True, "command": "set", **result})
        return
    for warning in result["warnings"]:
        print(f"warn:  {warning}")
    row = result["job"]
    print(f"{row['id']}  application_status={row['application_status']}  listing_status={row['listing_status']}  stage={row['stage_reached']}")


def validate_status_date(value, field):
    if value is None:
        return None
    value = clean_value(value).strip()
    if not value:
        raise ValidationError(f"status: {field} не может быть пустой датой")
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(f"status: {field} должна быть YYYY-MM-DD")
    if parsed > business_date():
        raise ValidationError(f"status: {field} не может быть в будущем")
    return value


def apply_status_change(row, *, application_status, stage=None, applied_at=None,
                        response_at=None, decision_reason=None, next_action=None,
                        next_action_date=None, cv_version=None, notes=None):
    """Record a user-confirmed lifecycle event without opening arbitrary set fields."""
    target = clean_value(application_status).strip()
    if target not in APPLICATION_STATUSES:
        raise ValidationError(f"status: недопустимый application_status {target!r}")
    if row["applied_at"] and target in PRE_APPLICATION_STATUSES:
        raise ValidationError("status: нельзя вернуть отправленную заявку в pre-application состояние")
    if stage is not None:
        stage = clean_value(stage).strip()
        if stage not in STAGES:
            raise ValidationError(f"status: недопустимая стадия {stage!r}")
    if target in PRE_APPLICATION_STATUSES and stage not in {None, "None"}:
        raise ValidationError(f"status: application_status={target} не принимает post-application stage")
    if target == "applied" and stage not in {None, "Applied"}:
        raise ValidationError("status: application_status=applied допускает только stage=Applied")
    if target == "interviewing" and stage in {"None", "Applied", "Offer"}:
        raise ValidationError("status: interviewing требует interview stage")
    if target == "offer" and stage not in {None, "Offer"}:
        raise ValidationError("status: application_status=offer требует stage=Offer")

    applied_at = validate_status_date(applied_at, "applied_at")
    response_at = validate_status_date(response_at, "response_at")
    if target in PRE_APPLICATION_STATUSES and (applied_at is not None or response_at is not None):
        raise ValidationError("status: pre-application состояние не принимает applied_at/response_at")
    if target == "applied" and response_at is not None:
        raise ValidationError("status: application_status=applied не принимает response_at")
    if next_action_date is not None:
        next_action_date = clean_value(next_action_date).strip()
        if next_action_date:
            try:
                datetime.strptime(next_action_date, "%Y-%m-%d")
            except ValueError:
                raise ValidationError("status: next_action_date должна быть YYYY-MM-DD")

    effective_applied_at = applied_at or row["applied_at"]
    if target in NEEDS_APPLIED_AT and not effective_applied_at and target != "applied":
        raise ValidationError(f"status: переход в {target} без существующей заявки требует --applied-at")
    effective_next_action = row["next_action"] if next_action is None else clean_value(next_action).strip()
    if target == "apply" and not effective_next_action:
        raise ValidationError("status: application_status=apply требует --next-action")
    if target in TERMINAL_APPLICATION_STATUSES and (
        (next_action is not None and clean_value(next_action).strip())
        or (next_action_date is not None and next_action_date)
    ):
        raise ValidationError(f"status: application_status={target} не принимает следующий шаг")
    if next_action_date and (next_action is None or not clean_value(next_action).strip()):
        raise ValidationError("status: next_action_date требует явный --next-action")

    supplied_reason = None if decision_reason is None else clean_value(decision_reason).strip()
    if target == "ghosted":
        if supplied_reason not in {None, "no_response_timeout"}:
            raise ValidationError("status: ghosted допускает только decision_reason=no_response_timeout")
        final_reason = "no_response_timeout"
    elif target == "withdrawn":
        if supplied_reason not in {None, "withdrawn_by_me"}:
            raise ValidationError("status: withdrawn допускает только decision_reason=withdrawn_by_me")
        final_reason = "withdrawn_by_me"
    else:
        if supplied_reason:
            raise ValidationError(f"status: decision_reason не используется для application_status={target}")
        final_reason = ""

    if target == "interviewing" and stage is None:
        current_stage = row["stage_reached"] or "None"
        if STAGES.index(current_stage) < STAGES.index("Recruiter screen"):
            stage = "Recruiter screen"
    elif target == "offer":
        stage = "Offer"

    assignments = [
        ("application_status", target),
        ("decision_reason", final_reason),
    ]
    if applied_at is not None:
        assignments.append(("applied_at", applied_at))
    if response_at is not None:
        assignments.append(("response_at", response_at))
    if cv_version is not None:
        assignments.append(("cv_version", clean_value(cv_version).strip()))
    if notes is not None:
        assignments.append(("notes", clean_value(notes).strip()))

    if target in TERMINAL_APPLICATION_STATUSES or (target == "applied" and next_action is None):
        assignments.extend((("next_action", ""), ("next_action_date", "")))
    else:
        if next_action is not None:
            assignments.append(("next_action", clean_value(next_action).strip()))
        if next_action_date is not None:
            assignments.append(("next_action_date", next_action_date))

    apply_job_changes(row, assignments, stage=stage, enforce_protected=False)
    return "status_changed"


def status_job(job_id, **values):
    rows = load()
    source_rows = load_job_sources()
    row = find(rows, job_id)
    outcome = apply_status_change(row, **values)
    warnings = ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    application_path, application_body = (None, None)
    if row["application_status"] in {"reviewing", "apply"} or row["applied_at"]:
        application_path, application_body = render_application_card(row, update_existing=True)
    application_writes = ((application_path, application_body),) if application_body is not None else ()
    apply_dataset_transaction(rows, source_rows, application_writes)
    return {
        "job": row,
        "warnings": warnings,
        "outcome": outcome,
        "application_path": application_path.relative_to(ROOT).as_posix() if application_path else None,
    }


def cmd_status(args):
    result = status_job(
        args.id,
        application_status=args.application_status,
        stage=args.stage,
        applied_at=args.applied_at,
        response_at=args.response_at,
        decision_reason=args.decision_reason,
        next_action=args.next_action,
        next_action_date=args.next_action_date,
        cv_version=args.cv_version,
        notes=args.notes,
    )
    if args.format == "json":
        print_json({"ok": True, "command": "status", **result})
        return
    row = result["job"]
    print(
        f"{row['id']}  application_status={row['application_status']}  "
        f"stage={row['stage_reached']}"
    )


def apply_screen_decision(row, *, decision_reason, notes=None):
    """Record a pre-application screening decision without claiming verification."""
    decision_reason = clean_value(decision_reason).strip()
    if decision_reason not in SCREEN_REASONS:
        raise ValidationError(f"screen: недопустимая decision_reason {decision_reason!r}")
    if row["application_status"] not in {"not_started", "reviewing", "apply"} or row["applied_at"]:
        raise ValidationError("screen допустим только до фактической отправки заявки")
    if notes is not None:
        row["notes"] = clean_value(notes).strip()
    if decision_reason == "other" and not row["notes"]:
        raise ValidationError("screen decision_reason=other требует --notes")
    row["application_status"] = "not_started"
    row["decision_reason"] = decision_reason
    row["next_action"] = ""
    row["next_action_date"] = ""
    row["last_update"] = today()
    return "screened_out"


def screen_job(job_id, *, decision_reason, notes=None):
    rows = load()
    source_rows = load_job_sources()
    row = find(rows, job_id)
    outcome = apply_screen_decision(row, decision_reason=decision_reason, notes=notes)
    warnings = ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    apply_dataset_transaction(rows, source_rows)
    return {"job": row, "warnings": warnings, "outcome": outcome}


def cmd_screen(args):
    result = screen_job(args.id, decision_reason=args.decision_reason, notes=args.notes)
    if args.format == "json":
        print_json({"ok": True, "command": "screen", **result})
        return
    for warning in result["warnings"]:
        print(f"warn:  {warning}")
    row = result["job"]
    print(f"{row['id']}  Skipped: {row['decision_reason']}  listing_status={row['listing_status']}")


def apply_verify_enrichment(row, **values):
    """Set non-lifecycle facts gathered alongside a completed verification."""
    for key, raw_value in values.items():
        if key not in VERIFY_ENRICHMENT_FIELDS:
            raise ValueError(f"verify enrichment field is not allowed: {key}")
        if raw_value is None:
            continue
        value = clean_value(raw_value).strip()
        if key in ENUMS and value and value not in ENUMS[key]:
            raise ValidationError(f"{key}: недопустимое значение {value!r}")
        row[key] = value


def apply_verify_changes(row, *, listing_status, first_party_verified, apply_verified,
                         original_url=None, decision_reason=None, notes=None, level=None,
                         remote_policy=None, stack=None, salary=None, match_score=None,
                         application_status=None, next_action=None, next_action_date=None):
    """Apply verification fields to an in-memory row and return its outcome."""
    if decision_reason == "duplicate_listing":
        raise ValidationError("duplicate_listing создаётся только командой add --duplicate-of JOB_ID")
    if application_status is not None:
        application_status = clean_value(application_status).strip()
        if application_status != "apply":
            raise ValidationError("verify может установить application_status только в apply")
        next_action = clean_value(next_action or "").strip()
        if not next_action:
            raise ValidationError("application_status=apply требует --next-action")
        if next_action_date is not None:
            next_action_date = clean_value(next_action_date).strip()
            try:
                datetime.strptime(next_action_date, "%Y-%m-%d")
            except ValueError:
                raise ValidationError("--next-action-date должна иметь формат YYYY-MM-DD")
    elif next_action is not None or next_action_date is not None:
        raise ValidationError("--next-action и --next-action-date допустимы только с --application-status apply")
    if decision_reason and application_status is not None:
        raise ValidationError("--decision-reason нельзя сочетать с --application-status apply")
    if original_url is not None:
        row["original_url"] = clean_value(original_url).strip()
    if notes is not None:
        row["notes"] = clean_value(notes).strip()
    apply_verify_enrichment(
        row,
        level=level,
        remote_policy=remote_policy,
        stack=stack,
        salary=salary,
        match_score=match_score,
    )
    row["listing_status"] = listing_status
    row["first_party_verified"] = first_party_verified
    row["apply_verified"] = apply_verified
    row["verified_at"] = today()
    passed = (
        listing_status == "open"
        and first_party_verified == "yes"
        and apply_verified == "yes"
    )
    pre_application = row["application_status"] in {"not_started", "reviewing", "apply"}
    if decision_reason:
        if not pre_application:
            raise ValidationError("--decision-reason допустим только до отклика")
        row["application_status"] = "not_started"
        row["decision_reason"] = decision_reason
        row["next_action"] = ""
        row["next_action_date"] = ""
        outcome = "blocked"
    elif passed:
        if application_status == "apply":
            if not pre_application:
                raise ValidationError("application_status=apply допустим только до фактической отправки заявки")
            row["application_status"] = "apply"
            row["next_action"] = next_action
            row["next_action_date"] = next_action_date or ""
            outcome = "ready_to_continue_application"
        else:
            if row["application_status"] == "not_started":
                row["application_status"] = "reviewing"
            if row["next_action"] == "verify first-party":
                row["next_action"] = ""
                row["next_action_date"] = ""
            outcome = "ready_for_review" if pre_application else "verified_after_application"
    elif pre_application:
        raise ValidationError("для непрошедшей verification до отклика нужен --decision-reason")
    else:
        outcome = "verified_after_application"
    row["last_update"] = today()
    return {"outcome": outcome, "passed": passed}


def prepare_verified_application_write(row, passed):
    """Sync an existing card's front matter on every verify, pass or fail.
    A new card is still only created once verification actually passes."""
    card_exists = application_card_path(row).exists()
    if not card_exists and not (passed and row["application_status"] in {"reviewing", "apply"}):
        return None, None, False
    application_path, application_body = render_application_card(row, update_existing=True)
    application_card_created = application_body is not None and not card_exists
    return application_path, application_body, application_card_created


def verify_job(job_id, *, listing_status, first_party_verified, apply_verified,
               original_url=None, decision_reason=None, notes=None, level=None,
               remote_policy=None, stack=None, salary=None, match_score=None,
               application_status=None, next_action=None, next_action_date=None):
    """Apply a completed first-party verification as one atomic dataset update."""
    rows = load()
    source_rows = load_job_sources()
    row = find(rows, job_id)
    change = apply_verify_changes(
        row,
        listing_status=listing_status,
        first_party_verified=first_party_verified,
        apply_verified=apply_verified,
        original_url=original_url,
        decision_reason=decision_reason,
        notes=notes,
        level=level,
        remote_policy=remote_policy,
        stack=stack,
        salary=salary,
        match_score=match_score,
        application_status=application_status,
        next_action=next_action,
        next_action_date=next_action_date,
    )
    warnings = ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    application_path, application_body, application_card_created = prepare_verified_application_write(
        row, change["passed"],
    )
    application_writes = ((application_path, application_body),) if application_body is not None else ()
    apply_dataset_transaction(rows, source_rows, application_writes)
    return {
        "job": row,
        "warnings": warnings,
        "outcome": change["outcome"],
        "application_path": application_path.relative_to(ROOT).as_posix() if application_path else None,
        "application_card_created": application_card_created,
    }


def cmd_verify(args):
    result = verify_job(
        args.id,
        listing_status=args.listing_status,
        first_party_verified=args.first_party_verified,
        apply_verified=args.apply_verified,
        original_url=args.original_url,
        decision_reason=args.decision_reason,
        notes=args.notes,
        level=args.level,
        remote_policy=args.remote_policy,
        stack=args.stack,
        salary=args.salary,
        match_score=args.match_score,
        application_status=args.application_status,
        next_action=args.next_action,
        next_action_date=args.next_action_date,
    )
    if args.format == "json":
        print_json({"ok": True, "command": "verify", **result})
        return
    for warning in result["warnings"]:
        print(f"warn:  {warning}")
    row = result["job"]
    print(
        f"{row['id']}  {result['outcome']}  "
        f"application_status={row['application_status']}  listing_status={row['listing_status']}"
    )


def cmd_validate(args):
    rows = load()
    source_rows = load_job_sources()
    errors, warnings = validate_dataset(rows, source_rows)
    notices = temporal_notices(rows)
    ok = not errors and not (warnings and args.strict)
    if args.format == "json":
        print_json({
            "ok": ok,
            "command": "validate",
            "checked": len(rows),
            "source_references": len(source_rows),
            "errors": errors,
            "warnings": warnings,
            "notices": notices,
        })
        if not ok:
            raise SystemExit(1)
        return
    for notice in notices:
        print(f"note:  {notice}")
    for warning in warnings:
        print(f"warn:  {warning}")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    print(
        f"\nпроверено записей: {len(rows)}; source references: {len(source_rows)}; "
        f"ошибок: {len(errors)}; предупреждений: {len(warnings)}; заметок: {len(notices)}"
    )
    if not ok:
        raise SystemExit(1)


def find_fuzzy_duplicates(rows, company_threshold, role_threshold):
    candidates = []
    for index, first in enumerate(rows):
        for second in rows[index + 1:]:
            company_score = similarity(without_noise(first["company"], COMPANY_NOISE), without_noise(second["company"], COMPANY_NOISE))
            role_score = similarity(without_noise(first["role"], ROLE_NOISE), without_noise(second["role"], ROLE_NOISE))
            if company_score >= company_threshold and role_score >= role_threshold:
                candidates.append({
                    "company_similarity": round(company_score, 4),
                    "role_similarity": round(role_score, 4),
                    "first": first,
                    "second": second,
                })
    return candidates


def cmd_dupes(args):
    rows = [row for row in load() if row["decision_reason"] != "duplicate_listing"]
    candidates = find_fuzzy_duplicates(rows, args.threshold, args.role_threshold)
    if args.format == "json":
        print_json({
            "ok": not (candidates and args.fail),
            "command": "dupes",
            "candidates": candidates,
        })
    else:
        for candidate in candidates:
            first, second = candidate["first"], candidate["second"]
            print(
                f"company {candidate['company_similarity']:.2f} / role {candidate['role_similarity']:.2f}\n"
                f"  {first['id']}  {first['company']} — {first['role']}  [{first['application_status']}; {first['listing_status']}]\n"
                f"  {second['id']}  {second['company']} — {second['role']}  [{second['application_status']}; {second['listing_status']}]\n"
            )
        print(f"пар-кандидатов: {len(candidates)}")
    if candidates and args.fail:
        raise SystemExit(1)


def parsed_row_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def is_active_candidate(row):
    """Active means there is no terminal decision or completed listing closure."""
    return (
        row["listing_status"] != "closed"
        and not row["decision_reason"]
        and row["application_status"] not in TERMINAL_APPLICATION_STATUSES
    )


def derived_state(row):
    """Return the primary human-facing state while keeping listing state separate."""
    reason = row["decision_reason"]
    if reason == "duplicate_listing":
        return "Duplicate"
    if row["application_status"] == "not_started" and (
        reason == "closed_before_application" or row["listing_status"] == "closed"
    ):
        return "Closed"
    if row["application_status"] == "not_started" and reason:
        return f"Skipped: {reason}"
    return {
        "not_started": "Not started",
        "reviewing": "Reviewing",
        "apply": "Apply",
        "applied": "Applied",
        "interviewing": "Interviewing",
        "offer": "Offer",
        "rejected": "Rejected",
        "ghosted": "Ghosted",
        "withdrawn": "Withdrawn",
    }[row["application_status"]]


def tracker_section(row):
    """Classify one valid canonical row into exactly one browser tracker section."""
    application_status = row["application_status"]
    case_status = derived_state(row)
    if application_status in TRACKER_APPLICATION_STATUS_ORDER:
        return "applications"
    if case_status == "Closed" or case_status == "Duplicate" or case_status.startswith("Skipped: "):
        return "archive"
    if (
        application_status in PRE_APPLICATION_STATUSES
        and row["listing_status"] == "open"
        and not row["decision_reason"]
        and row["first_party_verified"] == "yes"
        and row["apply_verified"] == "yes"
    ):
        return "action_now"
    if (
        application_status in PRE_APPLICATION_STATUSES
        and row["listing_status"] != "closed"
        and not row["decision_reason"]
    ):
        return "to_verify"
    raise ValueError(
        f"{row['id']}: cannot classify application_status={application_status!r}, "
        f"listing_status={row['listing_status']!r}, decision_reason={row['decision_reason']!r}"
    )


def tracker_case_display(case_status):
    """Map an existing derived state to text intended for the Markdown view."""
    if case_status == "Apply":
        return "Ready to apply"
    if case_status.startswith("Skipped: "):
        return f"Skipped: {case_status.removeprefix('Skipped: ').replace('_', ' ')}"
    return case_status


def tracker_listing_display(listing_status):
    return {"unknown": "Not checked", "open": "Open", "closed": "Closed"}[listing_status]


def tracker_decision_display(decision_reason):
    return decision_reason.replace("_", " ") if decision_reason else "—"


def tracker_needs(row):
    """Return domain and display labels for the checks still required by a row."""
    needs = []
    if row["first_party_verified"] != "yes":
        needs.append(("first_party", "First party"))
    if row["apply_verified"] != "yes":
        needs.append(("apply", "Apply"))
    if row["listing_status"] == "unknown":
        needs.append(("listing", "Listing"))
    return needs


def tracker_application_cards(rows):
    """Resolve the one supported Markdown card for every canonical job, if present."""
    cards = {}
    for row in rows:
        job_id = row["id"]
        matches = sorted(set(APPS_DIR.glob(f"{job_id}-*.md")) | set(APPS_DIR.glob(f"{job_id}.md")))
        if len(matches) > 1:
            names = ", ".join(path.name for path in matches)
            raise ValueError(f"{row['id']}: multiple application cards match: {names}")
        if matches:
            cards[row["id"]] = matches[0].relative_to(ROOT).as_posix()
    return cards


def tracker_vacancy_url(row, source_references):
    """Choose the first validated external URL according to the view contract."""
    for value in (row["original_url"], row["source_url"]):
        if valid_http_url(value):
            return value
    for reference in source_references:
        if reference["job_id"] == row["id"] and valid_http_url(reference["source_url"]):
            return reference["source_url"]
    return None


def tracker_action_display(next_action, next_action_date, fallback=None):
    if next_action and next_action_date:
        return f"{next_action} · {next_action_date}"
    if next_action:
        return next_action
    if fallback:
        return f"{fallback} · {next_action_date}" if next_action_date else fallback
    if next_action_date:
        return next_action_date
    return "—"


def tracker_item(row, source_references, application_cards):
    """Build display-ready values without rendering any Markdown."""
    case_status = derived_state(row)
    needs = tracker_needs(row)
    return {
        "id": row["id"],
        "company": row["company"],
        "role": row["role"],
        "vacancy_url": tracker_vacancy_url(row, source_references),
        "application_card": application_cards.get(row["id"]),
        "case_status": case_status,
        "case_status_display": tracker_case_display(case_status),
        "application_status": row["application_status"],
        "listing_status": row["listing_status"],
        "listing_display": tracker_listing_display(row["listing_status"]),
        "match_score": row["match_score"] or None,
        "stage_reached": row["stage_reached"] or None,
        "applied_at": row["applied_at"] or None,
        "next_action": row["next_action"] or None,
        "next_action_date": row["next_action_date"] or None,
        "next_action_display": tracker_action_display(row["next_action"], row["next_action_date"]),
        "found_at": row["found_at"],
        "verified_at": row["verified_at"] or None,
        "last_update": row["last_update"],
        "decision_reason": row["decision_reason"] or None,
        "decision_display": tracker_decision_display(row["decision_reason"]),
        "needs": [need for need, _label in needs],
        "need_display": " + ".join(label for _need, label in needs) or "—",
    }


def tracker_date_sort_value(value, *, descending=False):
    numeric = int(value.replace("-", "")) if value else 0
    return -numeric if descending else (numeric or 99999999)


def tracker_id_number(identifier):
    match = re.fullmatch(r"job-(\d{4,})", identifier)
    if not match:
        raise ValueError(f"invalid tracker job id: {identifier!r}")
    return int(match.group(1))


def sort_tracker_items(section, items):
    if section == "action_now":
        status_order = {"apply": 0, "reviewing": 1, "not_started": 2}
        return sorted(
            items,
            key=lambda item: (
                status_order[item["application_status"]],
                tracker_date_sort_value(item["next_action_date"]),
                -score_priority(item),
                tracker_id_number(item["id"]),
            ),
        )
    if section == "applications":
        return sorted(
            items,
            key=lambda item: (
                TRACKER_APPLICATION_STATUS_ORDER[item["application_status"]],
                tracker_date_sort_value(item["next_action_date"]),
                tracker_date_sort_value(item["last_update"], descending=True),
                tracker_id_number(item["id"]),
            ),
        )
    if section == "to_verify":
        status_order = {"apply": 0, "reviewing": 1, "not_started": 2}
        return sorted(
            items,
            key=lambda item: (
                status_order[item["application_status"]],
                -score_priority(item),
                tracker_date_sort_value(item["found_at"], descending=True),
                tracker_id_number(item["id"]),
            ),
        )
    if section == "archive":
        return sorted(
            items,
            key=lambda item: (
                tracker_date_sort_value(item["last_update"], descending=True),
                -tracker_id_number(item["id"]),
            ),
        )
    raise ValueError(f"unknown tracker section: {section}")


def tracker_payload(rows, source_references, application_cards):
    """Return a deterministic, exhaustive browser-tracker view model."""
    sections = {section: [] for section in TRACKER_SECTION_ORDER}
    for row in rows:
        section = tracker_section(row)
        sections[section].append(tracker_item(row, source_references, application_cards))
    sections = {
        section: sort_tracker_items(section, sections[section])
        for section in TRACKER_SECTION_ORDER
    }
    counts = {section: len(sections[section]) for section in TRACKER_SECTION_ORDER}
    if sum(counts.values()) != len(rows):
        raise ValueError("tracker section counts do not cover every canonical job")
    return {
        "dataset_updated": max((row["last_update"] for row in rows if row["last_update"]), default=None),
        "jobs_total": len(rows),
        "section_order": list(TRACKER_SECTION_ORDER),
        "counts": counts,
        "sections": sections,
    }


def markdown_escape(value):
    """Treat canonical values as plain data, never as Markdown syntax."""
    value = re.sub(r"[\r\n]+", " ", str(value or ""))
    for character in ("\\", "|", "<", ">", "`", "[", "]", "*", "_"):
        value = value.replace(character, f"\\{character}")
    return value


def markdown_url(url):
    """Return a safe Markdown link destination for an already validated http(s) URL."""
    if not url or not valid_http_url(url):
        return None
    return quote(url, safe=":/?&=#%+,-._~!$'()*@;")


def tracker_vacancy_cell(item):
    label = f"{markdown_escape(item['company'])} — {markdown_escape(item['role'])}"
    url = markdown_url(item["vacancy_url"])
    vacancy = f"[{label}](<{url}>)" if url else label
    return f"{vacancy} · {markdown_escape(item['id'])}"


def tracker_card_cell(item):
    path = item["application_card"]
    if not path:
        return "—"
    return f"[Open](../{quote(path, safe='/-._~')})"


def tracker_table(headers, rows):
    if not rows:
        return "No jobs.\n"
    separator = "| " + " | ".join("---" for _header in headers) + " |"
    lines = [
        "| " + " | ".join(headers) + " |",
        separator,
        *("| " + " | ".join(row) + " |" for row in rows),
    ]
    return "\n".join(lines) + "\n"


def render_tracker_markdown(payload):
    """Render the complete canonical browser view with a final newline."""
    counts = payload["counts"]
    updated = payload["dataset_updated"] or "—"
    navigation = " · ".join(
        f"[{TRACKER_SECTION_TITLES[section]} ({counts[section]})](#{TRACKER_SECTION_TITLES[section].lower().replace(' ', '-')})"
        for section in TRACKER_SECTION_ORDER
    )
    parts = [
        "# Job tracker\n",
        "> Generated from [`data/jobs.csv`](../data/jobs.csv). Do not edit manually.\n",
        f"Dataset updated: **{updated}** · Jobs: **{payload['jobs_total']}**\n",
        f"{navigation}\n",
        "## Action now\n",
        tracker_table(
            ("Status", "Vacancy", "Match", "Next action", "Listing", "Card"),
            [
                (
                    markdown_escape(item["case_status_display"]),
                    tracker_vacancy_cell(item),
                    markdown_escape(item["match_score"] or "—"),
                    markdown_escape(item["next_action_display"]),
                    markdown_escape(item["listing_display"]),
                    tracker_card_cell(item),
                )
                for item in payload["sections"]["action_now"]
            ],
        ),
        "## Applications\n",
        tracker_table(
            ("Status", "Vacancy", "Stage", "Applied", "Next action", "Card"),
            [
                (
                    markdown_escape(item["case_status_display"]),
                    tracker_vacancy_cell(item),
                    markdown_escape(item["stage_reached"] or "—"),
                    markdown_escape(item["applied_at"] or "—"),
                    markdown_escape(item["next_action_display"]),
                    tracker_card_cell(item),
                )
                for item in payload["sections"]["applications"]
            ],
        ),
        "## To verify\n",
        tracker_table(
            ("Status", "Vacancy", "Need", "Match", "Next action", "Last checked"),
            [
                (
                    markdown_escape(item["case_status_display"]),
                    tracker_vacancy_cell(item),
                    markdown_escape(item["need_display"]),
                    markdown_escape(item["match_score"] or "—"),
                    markdown_escape(tracker_action_display(
                        item["next_action"], item["next_action_date"], fallback="verify first-party",
                    )),
                    markdown_escape(item["verified_at"] or "Never"),
                )
                for item in payload["sections"]["to_verify"]
            ],
        ),
        "## Archive\n",
        "<details>\n\n",
        f"<summary>Archive ({counts['archive']})</summary>\n\n",
        tracker_table(
            ("Status", "Vacancy", "Decision", "Listing", "Updated"),
            [
                (
                    markdown_escape(item["case_status_display"]),
                    tracker_vacancy_cell(item),
                    markdown_escape(item["decision_display"]),
                    markdown_escape(item["listing_display"]),
                    markdown_escape(item["last_update"]),
                )
                for item in payload["sections"]["archive"]
            ],
        ),
        "\n</details>\n",
    ]
    return "\n\n".join(part.rstrip("\n") for part in parts) + "\n"


def write_or_check_tracker(markdown, check):
    """Atomically write the generated artifact or compare it byte-for-byte."""
    expected = markdown.encode("utf-8")
    if check:
        return TRACKER_PATH.exists() and TRACKER_PATH.read_bytes() == expected
    TRACKER_PATH.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix="tracker-", suffix=".md", dir=TRACKER_PATH.parent)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(expected)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_name, TRACKER_PATH)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return True


def index_tsv_value(value):
    """A tab or newline in a cell would silently corrupt a naive TSV read;
    company/role text is single-line by contract, but this stays defensive."""
    return (value or "").replace("\t", " ").replace("\n", " ").replace("\r", " ")


def render_known_index(rows):
    """Compact company/role dedup hint (docs/agent-write-path-plan-2026-09-07.md,
    Э6): no URLs, so it is not the exact-match dedup key — that's keys.tsv."""
    lines = ["id\tcompany\trole\tapplication_status\tlisting_status\tdecision_reason"]
    for row in sorted(rows, key=lambda item: item["id"]):
        lines.append("\t".join(index_tsv_value(row[field]) for field in (
            "id", "company", "role", "application_status", "listing_status", "decision_reason",
        )))
    return ("\n".join(lines) + "\n").encode("utf-8")


def index_reference_key(reference):
    source_job_id = (reference.get("source_job_id") or "").strip()
    return source_job_id if source_job_id else norm_url(reference.get("source_url") or "")


def index_common_prefix(values):
    """Longest shared prefix across a source's keys, cut back to the last `/`
    so a stripped suffix stays a readable path fragment rather than an
    arbitrary substring."""
    if len(values) < 2:
        return ""
    prefix = values[0]
    for value in values[1:]:
        while not value.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    cut = prefix.rfind("/")
    return prefix[:cut + 1] if cut >= 0 else ""


def render_keys_index(source_rows):
    """Exact-match dedup key per source reference (docs/agent-write-path-plan-
    2026-09-07.md, Э6): source_job_id when known, else normalized source_url.
    Grouped by source with the group's common URL prefix stripped to keep the
    file small; every reference in job_sources.csv is included, not just the
    one recorded on jobs.csv, since a confirmed duplicate may add another."""
    by_source = {}
    for reference in source_rows:
        key = index_reference_key(reference)
        if not key:
            continue
        by_source.setdefault(reference["source"], []).append((reference["job_id"], key))
    blocks = []
    for source in sorted(by_source):
        entries = sorted(by_source[source])
        prefix = index_common_prefix([key for _, key in entries])
        blocks.append(f"# {index_tsv_value(source)}\tprefix={prefix}")
        for job_id, key in entries:
            blocks.append(f"{job_id}\t{key[len(prefix):]}")
    return ("\n".join(blocks) + "\n").encode("utf-8") if blocks else b""


ACTIVE_INDEX_APPLICATION_STATUSES = {"reviewing", "apply", "applied", "interviewing", "offer"}


def is_active_index_row(row):
    """docs/agent-write-path-plan-2026-09-07.md, Э6: reviewing/apply/applied/
    interviewing/offer, plus not_started with no decision_reason yet. Unlike
    is_active_candidate(), this ignores listing_status: an already-applied or
    interviewing job still belongs in the bootstrap slice even after its
    listing closes, since the application itself is still in flight."""
    if row["application_status"] in ACTIVE_INDEX_APPLICATION_STATUSES:
        return True
    return row["application_status"] == "not_started" and not row["decision_reason"]


def render_active_index(rows):
    """All canonical fields for the active slice."""
    active_rows = sorted((row for row in rows if is_active_index_row(row)), key=lambda item: item["id"])
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: row.get(key) or "" for key in FIELDS} for row in active_rows)
    return buffer.getvalue().encode("utf-8")


def write_or_check_index_file(path, data, check):
    """Atomically write a generated index artifact, or compare it byte-for-
    byte (same exact-freshness contract as write_or_check_tracker)."""
    if check:
        return path.exists() and path.read_bytes() == data
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f"{path.stem}-", suffix=path.suffix, dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return True


def cmd_render_index(args):
    rows = load()
    source_rows = load_job_sources(allow_missing=True)
    ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    artifacts = {
        "known": (KNOWN_INDEX_PATH, render_known_index(rows)),
        "keys": (KEYS_INDEX_PATH, render_keys_index(source_rows)),
        "active": (ACTIVE_INDEX_PATH, render_active_index(rows)),
    }
    up_to_date = {name: write_or_check_index_file(path, data, args.check) for name, (path, data) in artifacts.items()}
    all_up_to_date = all(up_to_date.values())
    result = {
        "ok": all_up_to_date if args.check else True,
        "command": "render-index",
        "paths": {name: path.relative_to(ROOT).as_posix() for name, (path, _) in artifacts.items()},
        "up_to_date": up_to_date,
    }
    if args.format == "json":
        print_json(result)
    elif args.check:
        if all_up_to_date:
            print("data/index/* is up to date")
        else:
            stale = [name for name, ok in up_to_date.items() if not ok]
            print(
                "data/index/* is out of date for: " + ", ".join(stale)
                + "; run: python3 scripts/jobs.py render-index",
                file=sys.stderr,
            )
    else:
        print("data/index/* rendered")
    if args.check and not all_up_to_date:
        raise SystemExit(1)


def cmd_render_tracker(args):
    rows = load()
    source_references = load_job_sources()
    ensure_dataset_valid(rows, source_references, emit_warnings=False)
    try:
        application_cards = tracker_application_cards(rows)
        payload = tracker_payload(rows, source_references, application_cards)
        markdown = render_tracker_markdown(payload)
    except ValueError as error:
        die(f"render-tracker: {error}")
    up_to_date = write_or_check_tracker(markdown, args.check)
    result = {
        "ok": up_to_date if args.check else True,
        "command": "render-tracker",
        "path": TRACKER_PATH.relative_to(ROOT).as_posix(),
        "up_to_date": up_to_date,
        "counts": payload["counts"],
    }
    if args.format == "json":
        print_json(result)
    elif args.check:
        if up_to_date:
            print("docs/tracker.md is up to date")
        else:
            print("docs/tracker.md is out of date; run: python3 scripts/jobs.py render-tracker", file=sys.stderr)
    else:
        print("docs/tracker.md rendered")
    if args.check and not up_to_date:
        raise SystemExit(1)


def stale_entries(rows, days, reference_date):
    cutoff = reference_date - timedelta(days=days)
    entries = []
    for row in rows:
        if not is_active_candidate(row):
            continue
        verified_at = parsed_row_date(row["verified_at"])
        if verified_at is None:
            entries.append({"job": row, "reason": "never_verified", "age_days": None})
        elif verified_at < cutoff:
            entries.append({
                "job": row,
                "reason": "verification_expired",
                "age_days": (reference_date - verified_at).days,
            })
    return entries


def score_priority(row):
    try:
        return float(row["match_score"])
    except (TypeError, ValueError):
        return 0.0


def todo_item(row, item_date="", reason=None):
    return {
        "id": row["id"],
        "company": row["company"],
        "role": row["role"],
        "date": item_date,
        "priority": score_priority(row) or None,
        "application_status": row["application_status"],
        "listing_status": row["listing_status"],
        "stage_reached": row["stage_reached"],
        "next_action": row["next_action"],
        "reason": reason,
    }


def sorted_todo_items(items):
    return sorted(
        items,
        key=lambda item: (item["date"] or "9999-12-31", -float(item["priority"] or 0), item["id"]),
    )


def todo_sections(rows, reference_date, stale_days=DEFAULT_STALE_DAYS):
    reference = reference_date.isoformat()
    sections = {key: [] for key, _title in TODO_SECTION_ORDER}
    stale_by_id = {entry["job"]["id"]: entry for entry in stale_entries(rows, stale_days, reference_date)}
    interview_stages = {"Recruiter screen", "Tech interview", "Test task", "Final interview"}
    for row in rows:
        action_date = row["next_action_date"]
        if action_date and action_date < reference:
            sections["overdue"].append(todo_item(row, action_date))
        elif action_date == reference:
            sections["today"].append(todo_item(row, action_date))
        if "follow-up" in (row["next_action"] or "").casefold() and (not action_date or action_date > reference):
            sections["follow_ups"].append(todo_item(row, action_date))
        if row["application_status"] == "apply":
            sections["apply_not_submitted"].append(todo_item(row, action_date))
        if row["application_status"] == "reviewing" and row["id"] in stale_by_id:
            stale = stale_by_id[row["id"]]
            stale_date = row["verified_at"] or row["last_update"]
            sections["stale_review"].append(todo_item(row, stale_date, stale["reason"]))
        if (
            is_active_candidate(row)
            and (row["first_party_verified"] != "yes" or row["apply_verified"] != "yes")
        ):
            sections["verification_queue"].append(todo_item(row, action_date or row["last_update"]))
        if is_active_candidate(row) and row["stage_reached"] in interview_stages:
            sections["upcoming_interview_test"].append(todo_item(row, action_date or row["response_at"]))
    return {key: sorted_todo_items(items) for key, items in sections.items()}


def filter_todo_rows(rows, *, source=None, id_range=None):
    """Restrict the read-only queue without changing its classification rules."""
    return [
        row for row in rows
        if (source is None or row["source"] == source)
        and (id_range is None or id_range.contains(row["id"]))
    ]


def percent(numerator, denominator):
    return round(numerator / denominator * 100, 1) if denominator else None


def stats_payload(rows, reference_date, stale_days=DEFAULT_STALE_DAYS):
    """Return the complete structured source for daily and weekly reporting."""
    active = [row for row in rows if is_active_candidate(row)]
    stale = stale_entries(rows, stale_days, reference_date)
    applied = [row for row in rows if row["applied_at"]]
    responses = [row for row in rows if row["response_at"]]
    fully_verified = [
        row for row in active
        if row["first_party_verified"] == "yes" and row["apply_verified"] == "yes"
    ]
    funnel = []
    for stage in STAGES[1:]:
        reached = sum(STAGES.index(row["stage_reached"] or "None") >= STAGES.index(stage) for row in rows)
        funnel.append({"stage": stage, "reached": reached, "percent_of_applications": percent(reached, len(applied))})
    sources = []
    for source in SOURCES:
        source_rows = [row for row in rows if row["source"] == source]
        if source_rows:
            source_applied = sum(bool(row["applied_at"]) for row in source_rows)
            source_responses = sum(bool(row["response_at"]) for row in source_rows)
            sources.append({
                "source": source,
                "found": len(source_rows),
                "applied": source_applied,
                "responses": source_responses,
                "response_rate": percent(source_responses, source_applied),
            })
    cv_versions = []
    for version in sorted({row["cv_version"] for row in rows if row["cv_version"]} | {"not recorded"}):
        version_rows = [
            row for row in applied
            if (row["cv_version"] or "not recorded") == version
        ]
        if version_rows:
            version_responses = sum(bool(row["response_at"]) for row in version_rows)
            cv_versions.append({
                "cv_version": version,
                "applied": len(version_rows),
                "responses": version_responses,
                "response_rate": percent(version_responses, len(version_rows)),
            })
    stale_items = [
        {
            "id": entry["job"]["id"],
            "verified_at": entry["job"]["verified_at"],
            "reason": entry["reason"],
            "age_days": entry["age_days"],
        }
        for entry in sorted(stale, key=lambda entry: (entry["job"]["verified_at"] or "0000-00-00", entry["job"]["id"]))
    ]
    state_order = [
        "Not started", "Reviewing", "Apply", "Applied", "Interviewing", "Offer",
        "Rejected", "Ghosted", "Withdrawn", "Closed", "Duplicate",
        *(f"Skipped: {reason}" for reason in REASONS),
    ]
    derived_state_counts = {
        state: sum(derived_state(row) == state for row in rows)
        for state in state_order
    }
    return {
        "ok": True,
        "command": "stats",
        "as_of": reference_date.isoformat(),
        "jobs_total": len(rows),
        "application_status": {
            status: sum(row["application_status"] == status for row in rows)
            for status in APPLICATION_STATUSES
        },
        "listing_status": {
            status: sum(row["listing_status"] == status for row in rows)
            for status in LISTING_STATUSES
        },
        "derived_state": {
            state: amount for state, amount in derived_state_counts.items() if amount
        },
        "derived": {
            "active_candidates": len(active),
            "skipped": sum(
                row["application_status"] == "not_started"
                and bool(row["decision_reason"])
                and row["decision_reason"] not in {"duplicate_listing", "closed_before_application"}
                for row in rows
            ),
            "closed_before_application": sum(
                row["application_status"] == "not_started" and row["listing_status"] == "closed"
                for row in rows
            ),
            "legacy_duplicates": sum(row["decision_reason"] == "duplicate_listing" for row in rows),
        },
        "verification": {
            "eligible_records": len(active),
            "first_party_verified": {
                value: sum(row["first_party_verified"] == value for row in active)
                for value in VERIFICATION
            },
            "apply_verified": {
                value: sum(row["apply_verified"] == value for row in active)
                for value in VERIFICATION
            },
            "fully_verified": len(fully_verified),
            "coverage_percent": percent(len(fully_verified), len(active)),
        },
        "stale": {"days": stale_days, "count": len(stale_items), "jobs": stale_items},
        "funnel": {
            "applications": len(applied),
            "responses": len(responses),
            "response_rate": percent(len(responses), len(applied)),
            "stages": funnel,
        },
        "sources": sources,
        "cv_versions": cv_versions,
        "decision_reasons": {
            reason: sum(row["decision_reason"] == reason for row in rows)
            for reason in REASONS
        },
    }


def cmd_stale(args):
    rows = load()
    reference_date = args.date or business_date()
    stale = stale_entries(rows, args.days, reference_date)
    payload = {
        "ok": True,
        "command": "stale",
        "as_of": reference_date.isoformat(),
        "days": args.days,
        "count": len(stale),
        "jobs": [
            {
                "id": entry["job"]["id"],
                "company": entry["job"]["company"],
                "role": entry["job"]["role"],
                "verified_at": entry["job"]["verified_at"],
                "reason": entry["reason"],
                "age_days": entry["age_days"],
            }
            for entry in sorted(stale, key=lambda entry: (entry["job"]["verified_at"] or "0000-00-00", entry["job"]["id"]))
        ],
    }
    if args.format == "json":
        print_json(payload)
        return
    print(f"# Stale verification — {payload['as_of']} (>{args.days} days)")
    if not payload["jobs"]:
        print("\nНет просроченных active records.")
        return
    print("\n| id | Компания | Роль | Verified at | Причина | Возраст |\n|---|---|---|---|---|---:|")
    for job in payload["jobs"]:
        age = job["age_days"] if job["age_days"] is not None else "—"
        print(f"| {job['id']} | {job['company']} | {job['role']} | {job['verified_at'] or '—'} | {job['reason']} | {age} |")


def cmd_todo(args):
    rows = filter_todo_rows(load(), source=args.source, id_range=args.id_range)
    reference_date = args.date or business_date()
    sections = todo_sections(rows, reference_date, stale_days=args.stale_days)
    payload = {
        "ok": True,
        "command": "todo",
        "date": reference_date.isoformat(),
        "stale_days": args.stale_days,
        "filters": {
            "source": args.source,
            "id_range": args.id_range.display() if args.id_range else None,
        },
        "section_order": [key for key, _title in TODO_SECTION_ORDER],
        "sections": sections,
    }
    if args.format == "json":
        print_json(payload)
        return
    print(f"# TODO — {payload['date']}")
    titles = dict(TODO_SECTION_ORDER)
    for key, _title in TODO_SECTION_ORDER:
        print(f"\n## {titles[key]}")
        items = sections[key]
        if not items:
            print("Нет задач.")
            continue
        print("\n| Дата | Приоритет | id | Компания | Роль | Действие |\n|---|---:|---|---|---|---|")
        for item in items:
            priority = f"{item['priority']:g}" if item["priority"] is not None else "—"
            action = item["next_action"] or item["reason"] or "—"
            print(f"| {item['date'] or '—'} | {priority} | {item['id']} | {item['company']} | {item['role']} | {action} |")


def cmd_stats(args):
    payload = stats_payload(load(), args.date or business_date(), stale_days=args.stale_days)
    if args.format == "json":
        print_json(payload)
        return
    verification = payload["verification"]
    stale = payload["stale"]
    funnel = payload["funnel"]
    coverage = f"{verification['coverage_percent']:g}%" if verification["coverage_percent"] is not None else "—"
    response_rate = f"{funnel['response_rate']:g}%" if funnel["response_rate"] is not None else "—"
    print(
        f"jobs={payload['jobs_total']}; active_candidates={payload['derived']['active_candidates']}; "
        f"verification_coverage={coverage}; stale={stale['count']}; "
        f"applications={funnel['applications']}; response_rate={response_rate}"
    )


def cmd_report(args):
    payload = stats_payload(load(), args.date or business_date(), stale_days=args.stale_days)
    if args.format == "json":
        print_json(payload)
        return
    print(f"# Отчёт job-searcher — {payload['as_of']}\n\nВсего записей: **{payload['jobs_total']}**")
    print("\n## Основной статус\n\n| Derived state | Кол-во |\n|---|---:|")
    for state, amount in payload["derived_state"].items():
        print(f"| {state} | {amount} |")
    verification = payload["verification"]
    coverage = f"{verification['coverage_percent']:g}%" if verification["coverage_percent"] is not None else "—"
    print(
        "\n## Verification coverage\n\n"
        f"Active candidates: **{verification['eligible_records']}**; fully verified: "
        f"**{verification['fully_verified']}** ({coverage})."
    )
    stale = payload["stale"]
    print(f"\n## Stale verification\n\nOlder than {stale['days']} days: **{stale['count']}**.")
    print("\n## Воронка (по stage_reached)\n\n| Стадия | Достигли | % от откликов |\n|---|---:|---:|")
    for stage in payload["funnel"]["stages"]:
        rate = f"{stage['percent_of_applications']:g}%" if stage["percent_of_applications"] is not None else "—"
        print(f"| {stage['stage']} | {stage['reached']} | {rate} |")
    response_rate = payload["funnel"]["response_rate"]
    rate = f"{response_rate:g}%" if response_rate is not None else "—"
    print(f"\nОтветов: **{payload['funnel']['responses']}** из **{payload['funnel']['applications']}** ({rate}).")
    print("\n## Источники\n\n| Источник | Найдено | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|---:|")
    for source in payload["sources"]:
        rate = f"{source['response_rate']:g}%" if source["response_rate"] is not None else "—"
        print(f"| {source['source']} | {source['found']} | {source['applied']} | {source['responses']} | {rate} |")
    print("\n## Версии CV\n\n| cv_version | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|")
    for version in payload["cv_versions"]:
        rate = f"{version['response_rate']:g}%" if version["response_rate"] is not None else "—"
        print(f"| {version['cv_version']} | {version['applied']} | {version['responses']} | {rate} |")
    print("\n## Свойства объявлений\n\n`listing_status` описывает объявление отдельно от основного статуса.\n")
    print("| Listing status | Кол-во |\n|---|---:|")
    for status, amount in payload["listing_status"].items():
        if amount:
            print(f"| {status} | {amount} |")
    print("\n## Причины отсева\n\n| decision_reason | Кол-во |\n|---|---:|")
    for reason, amount in payload["decision_reasons"].items():
        if amount:
            print(f"| {reason} | {amount} |")


def main():
    parser = JobsArgumentParser(prog="jobs.py", description="CLI для data/jobs.csv")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=JobsArgumentParser)
    add = subparsers.add_parser("add", help="добавить вакансию")
    add.add_argument("--company")
    add.add_argument("--role")
    add.add_argument("--source", choices=SOURCES)
    add.add_argument("--application-status", choices=ADD_APPLICATION_STATUSES)
    add.add_argument("--listing-status", choices=LISTING_STATUSES)
    add.add_argument("--first-party-verified", choices=VERIFICATION)
    add.add_argument("--apply-verified", choices=VERIFICATION)
    add.add_argument("--level", choices=LEVELS)
    add.add_argument("--remote-policy", dest="remote_policy", choices=REMOTE)
    for flag, destination in [
        ("--original-url", "original_url"), ("--source-url", "source_url"),
        ("--source-job-id", "source_job_id"),
        ("--location", "location"), ("--stack", "stack"), ("--salary", "salary"),
        ("--posted-at", "posted_at"), ("--found-at", "found_at"),
        ("--match-score", "match_score"), ("--notes", "notes"),
    ]:
        add.add_argument(flag, dest=destination)
    add.add_argument("--decision-reason", dest="decision_reason", choices=REASONS)
    input_source = add.add_mutually_exclusive_group()
    input_source.add_argument("--json", dest="json_path", metavar="PATH")
    input_source.add_argument("--stdin", action="store_true")
    add.add_argument("--duplicate-of", dest="duplicate_of", metavar="JOB_ID")
    add.add_argument("--no-file", action="store_true")
    add.add_argument("--force", action="store_true")
    add.add_argument("--format", choices=("text", "json"), default="text")
    add.set_defaults(func=cmd_add)
    set_parser = subparsers.add_parser("set", help="изменить запись")
    set_parser.add_argument("id")
    set_parser.add_argument("field", nargs="*")
    set_parser.add_argument("--stage")
    set_parser.add_argument("--format", choices=("text", "json"), default="text")
    set_parser.set_defaults(func=cmd_set)
    status = subparsers.add_parser("status", help="зафиксировать подтверждённое человеком lifecycle-событие")
    status.add_argument("id")
    status.add_argument("--application-status", required=True, choices=APPLICATION_STATUSES)
    status.add_argument("--stage", choices=STAGES)
    status.add_argument("--applied-at")
    status.add_argument("--response-at")
    status.add_argument("--decision-reason", choices=("no_response_timeout", "withdrawn_by_me"))
    status.add_argument("--next-action")
    status.add_argument("--next-action-date")
    status.add_argument("--cv-version")
    status.add_argument("--notes")
    status.add_argument("--format", choices=("text", "json"), default="text")
    status.set_defaults(func=cmd_status)
    screen = subparsers.add_parser("screen", help="зафиксировать pre-application screening decision")
    screen.add_argument("id")
    screen.add_argument("--decision-reason", required=True, choices=sorted(SCREEN_REASONS))
    screen.add_argument("--notes")
    screen.add_argument("--format", choices=("text", "json"), default="text")
    screen.set_defaults(func=cmd_screen)
    verify = subparsers.add_parser("verify", help="зафиксировать completed first-party verification")
    verify.add_argument("id")
    verify.add_argument("--listing-status", required=True, choices=("open", "closed"))
    verify.add_argument("--first-party-verified", required=True, choices=("yes", "no"))
    verify.add_argument("--apply-verified", required=True, choices=("yes", "no"))
    verify.add_argument("--original-url")
    verify.add_argument("--decision-reason", choices=sorted(PRE_APPLICATION_REASONS - {"duplicate_listing"}))
    verify.add_argument("--notes")
    verify.add_argument("--level", choices=LEVELS, help="уровень, подтверждённый при проверке")
    verify.add_argument("--remote-policy", choices=REMOTE, help="remote policy, подтверждённая при проверке")
    verify.add_argument("--stack", help="стек через '; '")
    verify.add_argument("--salary", help="компенсация из первоисточника или Unknown")
    verify.add_argument("--match-score", help="оценка 1–10")
    verify.add_argument("--application-status", choices=("apply",), help="зафиксировать начатый, но не отправленный процесс")
    verify.add_argument("--next-action", help="следующий шаг для application_status=apply")
    verify.add_argument("--next-action-date", help="дата следующего шага YYYY-MM-DD")
    verify.add_argument("--format", choices=("text", "json"), default="text")
    verify.set_defaults(func=cmd_verify)
    validate = subparsers.add_parser("validate", help="проверить целостность")
    validate.add_argument("--strict", action="store_true")
    validate.add_argument("--format", choices=("text", "json"), default="text")
    validate.set_defaults(func=cmd_validate)
    render_tracker = subparsers.add_parser(
        "render-tracker", help="собрать browser-first Markdown view из canonical dataset",
    )
    render_tracker.add_argument("--check", action="store_true", help="проверить freshness без записи")
    render_tracker.add_argument("--format", choices=("text", "json"), default="text")
    render_tracker.set_defaults(func=cmd_render_tracker)
    render_index = subparsers.add_parser(
        "render-index", help="собрать компактные bootstrap-индексы data/index/*",
    )
    render_index.add_argument("--check", action="store_true", help="проверить freshness без записи")
    render_index.add_argument("--format", choices=("text", "json"), default="text")
    render_index.set_defaults(func=cmd_render_index)
    migrate = subparsers.add_parser("migrate-v2", help="однократно мигрировать v1 CSV в v2")
    migrate.add_argument("--check", action="store_true", help="проверить миграцию без записи")
    migrate.add_argument("--format", choices=("text", "json"), default="text")
    migrate.set_defaults(func=cmd_migrate_v2)
    repair_himalayas = subparsers.add_parser(
        "repair-himalayas-screening",
        help="исправить verification у старого Himalayas screening batch",
    )
    repair_himalayas.add_argument("--check", action="store_true", help="проверить repair без записи")
    repair_himalayas.add_argument("--format", choices=("text", "json"), default="text")
    repair_himalayas.set_defaults(func=cmd_repair_himalayas_screening)
    backfill_sources = subparsers.add_parser("backfill-sources", help="создать source references из historical jobs")
    backfill_sources.add_argument("--check", action="store_true", help="проверить backfill без записи")
    backfill_sources.add_argument("--format", choices=("text", "json"), default="text")
    backfill_sources.set_defaults(func=cmd_backfill_sources)
    ingest = subparsers.add_parser("ingest", help="классифицировать raw JSONL batch")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--dry-run", action="store_true", help="не изменять canonical dataset")
    ingest.add_argument("--resolutions", type=Path, help="JSON sidecar с явными решениями fuzzy matches")
    ingest.add_argument("--format", choices=("text", "json"), default="text")
    ingest.set_defaults(func=cmd_ingest)
    dupes = subparsers.add_parser("dupes", help="fuzzy-поиск дублей")
    dupes.add_argument("--threshold", type=float, default=.85)
    dupes.add_argument("--role-threshold", dest="role_threshold", type=float, default=.75)
    dupes.add_argument("--fail", action="store_true")
    dupes.add_argument("--format", choices=("text", "json"), default="text")
    dupes.set_defaults(func=cmd_dupes)
    stale = subparsers.add_parser("stale", help="показать active records с просроченной verification")
    stale.add_argument("--days", required=True, type=positive_int, help="verification старше N дней")
    stale.add_argument("--date", type=iso_date_argument, help="дата среза YYYY-MM-DD (по умолчанию сегодня)")
    stale.add_argument("--format", choices=("text", "json"), default="text")
    stale.set_defaults(func=cmd_stale)
    todo = subparsers.add_parser("todo", help="ежедневная структурированная очередь действий")
    todo.add_argument("--date", type=iso_date_argument, help="дата среза YYYY-MM-DD (по умолчанию сегодня)")
    todo.add_argument("--stale-days", type=positive_int, default=DEFAULT_STALE_DAYS)
    todo.add_argument("--source", choices=SOURCES, help="только вакансии с этим primary source")
    todo.add_argument("--id-range", type=job_id_range_argument, help="inclusive range: job-0099:job-0126")
    todo.add_argument("--format", choices=("text", "json"), default="text")
    todo.set_defaults(func=cmd_todo)
    stats = subparsers.add_parser("stats", help="структурированный daily/weekly snapshot")
    stats.add_argument("--date", type=iso_date_argument, help="дата среза YYYY-MM-DD (по умолчанию сегодня)")
    stats.add_argument("--stale-days", type=positive_int, default=DEFAULT_STALE_DAYS)
    stats.add_argument("--format", choices=("text", "json"), default="text")
    stats.set_defaults(func=cmd_stats)
    report = subparsers.add_parser("report", help="markdown-отчёт в stdout")
    report.add_argument("--date", type=iso_date_argument, help="дата среза YYYY-MM-DD (по умолчанию сегодня)")
    report.add_argument("--stale-days", type=positive_int, default=DEFAULT_STALE_DAYS)
    report.add_argument("--format", choices=("text", "json"), default="text")
    report.set_defaults(func=cmd_report)
    args = parser.parse_args()
    try:
        args.func(args)
    except ValidationError as error:
        die(str(error))


if __name__ == "__main__":
    main()
