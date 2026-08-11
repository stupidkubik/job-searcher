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
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "jobs.csv"
JOB_SOURCES_PATH = ROOT / "data" / "job_sources.csv"
APPS_DIR = ROOT / "applications"
TEMPLATE_PATH = APPS_DIR / "_TEMPLATE.md"

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
LEVELS = ["Intern", "Graduate", "Junior", "Junior+", "Associate", "Junior/Middle", "Middle", "Senior", "Unknown"]
REMOTE = ["Global", "Europe", "EMEA", "Serbia", "Country-specific", "Hybrid", "On-site", "Unclear"]
SOURCES = [
    "Hirify", "Jaabz", "LinkedIn", "Welcome to the Jungle", "We Work Remotely",
    "HiringCafe", "Hacker News — Who is Hiring?", "Hacker News — Who Wants to Be Hired?",
    "YC Work at a Startup", "Wellfound", "HelloWorld.rs", "Reactiflux Discord",
    "Find My Remote / Telegram", "Himalayas", "Startit Jobs", "Company Careers",
    "Referral", "Manual", "Other",
]
REASONS = [
    "geo_restriction", "work_authorization", "seniority_too_high", "seniority_too_low",
    "stack_mismatch", "role_not_frontend", "salary_too_low", "company_not_interesting",
    "closed_before_application", "already_applied", "duplicate_listing",
    "no_response_timeout", "withdrawn_by_me", "other",
]
NEEDS_APPLIED_AT = {"applied", "interviewing", "offer", "rejected", "ghosted", "withdrawn"}
RESPONDED_APPLICATION_STATUSES = {"interviewing", "offer", "rejected"}
PRE_APPLICATION_REASONS = set(REASONS) - {"no_response_timeout", "withdrawn_by_me"}
SET_PROTECTED = {"id", "stage_reached", "verified_at", "last_update"}
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
    return date.today().isoformat()


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
        if not key.lower().startswith("utm_") and key.lower() not in {"ref", "referrer", "source"}
    ]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(query), ""))


COMPANY_NOISE = {"ltd", "limited", "inc", "incorporated", "llc", "llp", "plc", "gmbh", "ag", "bv", "nv", "ab", "oy", "oyj", "as", "sa", "sas", "srl", "spa", "doo", "ooo", "corp", "corporation", "co", "company", "group", "holding", "holdings", "the"}
ROLE_NOISE = {"developer", "engineer", "software", "web", "senior", "junior", "middle", "mid", "associate", "graduate", "intern", "internship", "remote", "m", "f", "d", "x", "the", "and"}


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
                if key != "next_action_date" and parsed > date.today():
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
        if reason in PRE_APPLICATION_REASONS and application_status != "not_started":
            error(line, f"{identifier}: decision_reason={reason} требует application_status=not_started")
        if reason == "closed_before_application":
            if listing_status != "closed":
                error(line, f"{identifier}: closed_before_application требует listing_status=closed")
            if (row.get("applied_at") or "").strip():
                error(line, f"{identifier}: closed_before_application несовместим с applied_at")
        if listing_status == "closed" and application_status == "not_started" and reason != "closed_before_application":
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
        if application_status == "applied" and row.get("applied_at") and not row.get("response_at"):
            try:
                days = (date.today() - datetime.strptime(row["applied_at"], "%Y-%m-%d").date()).days
                if days > GHOST_AFTER_DAYS:
                    warnings.append(f"строка {line}: {identifier}: {days} дней без ответа → application_status=ghosted?")
            except ValueError:
                pass
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
                if parsed > date.today():
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
        die("изменение отклонено:\n  " + "\n  ".join(errors))
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


def migration_summary(rows):
    return [
        f"строк: {len(rows)}",
        f"уникальных id: {len({row['id'] for row in rows})}",
        f"с applied_at: {sum(bool(row['applied_at']) for row in rows)}",
        f"listing_status=closed: {sum(row['listing_status'] == 'closed' for row in rows)}",
        f"decision_reason=duplicate_listing: {sum(row['decision_reason'] == 'duplicate_listing' for row in rows)}",
    ]


def cmd_migrate_v2(args):
    rows = migrate_v1_rows(load_v1())
    ensure_valid(rows)
    mode = "проверка" if args.check else "миграция выполнена"
    print(f"v1 → v2: {mode}")
    for line in migration_summary(rows):
        print(line)
    if args.check:
        print("jobs.csv не изменён")
        return
    save(rows)
    print("data/jobs.csv атомарно обновлён")


def clean_value(value):
    return str(value or "").replace("\n", " ")


