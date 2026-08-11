#!/usr/bin/env python3
"""CLI для data/jobs.csv. Использует только стандартную библиотеку Python."""

import argparse
import csv
import math
import os
import re
import sys
import tempfile
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "jobs.csv"
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


@dataclass
class AddPlan:
    rows: list
    row: dict
    warnings: list
    app_path: Path | None
    app_body: str | None


def today():
    return date.today().isoformat()


def die(message):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def read_csv():
    if not CSV_PATH.exists():
        die(f"не найден {CSV_PATH}")
    with CSV_PATH.open(newline="", encoding="utf-8") as file:
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


def ensure_valid(rows, emit_warnings=True):
    errors, warnings = validate_rows(rows)
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


def build_add_row(rows, values, duplicate_of=None):
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
    if duplicate_of:
        original = find(rows, duplicate_of)
        application_status, listing_status = "not_started", "unknown"
        decision_reason = "duplicate_listing"
        notes = f"duplicate of {original['id']}" + (f"; {clean_value(values.get('notes'))}" if values.get("notes") else "")
        first_party_verified, apply_verified = "unknown", "unknown"
    else:
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
        "verified_at": today() if verification_touched and not duplicate_of else "",
        "last_update": today(),
        "notes": notes,
    })
    return row


def should_create_application_card(row, no_file):
    return not no_file and not (
        row["application_status"] == "not_started" and row["decision_reason"]
    )


def render_application_card(row):
    app_path = APPS_DIR / f"{row['id']}-{slug(row['company'])}-{slug(row['role'])}.md"
    if app_path.exists():
        return app_path, None
    if not TEMPLATE_PATH.exists():
        die(f"не найден шаблон {TEMPLATE_PATH}")
    body = TEMPLATE_PATH.read_text(encoding="utf-8").replace("job-0000", row["id"]).replace("{{company}}", row["company"]).replace("{{role}}", row["role"])
    for key in (
        "company", "role", "original_url", "verified_at", "listing_status",
        "first_party_verified", "apply_verified",
    ):
        body = body.replace(f"{key}:", f"{key}: {row[key]}", 1)
    return app_path, body


def prepare_add(values, force=False, duplicate_of=None, no_file=False):
    rows = load()
    company = clean_value(values.get("company")).strip()
    role = clean_value(values.get("role")).strip()
    original_url = clean_value(values.get("original_url"))
    candidates = find_duplicate_candidates(rows, company, role, original_url)
    if candidates and not force and not duplicate_of:
        raise UnresolvedDuplicate(candidates)
    row = build_add_row(rows, values, duplicate_of=duplicate_of)
    new_rows = [*rows, row]
    app_path, app_body = (None, None)
    if should_create_application_card(row, no_file):
        app_path, app_body = render_application_card(row)
    return AddPlan(
        rows=new_rows,
        row=row,
        warnings=ensure_valid(new_rows, emit_warnings=False),
        app_path=app_path,
        app_body=app_body,
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
    except BaseException:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        if created_path:
            created_path.unlink(missing_ok=True)
        raise
    return created_path


def add_job(values, force=False, duplicate_of=None, no_file=False):
    plan = prepare_add(values, force=force, duplicate_of=duplicate_of, no_file=no_file)
    created_path = persist_add(plan)
    return {
        "job": plan.row,
        "warnings": plan.warnings,
        "application_path": created_path.relative_to(ROOT).as_posix() if created_path else None,
    }


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
        "location": args.location,
        "stack": args.stack,
        "salary": args.salary,
        "posted_at": args.posted_at,
        "found_at": args.found_at,
        "match_score": args.match_score,
        "decision_reason": args.decision_reason,
        "notes": args.notes,
    }


def cmd_add(args):
    try:
        result = add_job(
            add_values_from_args(args), force=args.force, duplicate_of=args.duplicate_of,
            no_file=args.no_file,
        )
    except UnresolvedDuplicate as error:
        print_duplicate_candidates(error.candidates)
        raise SystemExit(2)
    for warning in result["warnings"]:
        print(f"warn:  {warning}")
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
    row = find(rows, job_id)
    apply_job_changes(row, assignments, stage=stage)
    warnings = ensure_valid(rows, emit_warnings=False)
    save(rows)
    return {"job": row, "warnings": warnings}


