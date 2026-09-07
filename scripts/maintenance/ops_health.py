#!/usr/bin/env python3
"""Read-only snapshot of write-path health. No network, no writes.

Mirrors the "Свежие цифры" table in
docs/agent-write-path-plan-2026-09-07.md so the plan's stages can be
compared against the same numbers before and after each change.
"""

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CSV_PATH = ROOT / "data" / "jobs.csv"
REQUESTS_DIR = ROOT / "data" / "operations" / "requests"
RESULTS_DIR = ROOT / "data" / "operations" / "results"

# Boot set as measured in docs/agent-ergonomics-analysis-2026-09-07.md
# section 2.1; excludes the per-source playbook, whose weight varies.
BOOT_SET = [
    ROOT / "data" / "jobs.csv",
    ROOT / "data" / "job_sources.csv",
    ROOT / "data" / "schema.md",
    ROOT / "AGENTS.md",
    ROOT / "config" / "profile.md",
    ROOT / "data" / "operations" / "README.md",
]

PLACEHOLDER_COMPANY_RE = re.compile(r"^(undisclosed|unknown|confidential|n/?a)\b", re.IGNORECASE)


def load_rows():
    with CSV_PATH.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def operation_ids(directory):
    return {path.stem for path in directory.glob("*.json")}


def result_status_distribution(result_ids):
    counts = {}
    for operation_id in sorted(result_ids):
        payload = json.loads((RESULTS_DIR / f"{operation_id}.json").read_text(encoding="utf-8"))
        status = payload.get("status", "unknown")
        counts[status] = counts.get(status, 0) + 1
    return counts


def boot_set_bytes():
    sizes = {}
    for path in BOOT_SET:
        sizes[str(path.relative_to(ROOT))] = path.stat().st_size if path.exists() else 0
    sizes["total"] = sum(sizes.values())
    return sizes


def build_report():
    rows = load_rows()
    requests = operation_ids(REQUESTS_DIR)
    results = operation_ids(RESULTS_DIR)
    missing = sorted(requests - results)

    not_started = [row for row in rows if row.get("application_status") == "not_started"]
    empty_original_url = [row for row in rows if not row.get("original_url", "").strip()]
    placeholder_company = [
        row for row in rows if PLACEHOLDER_COMPANY_RE.match((row.get("company") or "").strip())
    ]

    jobs_total = len(rows)
    return {
        "jobs_csv_rows": jobs_total,
        "requests_total": len(requests),
        "results_total": len(results),
        "requests_without_result": len(missing),
        "requests_without_result_ids": missing,
        "results_status_distribution": result_status_distribution(results),
        "empty_original_url_rows": len(empty_original_url),
        "placeholder_company_rows": len(placeholder_company),
        "not_started_rows": len(not_started),
        "not_started_percent": round(100 * len(not_started) / jobs_total, 1) if jobs_total else None,
        "boot_set_bytes": boot_set_bytes(),
    }


def print_text(report):
    rows = [
        ("строк в data/jobs.csv", report["jobs_csv_rows"]),
        ("запросов в requests/", report["requests_total"]),
        ("результатов в results/", report["results_total"]),
        ("запросов без результата", report["requests_without_result"]),
        ("результатов status: conflict", report["results_status_distribution"].get("conflict", 0)),
        ("строк с пустым original_url", report["empty_original_url_rows"]),
        ("строк с placeholder-компанией", report["placeholder_company_rows"]),
        (
            "not_started в датасете",
            f"{report['not_started_rows']} ({report['not_started_percent']}%)",
        ),
        ("boot-набор, байт", report["boot_set_bytes"]["total"]),
    ]
    width = max(len(label) for label, _ in rows)
    for label, value in rows:
        print(f"{label.ljust(width)} : {value}")
    if report["results_status_distribution"]:
        print("\nраспределение status в results/:")
        for status, count in sorted(report["results_status_distribution"].items()):
            print(f"  {status}: {count}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    report = build_report()
    if args.format == "json":
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print_text(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
