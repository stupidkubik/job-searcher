#!/usr/bin/env python3
"""Fetch Himalayas discovery results into one immutable raw JSONL batch.

This adapter deliberately stops at discovery. It never calls ``jobs.py ingest``
and it never concludes that an API listing is open or that an Apply link works.
"""

import argparse
import json
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

try:  # Direct CLI execution places scripts/ on sys.path.
    from source_config import SourceConfigError, load_source_config
except ModuleNotFoundError:  # Unit tests may import this module as scripts.import_himalayas.
    from scripts.source_config import SourceConfigError, load_source_config


ROOT = Path(__file__).resolve().parent.parent
INBOX_DIR = ROOT / "data" / "inbox"
SOURCE_NAME = "Himalayas"
REQUEST_TIMEOUT_SECONDS = 20
RETRY_DELAYS_SECONDS = (1, 2)


class HimalayasImportError(ValueError):
    pass


def die(message):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def is_http_url(value):
    if not isinstance(value, str):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def api_date(value):
    """Accept the documented Unix timestamp plus legacy ISO/date representations."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        timestamp = float(value)
        if timestamp > 100_000_000_000:
            timestamp /= 1000
        try:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).date()
        except (OverflowError, OSError, ValueError) as error:
            raise HimalayasImportError(f"некорректный Unix timestamp {value!r}") from error
    if isinstance(value, str) and value.strip():
        raw = value.strip()
        try:
            return date.fromisoformat(raw)
        except ValueError:
            try:
                return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
            except ValueError as error:
                raise HimalayasImportError(f"некорректная дата API {value!r}") from error
    raise HimalayasImportError(f"некорректная дата API {value!r}")


def raw_location(value):
    if not isinstance(value, list):
        raise HimalayasImportError("locationRestrictions должен быть array")
    if not value:
        return "Worldwide"
    locations = []
    for item in value:
        if isinstance(item, str) and item.strip():
            locations.append(item.strip())
        elif isinstance(item, dict) and isinstance(item.get("name"), str) and item["name"].strip():
            locations.append(item["name"].strip())
        else:
            raise HimalayasImportError("locationRestrictions содержит запись без названия")
    return "; ".join(locations)


def required_string(job, field):
    value = job.get(field)
    if not isinstance(value, str) or not value.strip():
        raise HimalayasImportError(f"API job: {field} должен быть непустой строкой")
    return value.strip()


def normalize_job(job, found_at):
    """Project one Himalayas API record into the immutable raw inbox contract."""
    if not isinstance(job, dict):
        raise HimalayasImportError("API jobs[] должен содержать только JSON objects")
    guid = required_string(job, "guid")
    application_url = required_string(job, "applicationLink")
    source_url = guid if is_http_url(guid) else application_url
    if not is_http_url(source_url):
        raise HimalayasImportError("API job не содержит пригодный http(s) guid/applicationLink")
    if not is_http_url(application_url):
        raise HimalayasImportError("API applicationLink должен быть абсолютным http(s) URL")
    return {
        "source": SOURCE_NAME,
        "source_job_id": guid,
        "company": required_string(job, "companyName"),
        "role": required_string(job, "title"),
        "source_url": source_url,
        # Candidate URL only. Its status and first-party nature are verified later.
        "application_url": application_url,
        "posted_at": api_date(job.get("pubDate")).isoformat(),
        "raw_location": raw_location(job.get("locationRestrictions")),
        "found_at": found_at.isoformat(),
        "payload": {"himalayas": job},
    }


def load_himalayas_settings(config_path=None):
    try:
        sources = load_source_config(config_path) if config_path else load_source_config()
    except SourceConfigError as error:
        raise HimalayasImportError(f"source registry invalid: {error}") from error
    source = sources.get(SOURCE_NAME)
    if source is None:
        raise HimalayasImportError(f"source {SOURCE_NAME} отсутствует в config/sources.toml")
    if not source["enabled"]:
        raise HimalayasImportError(f"source {SOURCE_NAME} выключен в config/sources.toml")
    if source["type"] != "api":
        raise HimalayasImportError(f"source {SOURCE_NAME} должен иметь type=api")
    for field in ("search_url", "narrow_queries", "broad_queries"):
        if field not in source:
            raise HimalayasImportError(f"source {SOURCE_NAME}: отсутствует {field}")
    return source


def select_run(settings, broad):
    if broad:
        return {
            "selection": "broad",
            "queries": settings["broad_queries"],
            "cadence_hours": settings["broad_cadence_hours"],
            "max_age_days": settings["fallback_max_age_days"],
        }
    return {
        "selection": "narrow",
        "queries": settings["narrow_queries"],
        "cadence_hours": settings["cadence_hours"],
        "max_age_days": settings["max_age_days"],
    }


def request_url(search_url, query, settings):
    parameters = {
        "q": query,
        "seniority": ",".join(settings["seniority"]),
        "employment_type": ",".join(settings["employment_types"]),
        "sort": "recent",
    }
    return f"{search_url}?{urlencode(parameters)}"


def fetch_json(url, *, urlopen_func=urlopen, sleep_func=time.sleep):
    """Fetch one API response with bounded retry for temporary HTTP/network errors."""
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "job-tracker-v2/1.0"})
    last_error = None
    for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
        try:
            with urlopen_func(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read()
        except HTTPError as error:
            last_error = f"HTTP {error.code}: {error.reason}"
            retryable = error.code == 429 or 500 <= error.code < 600
            error.close()
        except (URLError, TimeoutError, OSError) as error:
            last_error = f"network error: {error}"
            retryable = True
        else:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise HimalayasImportError(f"некорректный JSON от Himalayas: {error}") from error
            if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
                raise HimalayasImportError("ответ Himalayas должен быть object с jobs array")
            return payload
        if not retryable or attempt == len(RETRY_DELAYS_SECONDS):
            break
        sleep_func(RETRY_DELAYS_SECONDS[attempt])
    raise HimalayasImportError(f"не удалось запросить Himalayas после {attempt + 1} попыток: {last_error}")


def collect_records(settings, run, *, today_value=None, fetch=fetch_json):
    """Fetch selected queries, retain all raw fields and locally enforce max age."""
    today_value = today_value or datetime.now(timezone.utc).date()
    oldest = date.fromordinal(today_value.toordinal() - run["max_age_days"])
    records, errors, seen_guids = [], [], set()
    summary = {
        "queries": len(run["queries"]),
        "fetched": 0,
        "outside_age_window": 0,
        "duplicates": 0,
        "records": 0,
    }
    for query in run["queries"]:
        url = request_url(settings["search_url"], query, settings)
        response = fetch(url)
        for job in response["jobs"]:
            summary["fetched"] += 1
            try:
                posted_at = api_date(job.get("pubDate")) if isinstance(job, dict) else None
                if posted_at is None:
                    raise HimalayasImportError("API jobs[] должен содержать JSON object")
                if posted_at < oldest:
                    summary["outside_age_window"] += 1
                    continue
                record = normalize_job(job, today_value)
            except HimalayasImportError as error:
                errors.append(f"query {query!r}: {error}")
                continue
            if record["source_job_id"] in seen_guids:
                summary["duplicates"] += 1
                continue
            seen_guids.add(record["source_job_id"])
            records.append(record)
    summary["records"] = len(records)
    return records, summary, errors


def validate_output_path(path):
    resolved = Path(path).resolve()
    inbox = INBOX_DIR.resolve()
    try:
        resolved.relative_to(inbox)
    except ValueError as error:
        raise HimalayasImportError(f"--output должен находиться в {INBOX_DIR}") from error
    if resolved.suffix != ".jsonl":
        raise HimalayasImportError("--output должен иметь расширение .jsonl")
    if resolved.exists():
        raise HimalayasImportError(f"raw batch уже существует и immutable: {resolved}")
    return resolved


def write_jsonl(path, records):
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8", newline="\n") as file:
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
                file.write("\n")
    except OSError as error:
        raise HimalayasImportError(f"не удалось записать raw batch {path}: {error}") from error


def main():
    parser = argparse.ArgumentParser(description="Сохранить Himalayas discovery results как raw JSONL")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--narrow", action="store_true", help="registry narrow queries (default)")
    selection.add_argument("--broad", action="store_true", help="registry broad queries and fallback age window")
    parser.add_argument("--output", type=Path, help="новый immutable .jsonl внутри data/inbox/")
    parser.add_argument("--dry-run", action="store_true", help="запросить и классифицировать без записи raw batch")
    args = parser.parse_args()
    if not args.dry_run and args.output is None:
        die("--output обязателен без --dry-run")
    if args.dry_run and args.output is not None:
        die("--output нельзя указывать вместе с --dry-run")
    try:
        settings = load_himalayas_settings()
        run = select_run(settings, broad=args.broad)
        records, summary, errors = collect_records(settings, run)
        output = None
        if not args.dry_run and not errors:
            output_path = validate_output_path(args.output)
            write_jsonl(output_path, records)
            output = output_path.relative_to(ROOT.resolve()).as_posix()
    except HimalayasImportError as error:
        die(str(error))
    result = {
        "ok": not errors,
        "command": "import_himalayas",
        "mode": "dry_run" if args.dry_run else "write_raw_batch",
        "selection": run["selection"],
        "cadence_hours": run["cadence_hours"],
        "max_age_days": run["max_age_days"],
        "geo_policy": settings["geo"],
        "summary": summary,
        "output": output,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if errors:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
