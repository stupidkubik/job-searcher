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
try:
    from tracker_time import BUSINESS_TIMEZONE_NAME, business_date, utc_instant, utc_timestamp
except ModuleNotFoundError:
    from scripts.tracker_time import BUSINESS_TIMEZONE_NAME, business_date, utc_instant, utc_timestamp


ROOT = Path(__file__).resolve().parent.parent
INBOX_DIR = ROOT / "data" / "inbox"
SOURCE_NAME = "Himalayas"
REQUEST_TIMEOUT_SECONDS = 20
RETRY_DELAYS_SECONDS = (1, 2)
MAX_PAGES_PER_PASS = 50

# `locationRestrictions` contains either a country object (normally with alpha2)
# or a display name. Keep the Europe pass local: the documented search endpoint
# has country and worldwide filters, but no Europe-region filter.
EUROPE_ALPHA2 = frozenset(
    {
        "AD",
        "AL",
        "AM",
        "AT",
        "AX",
        "AZ",
        "BA",
        "BE",
        "BG",
        "BY",
        "CH",
        "CY",
        "CZ",
        "DE",
        "DK",
        "EE",
        "ES",
        "FI",
        "FO",
        "FR",
        "GB",
        "GE",
        "GG",
        "GI",
        "GR",
        "HR",
        "HU",
        "IE",
        "IM",
        "IS",
        "IT",
        "JE",
        "KZ",
        "LI",
        "LT",
        "LU",
        "LV",
        "MC",
        "MD",
        "ME",
        "MK",
        "MT",
        "NL",
        "NO",
        "PL",
        "PT",
        "RO",
        "RS",
        "RU",
        "SE",
        "SI",
        "SJ",
        "SK",
        "SM",
        "TR",
        "UA",
        "VA",
        "XK",
    }
)
EUROPE_LOCATION_NAMES = frozenset(
    {
        "andorra",
        "armenia",
        "austria",
        "azerbaijan",
        "belarus",
        "belgium",
        "bosnia and herzegovina",
        "bulgaria",
        "croatia",
        "cyprus",
        "czech republic",
        "czechia",
        "denmark",
        "estonia",
        "finland",
        "france",
        "georgia",
        "germany",
        "greece",
        "hungary",
        "iceland",
        "ireland",
        "italy",
        "kazakhstan",
        "kosovo",
        "latvia",
        "liechtenstein",
        "lithuania",
        "luxembourg",
        "malta",
        "moldova",
        "monaco",
        "montenegro",
        "netherlands",
        "north macedonia",
        "norway",
        "poland",
        "portugal",
        "romania",
        "russia",
        "san marino",
        "serbia",
        "slovakia",
        "slovenia",
        "spain",
        "sweden",
        "switzerland",
        "turkey",
        "ukraine",
        "united kingdom",
        "vatican city",
        "europe",
        "european union",
        "eu",
        "eea",
        "european economic area",
        "emea",
    }
)
GEO_PASSES = {
    "serbia": "Serbia",
    "worldwide": "Worldwide",
    "europe": "Europe",
}


class HimalayasImportError(ValueError):
    pass


class HimalayasRunError(HimalayasImportError):
    def __init__(self, message, outcome):
        super().__init__(message)
        self.outcome = outcome


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


def configured_geo_passes(settings):
    """Return the configured discovery passes in registry order."""
    passes = []
    for value in settings["geo"]:
        key = value.strip().casefold()
        if key not in GEO_PASSES:
            raise HimalayasImportError(
                f"source {SOURCE_NAME}: unsupported geo policy {value!r}; "
                "supported values: Serbia, worldwide, Europe"
            )
        geo = GEO_PASSES[key]
        if geo not in passes:
            passes.append(geo)
    if not passes:
        raise HimalayasImportError(f"source {SOURCE_NAME}: geo policy must not be empty")
    return passes


def request_url(search_url, query, settings, *, geo, page):
    parameters = {
        "q": query,
        "seniority": ",".join(settings["seniority"]),
        "employment_type": ",".join(settings["employment_types"]),
        "sort": "recent",
        "page": page,
    }
    if geo == "Serbia":
        parameters.update({"country": "Serbia", "exclude_worldwide": "true"})
    elif geo == "Worldwide":
        parameters["worldwide"] = "true"
    elif geo != "Europe":
        raise HimalayasImportError(f"unknown Himalayas geo pass {geo!r}")
    return f"{search_url}?{urlencode(parameters)}"


