"""Dataset I/O, integrity checks, and duplicate detection.

docs/agent-write-path-plan-2026-09-07.md, Э10. Everything that reads
data/jobs.csv and data/job_sources.csv, checks them for internal
consistency, or looks for a possible duplicate lives here; write.py, render.py
and ingest.py all build on top of it.
"""

import csv
import math
import os
import re
import tempfile
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

try:  # Direct CLI execution places scripts/ on sys.path.
    from tracker_time import business_date
except ModuleNotFoundError:  # Unit tests may import this module as scripts.tracker_validate.
    from scripts.tracker_time import business_date

try:  # Direct CLI execution places scripts/ on sys.path.
    from tracker_paths import PATHS
    from tracker_schema import (
        DATE_FIELDS,
        ENUMS,
        FIELDS,
        GHOST_AFTER_DAYS,
        IN_PROGRESS_APPLICATION_STATUSES,
        JOB_SOURCE_FIELDS,
        NEEDS_APPLIED_AT,
        PRE_APPLICATION_REASONS,
        PRE_APPLICATION_STATUSES,
        REQUIRED,
        RESPONDED_APPLICATION_STATUSES,
        SOURCES,
        ValidationError,
        die,
        norm,
        valid_http_url,
    )
except ModuleNotFoundError:  # Unit tests may import this module as scripts.tracker_validate.
    from scripts.tracker_paths import PATHS
    from scripts.tracker_schema import (
        DATE_FIELDS,
        ENUMS,
        FIELDS,
        GHOST_AFTER_DAYS,
        IN_PROGRESS_APPLICATION_STATUSES,
        JOB_SOURCE_FIELDS,
        NEEDS_APPLIED_AT,
        PRE_APPLICATION_REASONS,
        PRE_APPLICATION_STATUSES,
        REQUIRED,
        RESPONDED_APPLICATION_STATUSES,
        SOURCES,
        ValidationError,
        die,
        norm,
        valid_http_url,
    )


def read_csv():
    if not PATHS.csv_path.exists():
        die(f"не найден {PATHS.csv_path}")
    with PATHS.csv_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames, list(reader)


def read_job_sources_csv():
    if not PATHS.job_sources_path.exists():
        die(f"не найден {PATHS.job_sources_path}")
    with PATHS.job_sources_path.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        return reader.fieldnames, list(reader)


def load():
    header, rows = read_csv()
    if header != FIELDS:
        die(
            "заголовок jobs.csv не совпадает со схемой v2; для v1 используйте scripts/maintenance/migrate_v2.py"
        )
    return rows


def load_job_sources(allow_missing=False):
    if allow_missing and not PATHS.job_sources_path.exists():
        return []
    header, rows = read_job_sources_csv()
    if header != JOB_SOURCE_FIELDS:
        die("заголовок job_sources.csv не совпадает со схемой; см. data/schema.md")
    return rows


