#!/usr/bin/env bash
# Applies one connector operation request and pushes the audited result to
# main, retrying against a freshly fetched main when the push loses a race
# with another concurrent operation (P8 in
# docs/agent-write-path-plan-2026-09-07.md, Э3).
#
# Never rebases: data/jobs.csv, data/job_sources.csv and docs/tracker.md are
# append-only across concurrent operations, and a rebase/merge over them would
# turn a lost push into a merge conflict in canonical data instead. Instead,
# on a lost race this script resets hard to the new origin/main (which already
# contains this run's own request commit, since that is what triggered the
# workflow) and reapplies the same request from scratch.
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "usage: apply_operation.sh <data/operations/requests/operation-id.json>" >&2
  exit 2
fi

REQUEST_PATH="$1"
OPERATION_ID="$(basename "$REQUEST_PATH" .json)"
RESULT_PATH="data/operations/results/${OPERATION_ID}.json"
OUTPUT_JSON="${RUNNER_TEMP:-/tmp}/operation-output.json"
MAX_ATTEMPTS=3

git config user.name "job-tracker-agent[bot]"
git config user.email "41898282+github-actions[bot]@users.noreply.github.com"

for attempt in $(seq 1 "$MAX_ATTEMPTS"); do
  echo "::group::attempt ${attempt}/${MAX_ATTEMPTS}: validate and apply"
  python3 scripts/agent_operations.py validate "$REQUEST_PATH" --format json
  set +e
  python3 scripts/agent_operations.py apply "$REQUEST_PATH" --format json > "$OUTPUT_JSON"
  set -e
  echo "::endgroup::"

  STATUS="$(python3 - "$OUTPUT_JSON" <<'PY'
import json
import re
import sys

payload = json.load(open(sys.argv[1], encoding="utf-8"))
operation_id = payload.get("operation_id")
risk = payload.get("risk")
status = payload.get("status")
if not isinstance(operation_id, str) or not re.fullmatch(r"[a-z0-9][a-z0-9._-]{2,79}", operation_id):
    sys.exit("runner returned an invalid operation_id")
if risk not in {"low", "medium", "none"} or status not in {"completed", "conflict", "partial", "rejected"}:
    sys.exit("runner returned an invalid risk or status")
print(status)
PY
  )"

  if [[ "$STATUS" != "rejected" ]]; then
    echo "::group::attempt ${attempt}/${MAX_ATTEMPTS}: validate resulting tracker state"
    python3 scripts/jobs.py validate --strict
    python3 scripts/jobs.py render-tracker
    python3 scripts/jobs.py render-tracker --check
    python3 -m unittest discover -s tests -v
    python3 scripts/jobs.py dupes --format json
    echo "::endgroup::"
  fi

  echo "::group::attempt ${attempt}/${MAX_ATTEMPTS}: enforce changed-file allowlist"
  python3 - "$OPERATION_ID" "$STATUS" <<'PY'
import re
import subprocess
import sys

operation_id, status = sys.argv[1], sys.argv[2]
expected_result = f"data/operations/results/{operation_id}.json"
raw = subprocess.check_output(["git", "status", "--porcelain=v1", "-z"])
paths = [entry[3:].decode("utf-8") for entry in raw.split(b"\0") if entry]
if status == "rejected":
    if paths != [expected_result]:
        sys.exit("a rejected operation must change exactly its own result file: " + ", ".join(paths))
else:
    allowed = {"data/jobs.csv", "data/job_sources.csv", "docs/tracker.md", expected_result}
    for path in paths:
        if path in allowed or re.fullmatch(r"applications/job-\d{4,}-[^/]+\.md", path):
            continue
        sys.exit(f"operation changed forbidden path: {path}")
    if expected_result not in paths:
        sys.exit("operation did not write its immutable result")
PY
  echo "::endgroup::"

  git add data/jobs.csv data/job_sources.csv docs/tracker.md data/operations/results applications
  if [[ "$STATUS" == "rejected" ]]; then
    git commit -m "jobs: reject agent operation ${OPERATION_ID}"
  else
    git commit -m "jobs: apply agent operation ${OPERATION_ID}"
  fi

  if git push origin "HEAD:${GITHUB_REF_NAME}"; then
    if [[ "$STATUS" == "rejected" ]]; then
      echo "operation rejected: see ${RESULT_PATH}" >&2
      exit 1
    fi
    exit 0
  fi

  if [[ "$attempt" == "$MAX_ATTEMPTS" ]]; then
    echo "push failed after ${MAX_ATTEMPTS} attempts: another operation keeps winning the race" >&2
    exit 1
  fi

  echo "push lost the race with a concurrent operation; reapplying on fresh main (attempt $((attempt + 1))/${MAX_ATTEMPTS})" >&2
  git fetch origin main
  git reset --hard origin/main
  rm -f "$RESULT_PATH"
done
