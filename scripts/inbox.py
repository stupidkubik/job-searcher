#!/usr/bin/env python3
"""Validate immutable raw JSONL discovery batches before ingestion."""

import argparse
import hashlib
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from urllib.parse import urlsplit

from source_config import SourceConfigError, load_source_config


REQUIRED_FIELDS = {
    "source", "source_job_id", "company", "role", "source_url",
    "application_url", "posted_at", "raw_location", "found_at",
}
OPTIONAL_FIELDS = {"payload"}
DATE_PATTERN = re.compile(r"\d{4}-\d{2}-\d{2}\Z")


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
    return errors


def validate_batch(path):
    path = Path(path)
    try:
        raw = path.read_bytes()
    except OSError as error:
        return {
            "ok": False,
            "command": "validate",
            "batch_id": None,
            "records": 0,
            "errors": [f"не удалось прочитать {path}: {error}"],
        }
    batch_id = "sha256:" + hashlib.sha256(raw).hexdigest()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as error:
        return {
            "ok": False,
            "command": "validate",
            "batch_id": batch_id,
            "records": 0,
            "errors": [f"input не UTF-8: {error}"],
        }
    try:
        configured_sources = load_source_config()
    except SourceConfigError as error:
        return {
            "ok": False,
            "command": "validate",
            "batch_id": batch_id,
            "records": 0,
            "errors": [f"source registry invalid: {error}"],
        }

    errors, records = [], 0
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            errors.append(f"line {line_number}: пустая строка не является JSON object")
            continue
        records += 1
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            errors.append(f"line {line_number}: некорректный JSON: {error.msg}")
            continue
        errors.extend(validate_record(record, line_number, configured_sources))
    return {
        "ok": not errors,
        "command": "validate",
        "batch_id": batch_id,
        "records": records,
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