def save(rows: list) -> None:
    """Атомарно заменяет CSV, чтобы ошибка не оставила обрезанный файл."""
    if (PATHS.root / "data/application_events").is_dir():
        raise RuntimeError("direct CSV save is disabled after event-ledger cutover; use the dataset transaction")
    descriptor, temporary_name = tempfile.mkstemp(prefix="jobs-", suffix=".csv", dir=PATHS.csv_path.parent)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: row.get(key) or "" for key in FIELDS} for row in rows)
        os.replace(temporary_name, PATHS.csv_path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def save_job_sources(rows: list) -> None:
    if (PATHS.root / "data/application_events").is_dir():
        raise RuntimeError("direct source save is disabled after event-ledger cutover; use the dataset transaction")
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="job-sources-", suffix=".csv", dir=PATHS.job_sources_path.parent
    )
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=JOB_SOURCE_FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: row.get(key) or "" for key in JOB_SOURCE_FIELDS} for row in rows)
        os.replace(temporary_name, PATHS.job_sources_path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


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
    return urlunsplit(
        (parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(query), "")
    )


COMPANY_NOISE = {
    "ltd",
    "limited",
    "inc",
    "incorporated",
    "llc",
    "llp",
    "plc",
    "gmbh",
    "ag",
    "bv",
    "nv",
    "ab",
    "oy",
    "oyj",
    "as",
    "sa",
    "sas",
    "srl",
    "spa",
    "doo",
    "ooo",
    "corp",
    "corporation",
    "co",
    "company",
    "group",
    "holding",
    "holdings",
    "the",
}

ROLE_NOISE = {
    "developer",
    "engineer",
    "software",
    "web",
    "senior",
    "junior",
    "middle",
    "mid",
    "associate",
    "graduate",
    "intern",
    "internship",
    "remote",
    "m",
    "f",
    "d",
    "x",
    "the",
    "and",
}

PLACEHOLDER_COMPANY_RE = re.compile(r"^(undisclosed|unknown|confidential|n/?a)\b", re.IGNORECASE)


def without_noise(text, noise):
    normalized = norm(text)
    result = " ".join(word for word in normalized.split() if word not in noise)
    return result or normalized


def similarity(first, second):
    return SequenceMatcher(None, first, second).ratio()


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
                    warnings.append(
                        f"строка {line}: {identifier}: {key}={value} в будущем — опечатка в годе?"
                    )
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
            error(
                line,
                f"{identifier}: cover_letter должен быть 'no' или путём (например cv/cover-letters/...), получено {cover_letter!r}",
            )
        application_status = row.get("application_status") or ""
        listing_status = row.get("listing_status") or ""
        reason = row.get("decision_reason") or ""
        verified_at = row.get("verified_at") or ""
        first_party_verified = row.get("first_party_verified") or ""
        apply_verified = row.get("apply_verified") or ""
        if application_status in NEEDS_APPLIED_AT and not (row.get("applied_at") or "").strip():
            error(line, f"{identifier}: application_status={application_status} требует applied_at")
        if (
            application_status in RESPONDED_APPLICATION_STATUSES
            and not (row.get("response_at") or "").strip()
        ):
            error(line, f"{identifier}: application_status={application_status} требует response_at")
        if (
            application_status in {"not_started", "reviewing", "apply"}
            and (row.get("applied_at") or "").strip()
        ):
            error(line, f"{identifier}: application_status={application_status} несовместим с applied_at")
        if application_status == "withdrawn" and not reason:
            error(line, f"{identifier}: application_status=withdrawn требует decision_reason")
        if reason == "other" and not (row.get("notes") or "").strip():
            error(line, f"{identifier}: decision_reason=other требует пояснения в notes")
        if reason and application_status in IN_PROGRESS_APPLICATION_STATUSES:
            error(
                line,
                f"{identifier}: decision_reason={reason} несовместим с application_status={application_status}; закрытое решение хранится как not_started",
            )
        elif reason in PRE_APPLICATION_REASONS and application_status != "not_started":
            error(line, f"{identifier}: decision_reason={reason} требует application_status=not_started")
        if reason == "closed_before_application":
            if listing_status != "closed":
                error(line, f"{identifier}: closed_before_application требует listing_status=closed")
            if (row.get("applied_at") or "").strip():
                error(line, f"{identifier}: closed_before_application несовместим с applied_at")
        if listing_status == "closed" and application_status in PRE_APPLICATION_STATUSES:
            if application_status != "not_started":
                error(
                    line,
                    f"{identifier}: listing_status=closed до отклика требует application_status=not_started",
                )
            elif reason != "closed_before_application":
                error(
                    line,
                    f"{identifier}: closed before application требует decision_reason=closed_before_application",
                )
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
        if row.get("stage_reached") == "Offer" and application_status not in {
            "offer",
            "rejected",
            "withdrawn",
        }:
            warnings.append(
                f"строка {line}: {identifier}: stage=Offer при application_status={application_status}"
            )
        try:
            if (
                row.get("response_at")
                and row.get("applied_at")
                and datetime.strptime(row["response_at"], "%Y-%m-%d")
                < datetime.strptime(row["applied_at"], "%Y-%m-%d")
            ):
                error(line, f"{identifier}: response_at раньше applied_at")
        except ValueError:
            pass
        if "\n" in (row.get("notes") or ""):
            error(line, f"{identifier}: перевод строки в notes; длинный текст → applications/{identifier}.md")
    for canonical, entries in urls.items():
        if (
            len(entries) > 1
            and len([row for _, row in entries if row.get("decision_reason") != "duplicate_listing"]) != 1
        ):
            labels = ", ".join(f"{row['id']}@{line}" for line, row in entries)
            errors.append(
                f"canonical original_url={canonical!r}: ожидается ровно одна оригинальная запись, получено: {labels}"
            )
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
            notices.append(
                f"строка {line}: {identifier}: {days} дней без ответа → application_status=ghosted?"
            )
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
                    warnings.append(
                        f"job_sources.csv:{line}: {identifier}: found_at={found_at} в будущем — опечатка в годе?"
                    )
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
                error(
                    line,
                    f"{identifier}: дубль source_url для той же вакансии (уже в строке {source_urls[key]})",
                )
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
        raise ValidationError(
            "dataset failed validation after this write",
            cli_hint_ru="изменение отклонено:\n  " + "\n  ".join(errors),
        )
    if emit_warnings:
        for warning in warnings:
            print(f"warn:  {warning}")
    return warnings


def find_duplicate_candidates(rows, company, role, original_url):
    """Each hit carries a reason in both languages (docs/agent-write-path-plan-2026-09-07.md, Э8):
    reason_ru for jobs.py's own human CLI output, reason_en for agent_operations'
    connector-facing conflict result. Neither addressee sees the other's text."""
    hits = {}
    if original_url:
        for row in rows:
            if row["original_url"] and norm_url(row["original_url"]) == norm_url(original_url):
                hits[row["id"]] = (row, "совпадение canonical original_url", "canonical original_url matches")
    if not PLACEHOLDER_COMPANY_RE.match(company.strip()):
        company_norm, role_norm = without_noise(company, COMPANY_NOISE), without_noise(role, ROLE_NOISE)
        for row in rows:
            if PLACEHOLDER_COMPANY_RE.match(row["company"].strip()):
                continue
            company_score = similarity(company_norm, without_noise(row["company"], COMPANY_NOISE))
            role_score = similarity(role_norm, without_noise(row["role"], ROLE_NOISE))
            if company_score >= 0.85 and role_score >= 0.75:
                hits.setdefault(
                    row["id"],
                    (
                        row,
                        f"похоже: company {company_score:.2f}, role {role_score:.2f}",
                        f"looks similar: company {company_score:.2f}, role {role_score:.2f}",
                    ),
                )
    return hits


def print_duplicate_candidates(candidates):
    print("возможные дубли:")
    for row, reason_text, _reason_en in candidates.values():
        print(
            f"  {row['id']}  {row['company']} — {row['role']}  [{row['application_status']}; {row['listing_status']}]  ({reason_text})"
        )
    print("\nэто дубль -> повторите с --duplicate-of job-NNNN\nэто другая вакансия -> повторите с --force")


def find_fuzzy_duplicates(rows, company_threshold, role_threshold):
    candidates = []
    for index, first in enumerate(rows):
        for second in rows[index + 1 :]:
            company_score = similarity(
                without_noise(first["company"], COMPANY_NOISE),
                without_noise(second["company"], COMPANY_NOISE),
            )
            role_score = similarity(
                without_noise(first["role"], ROLE_NOISE), without_noise(second["role"], ROLE_NOISE)
            )
            if company_score >= company_threshold and role_score >= role_threshold:
                candidates.append(
                    {
                        "company_similarity": round(company_score, 4),
                        "role_similarity": round(role_score, 4),
                        "first": first,
                        "second": second,
                    }
                )
    return candidates