def find_duplicate_candidates(rows, company, role, original_url):
    hits = {}
    if original_url:
        for row in rows:
            if row["original_url"] and norm_url(row["original_url"]) == norm_url(original_url):
                hits[row["id"]] = (row, "совпадение canonical original_url")
    company_norm, role_norm = without_noise(company, COMPANY_NOISE), without_noise(role, ROLE_NOISE)
    for row in rows:
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
        die("company, role и source обязательны при создании вакансии")
    if source not in SOURCES:
        die(f"source: недопустимое значение {source!r}")
    application_status = clean_value(values.get("application_status") or "not_started")
    listing_status = clean_value(values.get("listing_status") or "unknown")
    first_party_verified = clean_value(values.get("first_party_verified") or "unknown")
    apply_verified = clean_value(values.get("apply_verified") or "unknown")
    level = clean_value(values.get("level") or "Unknown")
    remote_policy = clean_value(values.get("remote_policy") or "Unclear")
    decision_reason = clean_value(values.get("decision_reason"))
    if application_status not in ADD_APPLICATION_STATUSES:
        die(f"application_status: недопустимое значение {application_status!r} для add")
    for key, value, allowed in (
        ("listing_status", listing_status, LISTING_STATUSES),
        ("first_party_verified", first_party_verified, VERIFICATION),
        ("apply_verified", apply_verified, VERIFICATION),
        ("level", level, LEVELS),
        ("remote_policy", remote_policy, REMOTE),
    ):
        if value not in allowed:
            die(f"{key}: недопустимое значение {value!r}")
    if decision_reason and decision_reason not in REASONS:
        die(f"decision_reason: недопустимое значение {decision_reason!r}")
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
        die("source обязателен для source reference")
    if source not in SOURCES:
        die(f"source: недопустимое значение {source!r}")
    if not source_url and not source_job_id:
        die("для внешнего источника нужен --source-url или --source-job-id")
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


def render_application_card(row, update_existing=False):
    app_path = APPS_DIR / f"{row['id']}-{slug(row['company'])}-{slug(row['role'])}.md"
    if app_path.exists():
        if not update_existing:
            return app_path, None
        original_body = app_path.read_text(encoding="utf-8")
        body = original_body
        for key in (
            "company", "role", "original_url", "verified_at", "listing_status",
            "first_party_verified", "apply_verified",
        ):
            body, replacements = re.subn(
                rf"(?m)^{re.escape(key)}:.*$", f"{key}: {row[key]}", body, count=1,
            )
            if replacements != 1:
                die(f"{app_path}: отсутствует front matter поле {key}")
        return app_path, body if body != original_body else None
    if not TEMPLATE_PATH.exists():
        die(f"не найден шаблон {TEMPLATE_PATH}")
    body = TEMPLATE_PATH.read_text(encoding="utf-8").replace("job-0000", row["id"]).replace("{{company}}", row["company"]).replace("{{role}}", row["role"])
    for key in (
        "company", "role", "original_url", "verified_at", "listing_status",
        "first_party_verified", "apply_verified",
    ):
        body = body.replace(f"{key}:", f"{key}: {row[key]}", 1)
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
        die(f"source={row['source']} требует source_url или source_job_id")
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
    created_path = None
    temporary_path = None
    try:
        if plan.app_path and plan.app_body is not None:
            descriptor, temporary_name = tempfile.mkstemp(prefix="application-", suffix=".md", dir=APPS_DIR)
            temporary_path = Path(temporary_name)
            with os.fdopen(descriptor, "w", encoding="utf-8") as file:
                file.write(plan.app_body)
            os.replace(temporary_path, plan.app_path)
            temporary_path = None
            created_path = plan.app_path
        save(plan.rows)
        save_job_sources(plan.source_rows)
    except BaseException:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        if created_path:
            created_path.unlink(missing_ok=True)
        raise
    return created_path


