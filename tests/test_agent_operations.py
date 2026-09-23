import csv
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import agent_operations as ops


PROJECT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT / ".github" / "workflows" / "agent-operations.yml"
VALIDATE_WORKFLOW = PROJECT / ".github" / "workflows" / "validate.yml"
APPLY_SCRIPT = PROJECT / "scripts" / "ci" / "apply_operation.sh"
LIVE_REQUESTS_DIR = PROJECT / "data" / "operations" / "requests"
LIVE_RESULTS_DIR = PROJECT / "data" / "operations" / "results"


class RequestResultInvariantTests(unittest.TestCase):
    """Every committed request must end up with a matching result
    (docs/agent-write-path-plan-2026-09-07.md, Э1b). Before Э1, a rejected
    apply left no result file at all; this guardian keeps that regression
    from recurring silently."""

    def test_every_request_has_a_matching_result(self):
        request_ids = {path.stem for path in LIVE_REQUESTS_DIR.glob("*.json")}
        result_ids = {path.stem for path in LIVE_RESULTS_DIR.glob("*.json")}
        missing = sorted(request_ids - result_ids)
        self.assertEqual(
            missing,
            [],
            "these requests have no result file: " + ", ".join(missing) + ". "
            "Run scripts/maintenance/backfill_missing_results.py for a historical "
            "request. If you just committed one of these yourself, its workflow run "
            "may simply not have finished yet — git pull and re-check before "
            "assuming this is a real regression.",
        )