def europe_location_restriction(job):
    """Whether one API location restriction allows work from Europe.

    Empty restrictions mean worldwide and are intentionally handled by the
    Worldwide API pass rather than duplicated in this locally-filtered pass.
    """
    restrictions = job.get("locationRestrictions") if isinstance(job, dict) else None
    if not isinstance(restrictions, list):
        raise HimalayasImportError("locationRestrictions должен быть array")
    for restriction in restrictions:
        if isinstance(restriction, dict):
            alpha2 = restriction.get("alpha2")
            if isinstance(alpha2, str) and alpha2.strip().upper() in EUROPE_ALPHA2:
                return True
            name = restriction.get("name")
        elif isinstance(restriction, str):
            name = restriction
        else:
            raise HimalayasImportError("locationRestrictions содержит запись без названия")
        if isinstance(name, str) and name.strip().casefold() in EUROPE_LOCATION_NAMES:
            return True
    return False


def has_next_page(response, page):
    """Use documented response metadata; never silently truncate a search."""
    total_count, limit = response.get("totalCount"), response.get("limit")
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (total_count, limit)):
        raise HimalayasImportError(
            "Himalayas response must include integer totalCount and limit for pagination"
        )
    if limit <= 0 or total_count < 0:
        raise HimalayasImportError(
            "Himalayas pagination metadata must use non-negative totalCount and positive limit"
        )
    return page * limit < total_count


def fetch_json(url, *, urlopen_func=urlopen, sleep_func=time.sleep):
    """Fetch one API response with bounded retry for temporary HTTP/network errors."""
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "job-tracker-v2/1.0"})
    last_error = None
    last_outcome = "request_failed"
    for attempt in range(len(RETRY_DELAYS_SECONDS) + 1):
        try:
            with urlopen_func(request, timeout=REQUEST_TIMEOUT_SECONDS) as response:
                raw = response.read()
        except HTTPError as error:
            last_error = f"HTTP {error.code}: {error.reason}"
            last_outcome = {
                401: "auth_required",
                403: "blocked",
                429: "rate_limited",
            }.get(error.code, "request_failed")
            retryable = error.code == 429 or 500 <= error.code < 600
            error.close()
        except (URLError, TimeoutError, OSError) as error:
            last_error = f"network error: {error}"
            last_outcome = "request_failed"
            retryable = True
        else:
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as error:
                raise HimalayasRunError(f"некорректный JSON от Himalayas: {error}", "parse_error") from error
            if not isinstance(payload, dict) or not isinstance(payload.get("jobs"), list):
                raise HimalayasRunError("ответ Himalayas должен быть object с jobs array", "parse_error")
            return payload
        if not retryable or attempt == len(RETRY_DELAYS_SECONDS):
            break
        sleep_func(RETRY_DELAYS_SECONDS[attempt])
    raise HimalayasRunError(
        f"не удалось запросить Himalayas после {attempt + 1} попыток: {last_error}",
        last_outcome,
    )


def collect_records(settings, run, *, today_value=None, fetch=fetch_json):
    """Fetch every configured query/geo page and retain qualifying raw records."""
    today_value = today_value or business_date()
    oldest = date.fromordinal(today_value.toordinal() - run["max_age_days"])
    geo_passes = configured_geo_passes(settings)
    records, errors, seen_guids = [], [], set()
    summary = {
        "queries": len(run["queries"]),
        "geo_passes": len(geo_passes),
        "pages": 0,
        "fetched": 0,
        "outside_geo_policy": 0,
        "outside_age_window": 0,
        "duplicates": 0,
        "records": 0,
    }
    for query in run["queries"]:
        for geo in geo_passes:
            page = 1
            while True:
                url = request_url(settings["search_url"], query, settings, geo=geo, page=page)
                response = fetch(url)
                summary["pages"] += 1
                for job in response["jobs"]:
                    summary["fetched"] += 1
                    try:
                        if geo == "Europe" and not europe_location_restriction(job):
                            summary["outside_geo_policy"] += 1
                            continue
                        posted_at = api_date(job.get("pubDate")) if isinstance(job, dict) else None
                        if posted_at is None:
                            raise HimalayasImportError("API jobs[] должен содержать JSON object")
                        if posted_at < oldest:
                            summary["outside_age_window"] += 1
                            continue
                        record = normalize_job(job, today_value)
                    except HimalayasImportError as error:
                        errors.append(f"query {query!r}, geo {geo}, page {page}: {error}")
                        continue
                    if record["source_job_id"] in seen_guids:
                        summary["duplicates"] += 1
                        continue
                    seen_guids.add(record["source_job_id"])
                    records.append(record)
                if not has_next_page(response, page):
                    break
                if page >= MAX_PAGES_PER_PASS:
                    raise HimalayasImportError(
                        f"query {query!r}, geo {geo}: превышен предел {MAX_PAGES_PER_PASS} страниц "
                        "на один проход; проверить totalCount/limit в ответе Himalayas"
                    )
                page += 1
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