def add_duplicate_source_reference(values, duplicate_of, force=False):
    rows = load()
    source_rows = load_job_sources()
    canonical_job = find(rows, duplicate_of)
    reference = build_source_reference(canonical_job["id"], values, canonical_job["found_at"])
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
    from ingestion import (
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

        duplicate = deterministic_duplicate(fields, rows, source_rows, norm, norm_url)
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
        die("ingest transaction отклонена:\n  " + "\n  ".join(validation_errors))
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


def apply_job_changes(row, assignments, stage=None):
    if not assignments and not stage:
        die("нечего менять: укажите field=value и/или --stage")
    verification_touched = False
    for key, raw_value in assignments:
        value = clean_value(raw_value)
        if key not in FIELDS:
            die(f"неизвестное поле: {key}")
        if key in SET_PROTECTED:
            die(f"поле {key} управляется скриптом и не меняется через field=value")
        if key == "decision_reason" and value == "duplicate_listing" and row["decision_reason"] != "duplicate_listing":
            die("duplicate_listing создаётся только командой add --duplicate-of JOB_ID")
        if key in ENUMS and value and value not in ENUMS[key]:
            die(f"{key}: недопустимое значение {value!r}")
        row[key] = value.replace("\n", " ")
        verification_touched = verification_touched or key in {
            "listing_status", "first_party_verified", "apply_verified",
        }
    if stage:
        if stage not in STAGES:
            die(f"недопустимая стадия: {stage}")
        current = row["stage_reached"] or "None"
        if STAGES.index(stage) < STAGES.index(current):
            die(f"stage_reached нельзя понижать: {current} -> {stage}")
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
    save(rows)
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


def apply_verify_enrichment(row, **values):
    """Set non-lifecycle facts gathered alongside a completed verification."""
    for key, raw_value in values.items():
        if key not in VERIFY_ENRICHMENT_FIELDS:
            raise ValueError(f"verify enrichment field is not allowed: {key}")
        if raw_value is None:
            continue
        value = clean_value(raw_value).strip()
        if key in ENUMS and value and value not in ENUMS[key]:
            die(f"{key}: недопустимое значение {value!r}")
        row[key] = value


def verify_job(job_id, *, listing_status, first_party_verified, apply_verified,
               original_url=None, decision_reason=None, notes=None, level=None,
               remote_policy=None, stack=None, salary=None, match_score=None,
               application_status=None, next_action=None, next_action_date=None):
    """Apply a completed first-party verification as one atomic dataset update."""
    rows = load()
    source_rows = load_job_sources()
    row = find(rows, job_id)
    if decision_reason == "duplicate_listing":
        die("duplicate_listing создаётся только командой add --duplicate-of JOB_ID")
    if application_status is not None:
        application_status = clean_value(application_status).strip()
        if application_status != "apply":
            die("verify может установить application_status только в apply")
        next_action = clean_value(next_action or "").strip()
        if not next_action:
            die("application_status=apply требует --next-action")
        if next_action_date is not None:
            next_action_date = clean_value(next_action_date).strip()
            try:
                datetime.strptime(next_action_date, "%Y-%m-%d")
            except ValueError:
                die("--next-action-date должна иметь формат YYYY-MM-DD")
    elif next_action is not None or next_action_date is not None:
        die("--next-action и --next-action-date допустимы только с --application-status apply")
    if decision_reason and application_status is not None:
        die("--decision-reason нельзя сочетать с --application-status apply")
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
            die("--decision-reason допустим только до отклика")
        row["application_status"] = "not_started"
        row["decision_reason"] = decision_reason
        row["next_action"] = ""
        row["next_action_date"] = ""
        outcome = "blocked"
    elif passed:
        if application_status == "apply":
            if not pre_application:
                die("application_status=apply допустим только до фактической отправки заявки")
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
        die("для непрошедшей verification до отклика нужен --decision-reason")
    else:
        outcome = "verified_after_application"
    row["last_update"] = today()
    warnings = ensure_dataset_valid(rows, source_rows, emit_warnings=False)

    application_path, application_body = (None, None)
    application_card_created = False
    if passed and row["application_status"] in {"reviewing", "apply"}:
        application_path, application_body = render_application_card(row, update_existing=True)
        application_card_created = application_body is not None and not application_path.exists()
    application_writes = ((application_path, application_body),) if application_body is not None else ()
    apply_dataset_transaction(rows, source_rows, application_writes)
    return {
        "job": row,
        "warnings": warnings,
        "outcome": outcome,
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
    ok = not errors and not (warnings and args.strict)
    if args.format == "json":
        print_json({
            "ok": ok,
            "command": "validate",
            "checked": len(rows),
            "source_references": len(source_rows),
            "errors": errors,
            "warnings": warnings,
        })
        if not ok:
            raise SystemExit(1)
        return
    for warning in warnings:
        print(f"warn:  {warning}")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    print(f"\nпроверено записей: {len(rows)}; source references: {len(source_rows)}; ошибок: {len(errors)}; предупреждений: {len(warnings)}")
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
            row["application_status"] == "not_started"
            and is_active_candidate(row)
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
    reference_date = args.date or date.today()
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
    reference_date = args.date or date.today()
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
    payload = stats_payload(load(), args.date or date.today(), stale_days=args.stale_days)
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
    payload = stats_payload(load(), args.date or date.today(), stale_days=args.stale_days)
    print(f"# Отчёт job-searcher — {payload['as_of']}\n\nВсего записей: **{payload['jobs_total']}**")
    print("\n## Состояния заявок\n\n| Application status | Кол-во |\n|---|---:|")
    for status, amount in payload["application_status"].items():
        if amount:
            print(f"| {status} | {amount} |")
    print("\n## Состояния объявлений\n\n| Listing status | Кол-во |\n|---|---:|")
    for status, amount in payload["listing_status"].items():
        if amount:
            print(f"| {status} | {amount} |")
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
    migrate = subparsers.add_parser("migrate-v2", help="однократно мигрировать v1 CSV в v2")
    migrate.add_argument("--check", action="store_true", help="проверить миграцию без записи")
    migrate.set_defaults(func=cmd_migrate_v2)
    backfill_sources = subparsers.add_parser("backfill-sources", help="создать source references из historical jobs")
    backfill_sources.add_argument("--check", action="store_true", help="проверить backfill без записи")
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
    report.set_defaults(func=cmd_report)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