class ApplyOperationScriptTests(unittest.TestCase):
    """Executes scripts/ci/apply_operation.sh instead of grepping it.

    docs/agent-write-path-plan-2026-09-07.md, Э1 promises that no path
    through the runner ends without a machine-readable result. Every other
    test in this file proves that for `agent_operations.py apply` alone,
    while the runner reaches it through this shell wrapper -- so a
    contract-rejecting step placed in front of `apply` restores the silent
    failure without breaking a single string assertion. Only running the
    script catches that, so this test runs it against a real throwaway
    repository with a bare origin.
    """

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        base = Path(self.temporary.name)
        self.root = base / "checkout"
        self.origin = base / "origin.git"
        for directory in (
            "scripts/ci",
            "data/operations/requests",
            "data/operations/results",
            "data/index",
            "applications",
            "docs",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in (
            "jobs.py",
            "tracker_paths.py",
            "tracker_schema.py",
            "tracker_validate.py",
            "tracker_write.py",
            "tracker_transaction.py",
            "tracker_ingest.py",
            "tracker_render.py",
            "tracker_cli.py",
            "tracker_time.py",
            "agent_operations.py",
        ):
            shutil.copy2(PROJECT / "scripts" / name, self.root / "scripts" / name)
        shutil.copy2(APPLY_SCRIPT, self.root / "scripts" / "ci" / "apply_operation.sh")
        for name in ("jobs.csv", "job_sources.csv"):
            header = (PROJECT / "data" / name).read_text(encoding="utf-8").splitlines()[0]
            (self.root / "data" / name).write_text(header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")
        (self.root / "docs" / "tracker.md").write_text("# tracker\n", encoding="utf-8")
        for name in ("known.tsv", "keys.tsv", "active.csv"):
            (self.root / "data" / "index" / name).write_text("", encoding="utf-8")
        # Mirror the real checkout: __pycache__ is ignored, and results/ is a
        # tracked directory, so the changed-path allowlist sees a new result as
        # its own path rather than as one collapsed untracked directory.
        (self.root / ".gitignore").write_text("__pycache__/\n.v3-transaction.lock\n", encoding="utf-8")
        (self.root / "data" / "operations" / "results" / ".gitkeep").write_text("", encoding="utf-8")

        self.git("init", "--bare", str(self.origin), cwd=base)
        self.git("init")
        self.git("config", "user.email", "test@example.invalid")
        self.git("config", "user.name", "test")
        self.git("remote", "add", "origin", str(self.origin))

    def tearDown(self):
        self.temporary.cleanup()

    def git(self, *arguments, cwd=None):
        done = subprocess.run(["git", *arguments], cwd=cwd or self.root, text=True, capture_output=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        return done.stdout

    def run_script(self, request_relative_path):
        environment = {
            **os.environ,
            "GITHUB_REF_NAME": "main",
            "RUNNER_TEMP": self.temporary.name,
        }
        return subprocess.run(
            ["bash", "scripts/ci/apply_operation.sh", request_relative_path],
            cwd=self.root,
            text=True,
            capture_output=True,
            env=environment,
        )

    def test_a_contract_rejection_still_commits_and_pushes_its_result(self):
        relative = "data/operations/requests/op-script-rejection-001.json"
        (self.root / relative).write_text(
            json.dumps(
                {
                    "version": 1,
                    "operation_id": "op-script-rejection-001",
                    "command": "add",
                    "args": {
                        "company": "ScriptCo",
                        "role": "Frontend Engineer",
                        "source": "Manual",
                        "next_action": "follow up",
                    },
                }
            ),
            encoding="utf-8",
        )
        self.git("add", "--all")
        self.git("commit", "--message", "seed")

        done = self.run_script(relative)

        self.assertEqual(done.returncode, 1, done.stdout + done.stderr)
        result_path = self.root / "data" / "operations" / "results" / "op-script-rejection-001.json"
        self.assertTrue(
            result_path.exists(),
            "the runner script ended without a result file: " + done.stdout + done.stderr,
        )
        result = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(result["status"], "rejected")
        self.assertEqual(result["error"]["code"], "unknown_args")
        self.assertEqual(result["error"]["field"], "args.next_action")
        self.assertIn(
            "jobs: reject agent operation op-script-rejection-001", self.git("log", "-1", "--format=%s")
        )
        self.assertIn(
            "op-script-rejection-001.json",
            self.git("show", "--name-only", "--format=", "HEAD"),
        )
        self.assertIn(
            "jobs: reject agent operation op-script-rejection-001",
            self.git("log", "-1", "--format=%s", "main", cwd=self.origin),
        )


class AgentOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in (
            "data",
            "applications",
            "scripts",
            "data/operations/requests",
            "data/operations/results",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in (
            "jobs.py",
            "tracker_paths.py",
            "tracker_schema.py",
            "tracker_validate.py",
            "tracker_write.py",
            "tracker_transaction.py",
            "tracker_ingest.py",
            "tracker_render.py",
            "tracker_cli.py",
            "tracker_time.py",
            "agent_operations.py",
        ):
            shutil.copy2(PROJECT / "scripts" / name, self.root / "scripts" / name)
        for name in ("jobs.csv", "job_sources.csv"):
            header = (PROJECT / "data" / name).read_text(encoding="utf-8").splitlines()[0]
            (self.root / "data" / name).write_text(header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke_jobs(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/jobs.py", *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def invoke_operation(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/agent_operations.py", *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def rows(self):
        with (self.root / "data" / "jobs.csv").open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def source_rows(self):
        with (self.root / "data" / "job_sources.csv").open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def seed_job(self):
        created = self.invoke_jobs(
            "add",
            "--company",
            "OperationCo",
            "--role",
            "Frontend Developer",
            "--source",
            "Manual",
            "--no-file",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        return self.rows()[0]

    def write_operation(self, operation):
        path = self.root / "data" / "operations" / "requests" / f"{operation['operation_id']}.json"
        path.write_text(json.dumps(operation), encoding="utf-8")
        return path.relative_to(self.root)

    def test_workflow_uses_an_expression_safe_dispatch_step_id(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("id: dispatch_request", workflow)
        self.assertIn("steps.dispatch_request.outputs.path", workflow)
        self.assertNotIn("dispatch-request", workflow)

    def test_workflow_discovers_a_push_request_from_the_main_diff(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('["git", "diff", "--name-only", base, "HEAD"]', workflow)
        self.assertNotIn('"agent/**"', workflow)
        self.assertNotIn('event.get("head_commit", {}).get("added", [])', workflow)

    def test_workflow_pushes_results_without_creating_a_review_pr(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("branches: [main]", workflow)
        self.assertIn('["git", "diff", "--name-status", base, "HEAD"]', workflow)
        self.assertNotIn("pull-requests: write", workflow)
        self.assertNotIn("GH_TOKEN:", workflow)
        self.assertNotIn("gh pr create", workflow)

    def test_connector_contract_uses_main_without_review_pr_creation(self):
        contract = (PROJECT / "data" / "operations" / "README.md").read_text(encoding="utf-8")
        instructions = (PROJECT / "AGENTS.md").read_text(encoding="utf-8")
        normalized_contract = " ".join(contract.split())
        self.assertIn("Every connector operation is delivered through `main`", normalized_contract)
        self.assertIn("Operation branches and review", normalized_contract)
        self.assertIn("Не создавать operation-ветки или PR", instructions)

    def test_workflow_keeps_its_operation_output_outside_the_checkout(self):
        script = APPLY_SCRIPT.read_text(encoding="utf-8")
        self.assertIn('> "$OUTPUT_JSON"', script)
        self.assertIn('OUTPUT_JSON="${RUNNER_TEMP:-/tmp}/operation-output.json"', script)
        self.assertNotIn("> operation-output.json", script)

    def test_documented_runner_allowlist_matches_the_one_the_runner_enforces(self):
        """The changed-path allowlist is stated in three places: the script
        that enforces it, the connector contract, and the write-path
        overview. Э6 added data/index/* to the script alone, so both
        documents described a narrower runner than the real one — read as
        "the runner will reject this", which is the opposite of true.
        """
        script = APPLY_SCRIPT.read_text(encoding="utf-8")
        block = script.split("allowed = {", 1)[1].split("}", 1)[0]
        enforced = set(re.findall(r'"([^"]+)"', block))
        self.assertIn("data/jobs.csv", enforced, "could not parse the allowlist out of the script")

        for relative in ("data/operations/README.md", "docs/agent-operations.md"):
            body = (PROJECT / relative).read_text(encoding="utf-8")
            for path in sorted(enforced):
                self.assertIn(
                    path,
                    body,
                    f"{relative} does not mention {path}, which the runner actually permits",
                )

    def test_workflows_keep_the_generated_tracker_in_sync(self):
        apply_script = APPLY_SCRIPT.read_text(encoding="utf-8")
        validation_workflow = VALIDATE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python3 scripts/jobs.py render-tracker", apply_script)
        self.assertIn("python3 scripts/jobs.py render-tracker --check", apply_script)
        self.assertIn('"docs/tracker.md"', apply_script)
        self.assertIn("git add data/jobs.csv data/job_sources.csv docs/tracker.md", apply_script)
        self.assertIn("python scripts/jobs.py render-tracker --check", validation_workflow)

    def test_workflows_keep_the_generated_indexes_in_sync(self):
        apply_script = APPLY_SCRIPT.read_text(encoding="utf-8")
        validation_workflow = VALIDATE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("python3 scripts/jobs.py render-index", apply_script)
        self.assertIn("python3 scripts/jobs.py render-index --check", apply_script)
        for path in ('"data/index/known.tsv"', '"data/index/keys.tsv"', '"data/index/active.csv"'):
            self.assertIn(path, apply_script)
        self.assertIn("git add data/jobs.csv data/job_sources.csv docs/tracker.md data/index", apply_script)
        self.assertIn("python scripts/jobs.py render-index --check", validation_workflow)

    def test_operation_workflow_delegates_apply_and_push_to_the_retry_script(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("scripts/ci/apply_operation.sh", workflow)
        self.assertIn("Reject merge commits", workflow)
        self.assertTrue(APPLY_SCRIPT.exists())

    def test_pull_requests_touching_operation_requests_are_rejected(self):
        validation_workflow = VALIDATE_WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("reject-request-prs", validation_workflow)
        self.assertIn("data/operations/requests/", validation_workflow)
        self.assertIn(
            "this delivery path is not supported: commit the request directly to main",
            validation_workflow,
        )

    def test_apply_script_reapplies_on_a_lost_push_race_without_rebasing(self):
        script = APPLY_SCRIPT.read_text(encoding="utf-8")
        self.assertIn("git fetch origin main", script)
        self.assertIn("git reset --hard origin/main", script)
        self.assertNotIn("git rebase", script)
        self.assertNotIn("git merge", script)
        self.assertIn('rm -f "$RESULT_PATH"', script)

    def test_medium_risk_add_creates_job_provenance_card_and_result(self):
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-add-001",
                "command": "add",
                "args": {
                    "company": "ConnectorCo",
                    "role": "Frontend Engineer",
                    "source": "LinkedIn",
                    "source_url": "https://www.linkedin.com/jobs/view/12345",
                    "original_url": "https://careers.example.test/jobs/frontend",
                    "application_status": "reviewing",
                    "listing_status": "open",
                    "first_party_verified": "yes",
                    "apply_verified": "yes",
                    "remote_policy": "Europe",
                    "match_score": 8.5,
                },
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "medium"))
        self.assertEqual(payload["result"]["result"]["outcome"], "job_added")
        self.assertEqual(payload["result"]["job_id"], "job-0001")
        row = self.rows()[0]
        self.assertEqual(
            (row["company"], row["application_status"], row["listing_status"], row["match_score"]),
            ("ConnectorCo", "reviewing", "open", "8.5"),
        )
        self.assertEqual(self.source_rows()[0]["job_id"], "job-0001")
        self.assertTrue(list((self.root / "applications").glob("job-0001-*.md")))
        self.assertTrue((self.root / payload["result_path"]).exists())

    def test_add_with_screening_blocker_does_not_create_application_card(self):
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-add-blocked-001",
                "command": "add",
                "args": {
                    "company": "BlockedCo",
                    "role": "Frontend Developer",
                    "source": "Himalayas",
                    "source_job_id": "blocked-123",
                    "decision_reason": "geo_restriction",
                    "notes": "Remote is limited to the United States.",
                },
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["result"]["result"]["application_path"], None)
        self.assertEqual(self.rows()[0]["decision_reason"], "geo_restriction")
        self.assertFalse(list((self.root / "applications").glob("job-0001-*.md")))

    def test_add_records_unresolved_duplicate_as_immutable_conflict(self):
        self.seed_job()
        before = (self.root / "data" / "jobs.csv").read_bytes()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-add-conflict-001",
                "command": "add",
                "args": {
                    "company": "OperationCo",
                    "role": "Frontend Developer",
                    "source": "LinkedIn",
                    "source_url": "https://www.linkedin.com/jobs/view/duplicate",
                },
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("conflict", "medium"))
        self.assertEqual(payload["result"]["result"]["reason"], "unresolved_duplicate")
        self.assertEqual(payload["result"]["result"]["candidates"][0]["id"], "job-0001")
        self.assertNotRegex(payload["result"]["result"]["candidates"][0]["reason"], r"[Ѐ-ӿ]")
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        self.assertTrue((self.root / payload["result_path"]).exists())

    def test_add_source_reference_conflict_speaks_english_without_a_cli_flag(self):
        """docs/agent-write-path-plan-2026-09-07.md, Э8: jobs.SourceReferenceConflict
        used to tell the connector to retry with --force; the retry object
        already does that (force=true), so the message itself must not."""
        self.seed_job()
        first = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-add-shared-url-001",
                "command": "add",
                "args": {
                    "company": "AlphaSource Co",
                    "role": "Backend Engineer",
                    "source": "LinkedIn",
                    "source_url": "https://www.linkedin.com/jobs/view/shared-1",
                },
            }
        )
        self.assertEqual(self.invoke_operation("apply", str(first), "--format", "json").returncode, 0)
        before = (self.root / "data" / "jobs.csv").read_bytes()

        conflicting = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-add-shared-url-002",
                "command": "add",
                "args": {
                    "company": "Totally Different Studio",
                    "role": "Marketing Lead",
                    "source": "LinkedIn",
                    "source_url": "https://www.linkedin.com/jobs/view/shared-1",
                },
            }
        )
        result = self.invoke_operation("apply", str(conflicting), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "conflict")
        details = payload["result"]["result"]
        self.assertEqual(details["reason"], "source_reference_conflict")
        self.assertIn("job-0002", details["message"])
        self.assertNotRegex(details["message"], r"--[a-zA-Z]")
        self.assertNotRegex(details["message"], r"[Ѐ-ӿ]")
        self.assertTrue(details["retry"]["as_separate"]["args"]["force"])
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

    def test_add_can_attach_a_confirmed_duplicate_source_reference(self):
        self.seed_job()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-add-source-001",
                "command": "add",
                "args": {
                    "company": "OperationCo",
                    "role": "Frontend Developer",
                    "source": "LinkedIn",
                    "source_url": "https://www.linkedin.com/jobs/view/another-location",
                    "duplicate_of": "job-0001",
                },
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["result"]["result"]["outcome"], "source_reference_added")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.source_rows()[0]["job_id"], "job-0001")

    def test_add_rejects_human_only_status_and_missing_external_reference(self):
        human_only = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-add-applied-001",
                "command": "add",
                "args": {
                    "company": "UnsafeCo",
                    "role": "Frontend Developer",
                    "source": "Manual",
                    "application_status": "applied",
                },
            }
        )
        missing_reference = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-add-no-source-001",
                "command": "add",
                "args": {
                    "company": "NoSourceCo",
                    "role": "Frontend Developer",
                    "source": "LinkedIn",
                },
            }
        )

        first = self.invoke_operation("validate", str(human_only), "--format", "json")
        second = self.invoke_operation("validate", str(missing_reference), "--format", "json")

        self.assertNotEqual(first.returncode, 0)
        self.assertIn("only to not_started or reviewing", first.stderr)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("requires source_url or source_job_id", second.stderr)
        self.assertEqual(self.rows(), [])

    def test_low_risk_verify_uses_jobs_write_path_and_records_immutable_result(self):
        row = self.seed_job()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-close-001",
                "command": "verify",
                "job_id": "job-0001",
                "expected": {"application_status": "not_started", "last_update": row["last_update"]},
                "args": {
                    "listing_status": "closed",
                    "first_party_verified": "yes",
                    "apply_verified": "no",
                    "original_url": "https://careers.example.test/jobs/operation",
                    "decision_reason": "closed_before_application",
                },
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "low"))
        updated = self.rows()[0]
        self.assertEqual(
            (updated["application_status"], updated["listing_status"], updated["decision_reason"]),
            ("not_started", "closed", "closed_before_application"),
        )
        result_path = self.root / payload["result_path"]
        self.assertEqual(json.loads(result_path.read_text(encoding="utf-8"))["status"], "completed")

        repeated = self.invoke_operation("apply", str(request), "--format", "json")
        self.assertEqual(repeated.returncode, 1)
        self.assertIn("already has a result", repeated.stderr)

    def test_medium_risk_verify_can_promote_to_reviewing_and_enrich(self):
        row = self.seed_job()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-review-001",
                "command": "verify",
                "job_id": "job-0001",
                "expected": {"application_status": "not_started", "last_update": row["last_update"]},
                "args": {
                    "listing_status": "open",
                    "first_party_verified": "yes",
                    "apply_verified": "yes",
                    "original_url": "https://careers.example.test/jobs/operation",
                    "level": "Junior",
                    "remote_policy": "Europe",
                    "stack": "React; TypeScript",
                    "salary": "1200 USD/month",
                    "match_score": 8.5,
                },
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "medium"))
        updated = self.rows()[0]
        self.assertEqual(
            (
                updated["application_status"],
                updated["level"],
                updated["remote_policy"],
                updated["match_score"],
            ),
            ("reviewing", "Junior", "Europe", "8.5"),
        )
        self.assertTrue(list((self.root / "applications").glob("job-0001-*.md")))

    def test_medium_risk_verify_can_record_a_human_started_application(self):
        row = self.seed_job()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-active-application-001",
                "command": "verify",
                "job_id": "job-0001",
                "expected": {"application_status": "not_started", "last_update": row["last_update"]},
                "args": {
                    "listing_status": "open",
                    "first_party_verified": "yes",
                    "apply_verified": "yes",
                    "original_url": "https://careers.example.test/jobs/operation",
                    "application_status": "apply",
                    "next_action": "complete the required interview",
                },
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "medium"))
        updated = self.rows()[0]
        self.assertEqual(
            (updated["application_status"], updated["next_action"], updated["applied_at"]),
            ("apply", "complete the required interview", ""),
        )
        self.assertTrue(list((self.root / "applications").glob("job-0001-*.md")))

    def test_stale_precondition_records_conflict_without_canonical_write(self):
        row = self.seed_job()
        before = (self.root / "data" / "jobs.csv").read_bytes()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-conflict-001",
                "command": "set",
                "job_id": "job-0001",
                "expected": {"application_status": "reviewing", "last_update": row["last_update"]},
                "args": {"next_action": "verify first-party"},
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("conflict", "low"))
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        self.assertEqual(payload["result"]["result"]["reason"], "stale_operation")

    def test_allowlisted_set_can_schedule_the_next_safe_action(self):
        row = self.seed_job()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-next-action-001",
                "command": "set",
                "job_id": "job-0001",
                "expected": {"application_status": "not_started", "last_update": row["last_update"]},
                "args": {
                    "next_action": "verify first-party",
                    "next_action_date": "2026-08-12",
                },
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "low"))
        self.assertEqual(
            (self.rows()[0]["next_action"], self.rows()[0]["next_action_date"]),
            ("verify first-party", "2026-08-12"),
        )

    def test_low_risk_screen_preserves_listing_and_verification_fields(self):
        row = self.seed_job()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-screen-001",
                "command": "screen",
                "job_id": "job-0001",
                "expected": {"application_status": "not_started", "listing_status": "unknown"},
                "args": {
                    "decision_reason": "geo_restriction",
                    "notes": "Himalayas restricts this role to Latin America.",
                },
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "low"))
        updated = self.rows()[0]
        self.assertEqual(
            (updated["application_status"], updated["decision_reason"]), ("not_started", "geo_restriction")
        )
        for field in ("listing_status", "verified_at", "first_party_verified", "apply_verified"):
            self.assertEqual(updated[field], row[field])

    def test_atomic_batch_applies_multiple_screen_decisions_once(self):
        first = self.seed_job()
        created = self.invoke_jobs(
            "add",
            "--company",
            "Second OperationCo",
            "--role",
            "Frontend Developer",
            "--source",
            "Manual",
            "--force",
            "--no-file",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        second = self.rows()[1]
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-screen-batch-001",
                "command": "batch",
                "atomic": True,
                "operations": [
                    {
                        "command": "screen",
                        "job_id": "job-0001",
                        "expected": {
                            "application_status": "not_started",
                            "last_update": first["last_update"],
                        },
                        "args": {"decision_reason": "geo_restriction"},
                    },
                    {
                        "command": "screen",
                        "job_id": "job-0002",
                        "expected": {
                            "application_status": "not_started",
                            "last_update": second["last_update"],
                        },
                        "args": {"decision_reason": "seniority_too_high"},
                    },
                ],
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "low"))
        self.assertEqual(payload["result"]["result"]["outcome"], "atomic_batch_applied")
        self.assertEqual(payload["result"]["result"]["count"], 2)
        self.assertEqual(
            [row["decision_reason"] for row in self.rows()],
            ["geo_restriction", "seniority_too_high"],
        )

    def test_atomic_batch_rejects_every_write_if_a_later_screen_is_forbidden(self):
        first = self.seed_job()
        created = self.invoke_jobs(
            "add",
            "--company",
            "Applied OperationCo",
            "--role",
            "Frontend Developer",
            "--source",
            "Manual",
            "--force",
            "--no-file",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(
            self.invoke_jobs("status", "job-0002", "--application-status", "applied").returncode, 0
        )
        second = self.rows()[1]
        before = (self.root / "data" / "jobs.csv").read_bytes()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-screen-batch-reject-001",
                "command": "batch",
                "atomic": True,
                "operations": [
                    {
                        "command": "screen",
                        "job_id": "job-0001",
                        "expected": {
                            "application_status": "not_started",
                            "last_update": first["last_update"],
                        },
                        "args": {"decision_reason": "geo_restriction"},
                    },
                    {
                        "command": "screen",
                        "job_id": "job-0002",
                        "expected": {"application_status": "applied", "last_update": second["last_update"]},
                        "args": {"decision_reason": "seniority_too_high"},
                    },
                ],
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["ok"], payload["status"]), (False, "rejected"))
        self.assertEqual(payload["result"]["error"]["code"], "invariant_violation")
        self.assertIn(
            "allowed only before an application is actually submitted", payload["result"]["error"]["message"]
        )
        self.assertNotRegex(payload["result"]["error"]["message"], r"[Ѐ-ӿ]")
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        result_path = self.root / "data" / "operations" / "results" / "op-screen-batch-reject-001.json"
        self.assertTrue(result_path.exists())
        self.assertEqual(json.loads(result_path.read_text(encoding="utf-8"))["status"], "rejected")

    def test_verify_rejects_human_only_application_statuses_before_writing(self):
        row = self.seed_job()
        before = (self.root / "data" / "jobs.csv").read_bytes()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-human-only-001",
                "command": "verify",
                "job_id": "job-0001",
                "expected": {"application_status": "not_started", "last_update": row["last_update"]},
                "args": {
                    "listing_status": "open",
                    "first_party_verified": "yes",
                    "apply_verified": "yes",
                    "application_status": "applied",
                    "next_action": "submit application",
                },
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["ok"], payload["status"]), (False, "rejected"))
        self.assertIn(
            "verify may set application_status only to apply", payload["result"]["error"]["message"]
        )
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        result_files = list((self.root / "data" / "operations" / "results").glob("*.json"))
        self.assertEqual(len(result_files), 1)
        self.assertEqual(json.loads(result_files[0].read_text(encoding="utf-8"))["status"], "rejected")

    def test_verify_requires_original_url_when_first_party_verified_yes(self):
        row = self.seed_job()
        before = (self.root / "data" / "jobs.csv").read_bytes()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-missing-original-url-001",
                "command": "verify",
                "job_id": "job-0001",
                "expected": {"application_status": "not_started", "last_update": row["last_update"]},
                "args": {
                    "listing_status": "open",
                    "first_party_verified": "yes",
                    "apply_verified": "no",
                },
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["ok"], payload["status"]), (False, "rejected"))
        error = payload["result"]["error"]
        self.assertEqual(error["code"], "invariant_violation")
        self.assertEqual(error["field"], "operation.args.original_url")
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

    def test_medium_risk_status_records_user_confirmed_lifecycle_events(self):
        self.seed_job()
        operations = [
            (
                "op-status-applied-001",
                "not_started",
                {
                    "application_status": "applied",
                    "confirmed_by_user": True,
                    "applied_at": "2026-08-11",
                    "cv_version": "frontend-2026-08",
                    "next_action": "follow-up",
                },
            ),
            (
                "op-status-interview-001",
                "applied",
                {
                    "application_status": "interviewing",
                    "confirmed_by_user": True,
                    "stage": "Recruiter screen",
                    "response_at": "2026-08-12",
                    "next_action": "prepare recruiter screen",
                },
            ),
            (
                "op-status-offer-001",
                "interviewing",
                {
                    "application_status": "offer",
                    "confirmed_by_user": True,
                },
            ),
            (
                "op-status-rejected-001",
                "offer",
                {
                    "application_status": "rejected",
                    "confirmed_by_user": True,
                },
            ),
        ]
        for operation_id, expected_status, args in operations:
            request = self.write_operation(
                {
                    "version": 1,
                    "operation_id": operation_id,
                    "command": "status",
                    "job_id": "job-0001",
                    "expected": {"application_status": expected_status},
                    "args": args,
                }
            )
            result = self.invoke_operation("apply", str(request), "--format", "json")
            self.assertEqual(result.returncode, 0, result.stderr)
            payload = json.loads(result.stdout)
            self.assertEqual((payload["status"], payload["risk"]), ("completed", "medium"))
            self.assertEqual(payload["result"]["result"]["outcome"], "status_changed")

        row = self.rows()[0]
        self.assertEqual((row["application_status"], row["stage_reached"]), ("rejected", "Offer"))
        self.assertEqual((row["applied_at"], row["response_at"]), ("2026-08-11", "2026-08-12"))
        self.assertEqual((row["next_action"], row["next_action_date"]), ("", ""))

    def test_status_requires_explicit_user_confirmation(self):
        row = self.seed_job()
        before = (self.root / "data" / "jobs.csv").read_bytes()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-status-unconfirmed-001",
                "command": "status",
                "job_id": "job-0001",
                "expected": {"application_status": "not_started", "last_update": row["last_update"]},
                "args": {
                    "application_status": "applied",
                    "confirmed_by_user": False,
                },
            }
        )

        result = self.invoke_operation("validate", str(request), "--format", "json")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("confirmed_by_user must be true", result.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

    def test_atomic_batch_can_record_confirmed_ghosted_and_withdrawn_events(self):
        self.seed_job()
        created = self.invoke_jobs(
            "add",
            "--company",
            "Second OperationCo",
            "--role",
            "Frontend Developer",
            "--source",
            "Manual",
            "--force",
            "--no-file",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        for job_id in ("job-0001", "job-0002"):
            applied = self.invoke_jobs("status", job_id, "--application-status", "applied")
            self.assertEqual(applied.returncode, 0, applied.stderr)
        rows = self.rows()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "op-status-terminal-batch-001",
                "command": "batch",
                "atomic": True,
                "operations": [
                    {
                        "command": "status",
                        "job_id": "job-0001",
                        "expected": {"application_status": "applied", "last_update": rows[0]["last_update"]},
                        "args": {"application_status": "ghosted", "confirmed_by_user": True},
                    },
                    {
                        "command": "status",
                        "job_id": "job-0002",
                        "expected": {"application_status": "applied", "last_update": rows[1]["last_update"]},
                        "args": {"application_status": "withdrawn", "confirmed_by_user": True},
                    },
                ],
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "medium"))
        rows = self.rows()
        self.assertEqual(
            (rows[0]["application_status"], rows[0]["decision_reason"]), ("ghosted", "no_response_timeout")
        )
        self.assertEqual(
            (rows[1]["application_status"], rows[1]["decision_reason"]), ("withdrawn", "withdrawn_by_me")
        )