def cmd_set(args):
    result = set_job(args.id, parse_field_assignments(args.field), stage=args.stage)
    for warning in result["warnings"]:
        print(f"warn:  {warning}")
    row = result["job"]
    print(f"{row['id']}  application_status={row['application_status']}  listing_status={row['listing_status']}  stage={row['stage_reached']}")


def cmd_validate(args):
    rows = load()
    errors, warnings = validate_rows(rows)
    for warning in warnings:
        print(f"warn:  {warning}")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    print(f"\nпроверено записей: {len(rows)}; ошибок: {len(errors)}; предупреждений: {len(warnings)}")
    if errors or (warnings and args.strict):
        raise SystemExit(1)


def cmd_dupes(args):
    rows = [row for row in load() if row["decision_reason"] != "duplicate_listing"]
    found = 0
    for index, first in enumerate(rows):
        for second in rows[index + 1:]:
            company_score = similarity(without_noise(first["company"], COMPANY_NOISE), without_noise(second["company"], COMPANY_NOISE))
            role_score = similarity(without_noise(first["role"], ROLE_NOISE), without_noise(second["role"], ROLE_NOISE))
            if company_score >= args.threshold and role_score >= args.role_threshold:
                found += 1
                print(
                    f"company {company_score:.2f} / role {role_score:.2f}\n"
                    f"  {first['id']}  {first['company']} — {first['role']}  [{first['application_status']}; {first['listing_status']}]\n"
                    f"  {second['id']}  {second['company']} — {second['role']}  [{second['application_status']}; {second['listing_status']}]\n"
                )
    print(f"пар-кандидатов: {found}")
    if found and args.fail:
        raise SystemExit(1)


def cmd_report(_args):
    rows = load()
    if not rows:
        print("jobs.csv пуст")
        return
    count = lambda predicate: sum(1 for row in rows if predicate(row))
    print(f"# Отчёт job-searcher — {today()}\n\nВсего записей: **{len(rows)}**\n\n## Состояния заявок\n\n| Application status | Кол-во |\n|---|---:|")
    for status in APPLICATION_STATUSES:
        if amount := count(lambda row, status=status: row["application_status"] == status):
            print(f"| {status} | {amount} |")
    print("\n## Состояния объявлений\n\n| Listing status | Кол-во |\n|---|---:|")
    for status in LISTING_STATUSES:
        if amount := count(lambda row, status=status: row["listing_status"] == status):
            print(f"| {status} | {amount} |")
    print("\n## Воронка (по stage_reached)\n\n| Стадия | Достигли | % от откликов |\n|---|---:|---:|")
    applied = count(lambda row: (row["stage_reached"] or "None") != "None")
    for stage in STAGES[1:]:
        amount = count(lambda row, stage=stage: row["stage_reached"] and STAGES.index(row["stage_reached"]) >= STAGES.index(stage))
        print(f"| {stage} | {amount} | {amount / applied * 100:.0f}% |" if applied else f"| {stage} | {amount} | — |")
    print("\n## Источники\n\n| Источник | Найдено | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|---:|")
    for source in SOURCES:
        found = count(lambda row, source=source: row["source"] == source)
        if found:
            applied_count = count(lambda row, source=source: row["source"] == source and row["applied_at"])
            responses = count(lambda row, source=source: row["source"] == source and row["response_at"])
            rate = f"{responses / applied_count * 100:.0f}%" if applied_count else "—"
            print(f"| {source} | {found} | {applied_count} | {responses} | {rate} |")
    print("\n## Конверсия по match_score\n\n| match_score | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|")
    for label, low, high in [("9–10", 9, 10), ("7–8.99", 7, 9), ("5–6.99", 5, 7), ("<5", 0, 5)]:
        def in_bucket(row, low=low, high=high):
            try:
                score = float(row["match_score"])
                return low <= score < high or (high == 10 and score == 10)
            except (TypeError, ValueError):
                return False
        applied_count = count(lambda row: in_bucket(row) and row["applied_at"])
        if applied_count:
            responses = count(lambda row: in_bucket(row) and row["response_at"])
            print(f"| {label} | {applied_count} | {responses} | {responses / applied_count * 100:.0f}% |")
    print("\n## Версии CV\n\n| cv_version | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|")
    for version in sorted({row["cv_version"] for row in rows if row["cv_version"]}):
        applied_count = count(lambda row, version=version: row["cv_version"] == version and row["applied_at"])
        if applied_count:
            responses = count(lambda row, version=version: row["cv_version"] == version and row["response_at"])
            print(f"| {version} | {applied_count} | {responses} | {responses / applied_count * 100:.0f}% |")
    unknown_cv_count = count(lambda row: row["applied_at"] and not (row["cv_version"] or "").strip())
    if unknown_cv_count:
        responses = count(lambda row: row["applied_at"] and not (row["cv_version"] or "").strip() and row["response_at"])
        print(f"| not recorded | {unknown_cv_count} | {responses} | {responses / unknown_cv_count * 100:.0f}% |")
    print("\n## Причины отсева\n\n| decision_reason | Кол-во |\n|---|---:|")
    for reason in REASONS:
        if amount := count(lambda row, reason=reason: row["decision_reason"] == reason):
            print(f"| {reason} | {amount} |")
    print("\n## Действия к исполнению\n")
    due = sorted((row for row in rows if row["next_action_date"] and row["next_action_date"] <= today()), key=lambda row: row["next_action_date"])
    if not due:
        print("Просроченных действий нет.")
    else:
        print("| Дата | id | Компания | Действие |\n|---|---|---|---|")
        for row in due:
            print(f"| {row['next_action_date']} | {row['id']} | {row['company']} | {row['next_action']} |")


