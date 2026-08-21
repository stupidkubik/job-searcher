#!/usr/bin/env python3
"""Load and validate external-source policy from config/sources.toml."""

import argparse
import sys
import tomllib
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = ROOT / "config" / "sources.toml"
SOURCE_TYPES = {"api", "job_board", "manual", "messaging"}
REQUIRED_SOURCE_FIELDS = {
    "enabled", "type", "cadence_hours", "max_age_days", "geo", "aggregator",
    "verification", "caveats",
}
OPTIONAL_SOURCE_FIELDS = {
    "broad_cadence_hours", "fallback_max_age_days", "feed_url", "search_url",
    "narrow_queries", "broad_queries", "employment_types", "seniority",
}
REQUIRED_VERIFICATION_FIELDS = {"first_party_required", "apply_required"}


class SourceConfigError(ValueError):
    pass


def error(source_name, message):
    raise SourceConfigError(f"source {source_name}: {message}")


def is_positive_int(value):
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def require_string_list(source_name, field, value, allow_empty=False):
    if not isinstance(value, list) or (not allow_empty and not value):
        error(source_name, f"{field} должен быть непустым списком строк")
    if not all(isinstance(item, str) and item.strip() for item in value):
        error(source_name, f"{field} должен содержать только непустые строки")


def validate_source(source_name, source):
    if not isinstance(source, dict):
        error(source_name, "конфигурация должна быть TOML table")
    unknown = sorted(set(source) - REQUIRED_SOURCE_FIELDS - OPTIONAL_SOURCE_FIELDS)
    if unknown:
        error(source_name, "неизвестные поля: " + ", ".join(unknown))
    missing = sorted(REQUIRED_SOURCE_FIELDS - set(source))
    if missing:
        error(source_name, "отсутствуют обязательные поля: " + ", ".join(missing))
    if not isinstance(source["enabled"], bool):
        error(source_name, "enabled должен быть boolean")
    if source["type"] not in SOURCE_TYPES:
        error(source_name, f"неизвестный type={source['type']!r}; допустимы: {sorted(SOURCE_TYPES)}")
    for field in ("cadence_hours", "max_age_days"):
        if not is_positive_int(source[field]):
            error(source_name, f"{field} должен быть положительным целым числом")
    if source["cadence_hours"] > 24 * 7:
        error(source_name, "cadence_hours не может быть больше 168")
    if "broad_cadence_hours" in source:
        if not is_positive_int(source["broad_cadence_hours"]):
            error(source_name, "broad_cadence_hours должен быть положительным целым числом")
        if source["broad_cadence_hours"] < source["cadence_hours"]:
            error(source_name, "broad_cadence_hours не может быть меньше cadence_hours")
    if "fallback_max_age_days" in source:
        if not is_positive_int(source["fallback_max_age_days"]):
            error(source_name, "fallback_max_age_days должен быть положительным целым числом")
        if source["fallback_max_age_days"] < source["max_age_days"]:
            error(source_name, "fallback_max_age_days не может быть меньше max_age_days")
    require_string_list(source_name, "geo", source["geo"])
    if not isinstance(source["aggregator"], bool):
        error(source_name, "aggregator должен быть boolean")
    verification = source["verification"]
    if not isinstance(verification, dict):
        error(source_name, "verification должен быть TOML table")
    verification_missing = sorted(REQUIRED_VERIFICATION_FIELDS - set(verification))
    if verification_missing:
        error(source_name, "verification не содержит: " + ", ".join(verification_missing))
    verification_unknown = sorted(set(verification) - REQUIRED_VERIFICATION_FIELDS)
    if verification_unknown:
        error(source_name, "verification содержит неизвестные поля: " + ", ".join(verification_unknown))
    if not all(isinstance(verification[key], bool) for key in REQUIRED_VERIFICATION_FIELDS):
        error(source_name, "verification values должны быть boolean")
    require_string_list(source_name, "caveats", source["caveats"])
    for field in ("narrow_queries", "broad_queries", "employment_types", "seniority"):
        if field in source:
            require_string_list(source_name, field, source[field])
    for field in ("feed_url", "search_url"):
        if field in source and (not isinstance(source[field], str) or not source[field].startswith("https://")):
            error(source_name, f"{field} должен быть https URL")
    return source


def load_source_config(path=CONFIG_PATH):
    try:
        with Path(path).open("rb") as file:
            document = tomllib.load(file)
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise SourceConfigError(f"не удалось прочитать source registry {path}: {exc}") from exc
    if set(document) != {"sources"} or not isinstance(document.get("sources"), dict):
        raise SourceConfigError("source registry должен содержать только [sources.*] tables")
    if not document["sources"]:
        raise SourceConfigError("source registry не должен быть пустым")
    return {
        source_name: validate_source(source_name, source)
        for source_name, source in document["sources"].items()
    }


def main():
    parser = argparse.ArgumentParser(description="Проверить config/sources.toml")
    parser.add_argument("path", nargs="?", type=Path, default=CONFIG_PATH)
    args = parser.parse_args()
    try:
        sources = load_source_config(args.path)
    except SourceConfigError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
    print(f"проверено источников: {len(sources)}; ошибок: 0")


if __name__ == "__main__":
    main()