def write_artifact(path, payload):
    resolved = Path(path).resolve()
    if resolved.exists():
        raise HimalayasImportError(f"discovery artifact уже существует и immutable: {resolved}")
    try:
        resolved.parent.mkdir(parents=True, exist_ok=True)
        with resolved.open("x", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, indent=2, sort_keys=True)
            file.write("\n")
    except OSError as error:
        raise HimalayasImportError(f"не удалось записать discovery artifact {resolved}: {error}") from error
    return resolved


def main():
    parser = argparse.ArgumentParser(description="Сохранить Himalayas discovery results как raw JSONL")
    selection = parser.add_mutually_exclusive_group()
    selection.add_argument("--narrow", action="store_true", help="registry narrow queries (default)")
    selection.add_argument(
        "--broad", action="store_true", help="registry broad queries and fallback age window"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--output", type=Path, help="новый immutable .jsonl внутри data/inbox/")
    mode.add_argument("--artifact", type=Path, help="новый read-only discovery artifact без canonical write")
    mode.add_argument(
        "--dry-run", action="store_true", help="запросить и классифицировать без записи raw batch"
    )
    args = parser.parse_args()
    started_at = utc_instant()
    try:
        settings = load_himalayas_settings()
        run = select_run(settings, broad=args.broad)
    except HimalayasImportError as error:
        die(str(error))
    found_at = business_date(started_at)
    try:
        records, summary, errors = collect_records(settings, run, today_value=found_at)
    except HimalayasImportError as error:
        records, summary, errors = [], None, [str(error)]
        outcome = getattr(error, "outcome", "parse_error")
    else:
        outcome = "partial" if errors else "zero_results" if not records else "success"
    finished_at = utc_instant()
    output = None
    artifact_payload = {
        "version": 2,
        "adapter_version": "himalayas-v2",
        "source": SOURCE_NAME,
        "selection": run["selection"],
        "outcome": outcome,
        "complete": outcome in {"success", "zero_results"},
        "run_started_at": utc_timestamp(started_at),
        "run_finished_at": utc_timestamp(finished_at),
        "duration_seconds": max(0, (finished_at - started_at).total_seconds()),
        "business_timezone": BUSINESS_TIMEZONE_NAME,
        "found_at": found_at.isoformat(),
        "cadence_hours": run["cadence_hours"],
        "max_age_days": run["max_age_days"],
        "geo_policy": settings["geo"],
        "queries": run["queries"],
        "summary": summary,
        "records": records,
        "errors": errors,
    }
    try:
        if args.output is not None and artifact_payload["complete"]:
            output_path = validate_output_path(args.output)
            write_jsonl(output_path, records)
            output = output_path.relative_to(ROOT.resolve()).as_posix()
        elif args.artifact is not None:
            output = str(write_artifact(args.artifact, artifact_payload))
    except HimalayasImportError as error:
        die(str(error))
    result = {
        "ok": artifact_payload["complete"],
        "command": "import_himalayas",
        "mode": "dry_run"
        if args.dry_run
        else "write_artifact"
        if args.artifact is not None
        else "write_raw_batch",
        "selection": run["selection"],
        "outcome": outcome,
        "complete": artifact_payload["complete"],
        "run_started_at": artifact_payload["run_started_at"],
        "run_finished_at": artifact_payload["run_finished_at"],
        "duration_seconds": artifact_payload["duration_seconds"],
        "business_timezone": BUSINESS_TIMEZONE_NAME,
        "found_at": artifact_payload["found_at"],
        "cadence_hours": run["cadence_hours"],
        "max_age_days": run["max_age_days"],
        "geo_policy": settings["geo"],
        "queries": run["queries"],
        "summary": summary,
        "output": output,
        "errors": errors,
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    if not artifact_payload["complete"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
