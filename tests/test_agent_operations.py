import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
WORKFLOW = PROJECT / ".github" / "workflows" / "agent-operations.yml"


class AgentOperationsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in (
            "data", "applications", "scripts", "data/operations/requests", "data/operations/results",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in ("jobs.py", "agent_operations.py"):
            shutil.copy2(PROJECT / "scripts" / name, self.root / "scripts" / name)
        for name in ("jobs.csv", "job_sources.csv"):
            header = (PROJECT / "data" / name).read_text(encoding="utf-8").splitlines()[0]
            (self.root / "data" / name).write_text(header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke_jobs(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/jobs.py", *arguments], cwd=self.root,
            text=True, capture_output=True,
        )

    def invoke_operation(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/agent_operations.py", *arguments], cwd=self.root,
            text=True, capture_output=True,
        )

    def rows(self):
        with (self.root / "data" / "jobs.csv").open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def seed_job(self):
        created = self.invoke_jobs(
            "add", "--company", "OperationCo", "--role", "Frontend Developer",
            "--source", "Manual", "--no-file",
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

    def test_workflow_discovers_a_push_request_from_the_branch_diff(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('["git", "diff", "--name-only", "origin/main...HEAD"]', workflow)
        self.assertNotIn('event.get("head_commit", {}).get("added", [])', workflow)

    def test_workflow_pr_body_stays_inside_the_run_block(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('            Risk: ${RISK}', workflow)
        self.assertIn('            Status: ${STATUS}', workflow)
        self.assertIn('            Validation: passed', workflow)
        self.assertIn('            Tests: passed"', workflow)

    def test_workflow_keeps_its_operation_output_outside_the_checkout(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn('> "$RUNNER_TEMP/operation-output.json"', workflow)
        self.assertIn('os.environ["RUNNER_TEMP"], "operation-output.json"', workflow)
        self.assertNotIn('> operation-output.json', workflow)

    def test_low_risk_verify_uses_jobs_write_path_and_records_immutable_result(self):
        row = self.seed_job()
        request = self.write_operation({
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
        })

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
        request = self.write_operation({
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
        })

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "medium"))
        updated = self.rows()[0]
        self.assertEqual(
            (updated["application_status"], updated["level"], updated["remote_policy"], updated["match_score"]),
            ("reviewing", "Junior", "Europe", "8.5"),
        )
        self.assertTrue(list((self.root / "applications").glob("job-0001-*.md")))

    def test_medium_risk_verify_can_record_a_human_started_application(self):
        row = self.seed_job()
        request = self.write_operation({
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
        })

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
        request = self.write_operation({
            "version": 1,
            "operation_id": "op-conflict-001",
            "command": "set",
            "job_id": "job-0001",
            "expected": {"application_status": "reviewing", "last_update": row["last_update"]},
            "args": {"next_action": "verify first-party"},
        })

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("conflict", "low"))
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        self.assertEqual(payload["result"]["result"]["reason"], "stale_operation")

    def test_allowlisted_set_can_schedule_the_next_safe_action(self):
        row = self.seed_job()
        request = self.write_operation({
            "version": 1,
            "operation_id": "op-next-action-001",
            "command": "set",
            "job_id": "job-0001",
            "expected": {"application_status": "not_started", "last_update": row["last_update"]},
            "args": {
                "next_action": "verify first-party",
                "next_action_date": "2026-08-12",
            },
        })

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "low"))
        self.assertEqual(
            (self.rows()[0]["next_action"], self.rows()[0]["next_action_date"]),
            ("verify first-party", "2026-08-12"),
        )

    def test_verify_rejects_human_only_application_statuses_before_writing(self):
        row = self.seed_job()
        before = (self.root / "data" / "jobs.csv").read_bytes()
        request = self.write_operation({
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
        })

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 1)
        self.assertIn("verify may set application_status only to apply", result.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        self.assertFalse(list((self.root / "data" / "operations" / "results").glob("*.json")))


if __name__ == "__main__":
    unittest.main()
