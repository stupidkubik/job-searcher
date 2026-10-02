"""Read-only request/result audit against a stable main and Actions evidence.

Unit tests use fixtures. Production completeness belongs here, after execution,
not in unittest discover on an intermediate request commit.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REQUESTS = "data/operations/requests"
RESULTS = "data/operations/results"
WORKFLOW = "agent-operations.yml"
ACTIVE = {"queued", "in_progress", "waiting", "pending", "requested", "paused"}
ATTEMPTS = 3
RETRY_SECONDS = 3


class AuditError(Exception):
    pass


def git(root, *args):
    return subprocess.check_output(["git", *args], cwd=root, text=True).strip()


class ActionsAPI:
    def __init__(self, repository, token):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise AuditError("invalid repository")
        self.repository = repository
        self.token = token

    def get(self, path):
        request = urllib.request.Request(
            f"https://api.github.com/repos/{self.repository}/{path}",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)

    def runs(self):
        result = []
        page = 1
        while True:
            payload = self.get(f"actions/workflows/{WORKFLOW}/runs?per_page=100&page={page}")
            runs = payload["workflow_runs"]
            result.extend(runs)
            if len(runs) < 100:
                return result
            page += 1

    def main_sha(self):
        return self.get("git/ref/heads/main")["object"]["sha"]


def missing_requests(root):
    requests = {path.stem for path in (root / REQUESTS).glob("*.json")}
    results = {path.stem for path in (root / RESULTS).glob("*.json")}
    return sorted(requests - results)


def classify(operation_id, introduction_sha, runs):
    """An active retry wins over a terminal earlier attempt for this ID only."""
    selected = []
    dispatch_title = f"operation {REQUESTS}/{operation_id}.json"
    legacy_dispatch_active = False
    for run in runs:
        if run.get("head_branch") != "main":
            continue
        event = run.get("event")
        match = (event == "push" and run.get("head_sha") == introduction_sha) or (
            event == "workflow_dispatch" and run.get("display_title") == dispatch_title
        )
        if match:
            selected.append(run)
        elif event == "workflow_dispatch" and run.get("status") in ACTIVE:
            legacy_dispatch_active |= not str(run.get("display_title", "")).startswith(
                f"operation {REQUESTS}/"
            )
    if any(run.get("status") in ACTIVE for run in selected):
        return {"state": "pending", "runs": [run["id"] for run in selected]}
    if any(run.get("status") != "completed" for run in selected):
        return {"state": "unknown", "reason": "unrecognized Actions status", "runs": selected}
    if legacy_dispatch_active:
        return {"state": "unknown", "reason": "active historical dispatch has no request identity"}
    if selected:
        return {"state": "lost", "runs": [run["id"] for run in selected]}
    return {"state": "unknown", "reason": "no matching run: orphan or registration lag"}


def inspect(root, runs):
    report = {}
    for operation_id in missing_requests(root):
        sha = git(
            root, "log", "-1", "--diff-filter=A", "--format=%H", "--", f"{REQUESTS}/{operation_id}.json"
        )
        if not sha:
            raise AuditError(f"no introduction commit for {operation_id}; full history is required")
        report[operation_id] = classify(operation_id, sha, runs)
    return report


def audit(root, api, *, sleep=time.sleep):
    """Fetch before evidence; compare API main afterwards; retry any failing snapshot.

    At most three snapshots and two three-second sleeps. API/Git errors fail
    closed immediately. Unknown is an error, not evidence that an operation lost.
    """
    for attempt in range(ATTEMPTS):
        git(root, "fetch", "origin", "main")
        git(root, "checkout", "--detach", "origin/main")
        sha = git(root, "rev-parse", "HEAD")
        report = inspect(root, api.runs())
        stable = sha == api.main_sha()
        unknown = any(item["state"] == "unknown" for item in report.values())
        lost = any(item["state"] == "lost" for item in report.values())
        if stable and not unknown and not lost:
            return {
                "snapshot": sha,
                "operations": report,
                "ok": True,
            }
        if attempt + 1 < ATTEMPTS:
            sleep(RETRY_SECONDS)
    result = {"snapshot": sha, "operations": report, "ok": False}
    if not stable:
        result["error"] = "main changed during audit"
    elif unknown:
        result["error"] = "unresolved run evidence after bounded registration retries"
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--settled",
        action="store_true",
        help="Offline strict audit: ALL requests must have results; run only when no operations are pending",
    )
    args = parser.parse_args()
    try:
        if args.settled:
            missing = missing_requests(ROOT)
            payload = {"ok": not missing, "missing": missing}
        else:
            token = os.environ.get("GH_TOKEN")
            if not token:
                raise AuditError("GH_TOKEN is required for Actions evidence (or use --settled offline)")
            payload = audit(ROOT, ActionsAPI(os.environ.get("GITHUB_REPOSITORY", ""), token))
        print(json.dumps(payload, indent=2))
        return 0 if payload["ok"] else 1
    except (AuditError, OSError, ValueError, KeyError, subprocess.CalledProcessError) as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    sys.exit(main())
