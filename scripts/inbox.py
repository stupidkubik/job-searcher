#!/usr/bin/env python3
"""Validate immutable raw JSONL discovery batches before ingestion."""

import argparse
import hashlib
import json
import re
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

try:  # Direct CLI execution places scripts/ on sys.path.
    from source_config import SourceConfigError, load_source_config
except ModuleNotFoundError:  # Unit tests may import this module as scripts.inbox.
    from scripts.source_config import SourceConfigError, load_source_config


REQUIRED_FIELDS = {
    "source",
    "source_job_id",
    "company",
    "role",
    "source_url",
    "application_url",
    "posted_at",
    "raw_location",
    "found_at",
}
OPTIONAL_FIELDS = {"payload"}
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")
HARD_FILTER_REASONS = {
    "geo_restriction",
    "work_authorization",
    "seniority_too_high",
    "seniority_too_low",
    "stack_mismatch",
    "role_not_frontend",
    "salary_too_low",
    "company_not_interesting",
}


def valid_http_url(value):
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def valid_date(value):
    if not DATE_PATTERN.fullmatch(value):
        return False
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        return False
    return True


def validate_record(record, line_number, configured_sources):
    errors = []
    prefix = f"line {line_number}"
    if not isinstance(record, dict):
        return [f"{prefix}: ожидается JSON object"]
    unknown = sorted(set(record) - REQUIRED_FIELDS - OPTIONAL_FIELDS)
    if unknown:
        errors.append(f"{prefix}: неизвестные поля: {', '.join(unknown)}")
    for field in sorted(REQUIRED_FIELDS):
        value = record.get(field)
        if not isinstance(value, str) or not value.strip():
            errors.append(f"{prefix}: {field} должен быть непустой строкой")
    source = record.get("source")
    if isinstance(source, str) and source.strip():
        source_config = configured_sources.get(source)
        if source_config is None:
            errors.append(f"{prefix}: source={source!r} отсутствует в config/sources.toml")
        elif not source_config["enabled"]:
            errors.append(f"{prefix}: source={source!r} выключен в config/sources.toml")
    for field in ("source_url", "application_url"):
        value = record.get(field)
        if isinstance(value, str) and value.strip() and not valid_http_url(value):
            errors.append(f"{prefix}: {field} должен быть абсолютным http(s) URL")
    for field in ("posted_at", "found_at"):
        value = record.get(field)
        if isinstance(value, str) and value.strip() and not valid_date(value):
            errors.append(f"{prefix}: {field} должен иметь формат YYYY-MM-DD")
    if "payload" in record and not isinstance(record["payload"], dict):
        errors.append(f"{prefix}: payload должен быть JSON object")
    if isinstance(record.get("payload"), dict) and "hard_filter_reason" in record["payload"]:
        reason = record["payload"]["hard_filter_reason"]
        if reason not in HARD_FILTER_REASONS:
            errors.append(f"{prefix}: payload.hard_filter_reason не входит в canonical enum")
    return errors


def load_batch(path):
    """Read a raw batch without changing it and retain validation per JSONL line."""
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as error:
        return {
            "batch_id": None,
            "entries": [],
            "errors": [f"не удалось прочитать {path}: {error}"],
        }
    batch_id = "sha256:" + hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        return {
            "batch_id": batch_id,
            "entries": [],
            "errors": [f"input не UTF-8: {error}"],
        }
    try:
        configured_sources = load_source_config()
    except SourceConfigError as error:
        return {
            "batch_id": batch_id,
            "entries": [],
            "errors": [f"source registry invalid: {error}"],
        }

    entries = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            entries.append(
                {
                    "line": line_number,
                    "record": None,
                    "errors": [f"line {line_number}: пустая строка не является JSON object"],
                }
            )
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            entries.append(
                {
                    "line": line_number,
                    "record": None,
                    "errors": [f"line {line_number}: некорректный JSON: {error.msg}"],
                }
            )
            continue
        entries.append(
            {
                "line": line_number,
                "record": record,
                "errors": validate_record(record, line_number, configured_sources),
            }
        )
    return {"batch_id": batch_id, "entries": entries, "errors": []}


def validate_batch(path):
    batch = load_batch(path)
    errors = [*batch["errors"], *(error for entry in batch["entries"] for error in entry["errors"])]
    return {
        "ok": not errors,
        "command": "validate",
        "batch_id": batch["batch_id"],
        "records": len(batch["entries"]),
        "errors": errors,
    }


def main():
    parser = argparse.ArgumentParser(description="Проверить raw JSONL batch перед ingest")
    subparsers = parser.add_subparsers(dest="command", required=True)
    validate = subparsers.add_parser("validate", help="проверить неизменяемый JSONL batch")
    validate.add_argument("path", type=Path)
    args = parser.parse_args()
    result = validate_batch(args.path)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not result["ok"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