class ErrorTaxonomyTests(unittest.TestCase):
    """Every apply failure must leave a rejected result behind (docs/agent-write-path-plan-2026-09-07.md, Э1)."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in (
            "data",
            "applications",
            "scripts",
            "data/operations/requests",
            "data/operations/results",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in (
            "jobs.py",
            "tracker_paths.py",
            "tracker_schema.py",
            "tracker_validate.py",
            "tracker_write.py",
            "tracker_transaction.py",
            "tracker_ingest.py",
            "tracker_render.py",
            "tracker_cli.py",
            "tracker_time.py",
            "agent_operations.py",
        ):
            shutil.copy2(PROJECT / "scripts" / name, self.root / "scripts" / name)
        for name in ("jobs.csv", "job_sources.csv"):
            header = (PROJECT / "data" / name).read_text(encoding="utf-8").splitlines()[0]
            (self.root / "data" / name).write_text(header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke_jobs(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/jobs.py", *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def invoke_operation(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/agent_operations.py", *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def rows(self):
        with (self.root / "data" / "jobs.csv").open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def seed_job(self):
        created = self.invoke_jobs(
            "add",
            "--company",
            "OperationCo",
            "--role",
            "Frontend Developer",
            "--source",
            "Manual",
            "--no-file",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        return self.rows()[0]

    def write_request(self, operation_id, payload):
        path = self.root / "data" / "operations" / "requests" / f"{operation_id}.json"
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def apply_and_reject(self, operation_id, payload, before=None):
        """Apply a request expected to fail and return its rejected result payload."""
        request = self.write_request(operation_id, payload)
        result = self.invoke_operation("apply", str(request), "--format", "json")
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        response = json.loads(result.stdout)
        self.assertFalse(response["ok"])
        self.assertEqual(response["status"], "rejected")
        result_path = self.root / "data" / "operations" / "results" / f"{operation_id}.json"
        self.assertTrue(result_path.exists())
        on_disk = json.loads(result_path.read_text(encoding="utf-8"))
        self.assertEqual(on_disk["status"], "rejected")
        self.assertEqual(on_disk, response["result"])
        if before is not None:
            self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        return on_disk

    def test_dataset_race_returns_a_retryable_conflict(self):
        operation_id = "tax-dataset-race"
        request = self.write_request(
            operation_id,
            {
                "version": 1,
                "operation_id": operation_id,
                "command": "add",
                "args": {"company": "RaceCo", "role": "Frontend Developer", "source": "Manual"},
            },
        )
        stale = ops.jobs.ValidationError("stale dataset", code="stale_operation")
        with (
            patch.object(ops, "ROOT", self.root),
            patch.object(ops, "REQUESTS_DIR", self.root / "data/operations/requests"),
            patch.object(ops, "RESULTS_DIR", self.root / "data/operations/results"),
            patch.object(ops.jobs.PATHS, "root", self.root),
            patch.object(ops, "apply_add", side_effect=stale),
        ):
            result, result_path = ops.execute(request)
        self.assertEqual(result["status"], "conflict", result)
        self.assertEqual(result["result"]["reason"], "stale_operation")
        self.assertEqual(result["result"]["retry"]["args"]["company"], "RaceCo")
        self.assertEqual(json.loads(result_path.read_text(encoding="utf-8")), result)

    def test_every_wave_one_code_produces_a_matching_rejected_result(self):
        row = self.seed_job()
        before = (self.root / "data" / "jobs.csv").read_bytes()
        add_args = {
            "company": "TaxonomyCo",
            "role": "Frontend Developer",
            "source": "Manual",
            "found_at": "2026-09-07",
        }
        cases = [
            ("tax-invalid-json", "not json at all", "invalid_json", None),
            (
                "tax-too-large",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "tax-too-large",
                        "command": "add",
                        "args": {**add_args, "notes": "x" * 70_000},
                    }
                ),
                "request_too_large",
                None,
            ),
            (
                "tax-unsupported-command",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "tax-unsupported-command",
                        "command": "ingest",
                        "job_id": "job-0001",
                        "expected": {},
                        "args": {},
                    }
                ),
                "unsupported_command",
                "command",
            ),
            (
                "tax-unknown-top-level",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "tax-unknown-top-level",
                        "command": "add",
                        "args": add_args,
                        "extra": True,
                    }
                ),
                "unknown_top_level_fields",
                None,
            ),
            (
                "tax-missing-top-level",
                json.dumps({"version": 1, "operation_id": "tax-missing-top-level", "command": "add"}),
                "missing_top_level_fields",
                None,
            ),
            (
                "tax-unknown-args",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "tax-unknown-args",
                        "command": "add",
                        "args": {**add_args, "next_action": "follow up"},
                    }
                ),
                "unknown_args",
                "args.next_action",
            ),
            (
                "tax-missing-args",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "tax-missing-args",
                        "command": "add",
                        "args": {"company": "TaxonomyCo"},
                    }
                ),
                "missing_args",
                None,
            ),
            (
                "tax-bad-type",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "tax-bad-type",
                        "command": "add",
                        "args": {**add_args, "force": "yes"},
                    }
                ),
                "bad_type",
                "args.force",
            ),
            (
                "tax-bad-enum",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "tax-bad-enum",
                        "command": "add",
                        "args": {**add_args, "source": "NotASource"},
                    }
                ),
                "bad_enum_value",
                "args.source",
            ),
            (
                "tax-bad-format",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "tax-bad-format",
                        "command": "add",
                        "args": {**add_args, "posted_at": "07/09/2026"},
                    }
                ),
                "bad_format",
                "args.posted_at",
            ),
            (
                "tax-duplicate-extra-fields",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "tax-duplicate-extra-fields",
                        "command": "add",
                        "args": {
                            "company": "OperationCo",
                            "role": "Frontend Developer",
                            "source": "Manual",
                            "duplicate_of": row["id"],
                            "source_job_id": "dup-1",
                            "notes": "should be ignored",
                        },
                    }
                ),
                "duplicate_add_extra_fields",
                None,
            ),
            (
                "tax-batch-not-atomic",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "tax-batch-not-atomic",
                        "command": "batch",
                        "atomic": "true",
                        "operations": [],
                    }
                ),
                "batch_not_atomic",
                "atomic",
            ),
            (
                "tax-unknown-job",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "tax-unknown-job",
                        "command": "screen",
                        "job_id": "job-9999",
                        "expected": {"application_status": "not_started"},
                        "args": {"decision_reason": "geo_restriction"},
                    }
                ),
                "unknown_job",
                None,
            ),
            (
                "tax-filename-mismatch",
                json.dumps(
                    {
                        "version": 1,
                        "operation_id": "does-not-match-filename",
                        "command": "add",
                        "args": add_args,
                    }
                ),
                "filename_mismatch",
                None,
            ),
        ]
        for operation_id, raw_content, expected_code, expected_field in cases:
            with self.subTest(code=expected_code):
                path = self.root / "data" / "operations" / "requests" / f"{operation_id}.json"
                path.write_text(raw_content, encoding="utf-8")
                result = self.invoke_operation("apply", str(path), "--format", "json")
                self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
                response = json.loads(result.stdout)
                self.assertFalse(response["ok"])
                self.assertEqual(response["status"], "rejected")
                self.assertEqual(response["result"]["error"]["code"], expected_code)
                if expected_field is not None:
                    self.assertEqual(response["result"]["error"]["field"], expected_field)
                on_disk = json.loads(
                    (self.root / "data" / "operations" / "results" / f"{operation_id}.json").read_text(
                        encoding="utf-8"
                    ),
                )
                self.assertEqual(on_disk["status"], "rejected")
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

    def test_result_exists_blocks_retry_of_a_rejected_operation_without_a_new_id(self):
        payload = {
            "version": 1,
            "operation_id": "tax-retry-rejected",
            "command": "add",
            "args": {
                "company": "TaxonomyCo",
                "role": "Frontend Developer",
                "source": "Manual",
                "next_action": "follow up",
            },
        }
        self.apply_and_reject("tax-retry-rejected", payload)

        repeat = self.invoke_operation(
            "apply",
            str(self.root / "data" / "operations" / "requests" / "tax-retry-rejected.json"),
            "--format",
            "json",
        )
        self.assertEqual(repeat.returncode, 1)
        self.assertIn("already has a result", repeat.stderr)
        result_files = list((self.root / "data" / "operations" / "results").glob("tax-retry-rejected*.json"))
        self.assertEqual(len(result_files), 1)

    def test_closed_error_code_set_matches_the_documented_taxonomy(self):
        from scripts import agent_operations as ops

        documented = {
            "invalid_json",
            "request_too_large",
            "filename_mismatch",
            "unsupported_command",
            "unknown_top_level_fields",
            "missing_top_level_fields",
            "unknown_args",
            "missing_args",
            "bad_type",
            "bad_enum_value",
            "bad_format",
            "duplicate_add_extra_fields",
            "invariant_violation",
            "unknown_job",
            "result_exists",
            "batch_not_atomic",
            "lost_before_apply",
            "contract_violation",
        }
        self.assertEqual(ops.ERROR_CODES, documented)
        with self.assertRaises(ValueError):
            ops.contract_error("bad code", code="not_a_real_code")

    def test_jobs_layer_rejections_split_english_connector_message_from_russian_cli_text(self):
        """docs/agent-write-path-plan-2026-09-07.md, Э8: a jobs.py business-rule
        rejection (jobs.ValidationError) must speak English, hint-free of CLI
        flags, to the connector, while the CLI keeps its original Russian text
        with flags intact for the human operator."""
        row = self.seed_job()
        self.assertEqual(
            self.invoke_jobs("status", row["id"], "--application-status", "applied").returncode,
            0,
        )
        applied = self.rows()[0]

        cli_rejection = self.invoke_jobs("screen", row["id"], "--decision-reason", "geo_restriction")
        self.assertEqual(cli_rejection.returncode, 1)
        self.assertIn("только до фактической отправки", cli_rejection.stderr)

        rejected = self.apply_and_reject(
            "op-screen-after-applied-001",
            {
                "version": 1,
                "operation_id": "op-screen-after-applied-001",
                "command": "screen",
                "job_id": row["id"],
                "expected": {"application_status": "applied", "last_update": applied["last_update"]},
                "args": {"decision_reason": "geo_restriction"},
            },
        )
        error = rejected["error"]
        self.assertEqual(error["code"], "invariant_violation")
        self.assertEqual(error["layer"], "jobs")
        self.assertIn("actually submitted", error["message"])
        for text in (error["message"], error.get("hint", "")):
            self.assertNotRegex(text, r"--[a-zA-Z]", f"connector-facing text names a CLI flag: {text!r}")
            self.assertNotRegex(text, r"[Ѐ-ӿ]", f"connector-facing text is not English: {text!r}")

    def test_unconverted_jobs_systemexit_is_caught_as_invariant_violation(self):
        import unittest.mock as mock

        from scripts import agent_operations as ops
        from scripts import jobs

        with ops.temporary_tracker_workspace() as temp_root:
            requests_dir = temp_root / "data" / "operations" / "requests"
            results_dir = temp_root / "data" / "operations" / "results"
            requests_dir.mkdir(parents=True, exist_ok=True)
            row = jobs.load()[0]
            payload = {
                "version": 1,
                "operation_id": "tax-systemexit-safety-net",
                "command": "screen",
                "job_id": row["id"],
                "expected": {"application_status": row["application_status"]},
                "args": {"decision_reason": "geo_restriction"},
            }
            request_path = requests_dir / "tax-systemexit-safety-net.json"
            request_path.write_text(json.dumps(payload), encoding="utf-8")
            before = jobs.PATHS.csv_path.read_bytes()
            with (
                mock.patch.object(ops, "REQUESTS_DIR", requests_dir),
                mock.patch.object(ops, "RESULTS_DIR", results_dir),
                mock.patch.object(jobs, "screen_job", side_effect=SystemExit(1)),
            ):
                result, result_file = ops.execute(request_path)
            self.assertEqual(result["status"], "rejected")
            self.assertEqual(result["error"]["code"], "invariant_violation")
            self.assertEqual(result["error"]["layer"], "jobs")
            self.assertTrue(result_file.exists())
            self.assertEqual(jobs.PATHS.csv_path.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