def main():
    parser = JobsArgumentParser(prog="jobs.py", description="CLI для data/jobs.csv")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=JobsArgumentParser)
    add = subparsers.add_parser("add", help="добавить вакансию")
    add.add_argument("--company", required=True)
    add.add_argument("--role", required=True)
    add.add_argument("--source", required=True, choices=SOURCES)
    add.add_argument("--application-status", default="not_started", choices=ADD_APPLICATION_STATUSES)
    add.add_argument("--listing-status", default="unknown", choices=LISTING_STATUSES)
    add.add_argument("--first-party-verified", default="unknown", choices=VERIFICATION)
    add.add_argument("--apply-verified", default="unknown", choices=VERIFICATION)
    add.add_argument("--level", default="Unknown", choices=LEVELS)
    add.add_argument("--remote-policy", dest="remote_policy", default="Unclear", choices=REMOTE)
    for flag, destination in [
        ("--original-url", "original_url"), ("--source-url", "source_url"),
        ("--location", "location"), ("--stack", "stack"), ("--salary", "salary"),
        ("--posted-at", "posted_at"), ("--found-at", "found_at"),
        ("--match-score", "match_score"), ("--notes", "notes"),
    ]:
        add.add_argument(flag, dest=destination)
    add.add_argument("--decision-reason", dest="decision_reason", choices=REASONS)
    add.add_argument("--duplicate-of", dest="duplicate_of", metavar="JOB_ID")
    add.add_argument("--no-file", action="store_true")
    add.add_argument("--force", action="store_true")
    add.set_defaults(func=cmd_add)
    set_parser = subparsers.add_parser("set", help="изменить запись")
    set_parser.add_argument("id")
    set_parser.add_argument("field", nargs="*")
    set_parser.add_argument("--stage")
    set_parser.set_defaults(func=cmd_set)
    validate = subparsers.add_parser("validate", help="проверить целостность")
    validate.add_argument("--strict", action="store_true")
    validate.set_defaults(func=cmd_validate)
    migrate = subparsers.add_parser("migrate-v2", help="однократно мигрировать v1 CSV в v2")
    migrate.add_argument("--check", action="store_true", help="проверить миграцию без записи")
    migrate.set_defaults(func=cmd_migrate_v2)
    dupes = subparsers.add_parser("dupes", help="fuzzy-поиск дублей")
    dupes.add_argument("--threshold", type=float, default=.85)
    dupes.add_argument("--role-threshold", dest="role_threshold", type=float, default=.75)
    dupes.add_argument("--fail", action="store_true")
    dupes.set_defaults(func=cmd_dupes)
    report = subparsers.add_parser("report", help="markdown-отчёт в stdout")
    report.set_defaults(func=cmd_report)
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
