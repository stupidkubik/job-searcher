#!/usr/bin/env python3
"""One-time backfill: give every historical request a matching result.

docs/agent-write-path-plan-2026-09-07.md, Э1b. Before Э1, a rejected request
left no result file at all, so the repository accumulated requests without a
matching result. This script makes that history readable and, together with
the test guardian in tests/test_agent_operations.py, keeps it from recurring:

- a request that still fails today's contract validation gets a `rejected`
  result carrying the validator's real `error.code`;
- a request that passes today's contract validation but was never applied
  gets a `rejected` result with `error.code: "lost_before_apply"` (RC-9 push
  race in docs/agent-ergonomics-analysis-2026-09-07.md) instead of a
  fabricated `completed` outcome — retroactively pretending it succeeded
  would risk claiming a canonical change that never happened.

Every backfilled result carries `"backfilled": true` and an `executed_at`
timestamp of when this script ran, not a guessed historical run time. This
script never touches data/jobs.csv, data/job_sources.csv, or an existing
result file.
"""

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
REQUESTS_DIR = ROOT / "data" / "operations" / "requests"
RESULTS_DIR = ROOT / "data" / "operations" / "results"

sys.path.insert(0, str(ROOT / "scripts"))
import agent_operations as ops  # noqa: E402
import jobs  # noqa: E402


LOST_BEFORE_APPLY_MESSAGE = (
    "request passed today's contract validation but has no matching result; "
    "it was lost before the runner ever applied it (see RC-9, the push race, "
    "in docs/agent-ergonomics-analysis-2026-09-07.md). This is not a "
    "retroactive success: canonical data was never changed. Resubmit as a "
    "new operation_id if the change is still wanted."
)


def missing_operation_ids():
    request_ids = {path.stem for path in REQUESTS_DIR.glob("*.json")}
    result_ids = {path.stem for path in RESULTS_DIR.glob("*.json")}
    return sorted(request_ids - result_ids)


def build_backfill_result(operation_id):
    request_path = REQUESTS_DIR / f"{operation_id}.json"
    command = ops.peek_command(request_path)
    try:
        operation = ops.load_operation(request_path)
    except (ops.OperationError, jobs.ValidationError) as error:
        result = ops.rejected_result(operation_id, command, error)
    else:
        lost_error = ops.contract_error(
            LOST_BEFORE_APPLY_MESSAGE,
            code="lost_before_apply",
        )
        result = ops.rejected_result(operation_id, operation["command"], lost_error)
    result["backfilled"] = True
    return result


def run(dry_run):
    created = []
    for operation_id in missing_operation_ids():
        result = build_backfill_result(operation_id)
        if not dry_run:
            ops.write_result(result)
        created.append(
            {
                "operation_id": operation_id,
                "command": result["command"],
                "error_code": result["error"]["code"],
            }
        )
    return created


def print_text(created, dry_run):
    if not created:
        print("no requests are missing a result")
        return
    verb = "would backfill" if dry_run else "backfilled"
    for entry in created:
        print(
            f"{verb}: {entry['operation_id']}  command={entry['command']}  error.code={entry['error_code']}"
        )
    print(f"\n{len(created)} result(s) {'would be ' if dry_run else ''}written")


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would be written without writing it"
    )
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args()

    created = run(args.dry_run)
    if args.format == "json":
        print(json.dumps({"dry_run": args.dry_run, "created": created}, ensure_ascii=False, sort_keys=True))
    else:
        print_text(created, args.dry_run)
    return 0


if __name__ == "__main__":
    sys.exit(main())
