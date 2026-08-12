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

    def source_rows(self):
        with (self.root / "data" / "job_sources.csv").open(newline="", encoding="utf-8") as file:
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

    def test_workflow_supports_explicit_main_operations_without_a_review_pr(self):
        workflow = WORKFLOW.read_text(encoding="utf-8")
        self.assertIn("      - main", workflow)
        self.assertIn('if: github.ref_name != \'main\'', workflow)
        self.assertIn('["git", "diff", "--name-status", base, "HEAD"]', workflow)

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

    def test_medium_risk_add_creates_job_provenance_card_and_result(self):
        request = self.write_operation({
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
        })

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
        request = self.write_operation({
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
        })

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["result"]["result"]["application_path"], None)
        self.assertEqual(self.rows()[0]["decision_reason"], "geo_restriction")
        self.assertFalse(list((self.root / "applications").glob("job-0001-*.md")))

    def test_add_records_unresolved_duplicate_as_immutable_conflict(self):
        self.seed_job()
        before = (self.root / "data" / "jobs.csv").read_bytes()
        request = self.write_operation({
            "version": 1,
            "operation_id": "op-add-conflict-001",
            "command": "add",
            "args": {
                "company": "OperationCo",
                "role": "Frontend Developer",
                "source": "LinkedIn",
                "source_url": "https://www.linkedin.com/jobs/view/duplicate",
            },
        })

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("conflict", "medium"))
        self.assertEqual(payload["result"]["result"]["reason"], "unresolved_duplicate")
        self.assertEqual(payload["result"]["result"]["candidates"][0]["id"], "job-0001")
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        self.assertTrue((self.root / payload["result_path"]).exists())

    def test_add_can_attach_a_confirmed_duplicate_source_reference(self):
        self.seed_job()
        request = self.write_operation({
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
        })

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["result"]["result"]["outcome"], "source_reference_added")
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.source_rows()[0]["job_id"], "job-0001")

    def test_add_rejects_human_only_status_and_missing_external_reference(self):
        human_only = self.write_operation({
            "version": 1,
            "operation_id": "op-add-applied-001",
            "command": "add",
            "args": {
                "company": "UnsafeCo",
                "role": "Frontend Developer",
                "source": "Manual",
                "application_status": "applied",
            },
        })
        missing_reference = self.write_operation({
            "version": 1,
            "operation_id": "op-add-no-source-001",
            "command": "add",
            "args": {
                "company": "NoSourceCo",
                "role": "Frontend Developer",
                "source": "LinkedIn",
            },
        })

        first = self.invoke_operation("validate", str(human_only), "--format", "json")
        second = self.invoke_operation("validate", str(missing_reference), "--format", "json")

        self.assertNotEqual(first.returncode, 0)
        self.assertIn("only to not_started or reviewing", first.stderr)
        self.assertNotEqual(second.returncode, 0)
        self.assertIn("requires source_url or source_job_id", second.stderr)
        self.assertEqual(self.rows(), [])

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

    def test_low_risk_screen_preserves_listing_and_verification_fields(self):
        row = self.seed_job()
        request = self.write_operation({
            "version": 1,
            "operation_id": "op-screen-001",
            "command": "screen",
            "job_id": "job-0001",
            "expected": {"application_status": "not_started", "listing_status": "unknown"},
            "args": {
                "decision_reason": "geo_restriction",
                "notes": "Himalayas restricts this role to Latin America.",
            },
        })

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "low"))
        updated = self.rows()[0]
        self.assertEqual((updated["application_status"], updated["decision_reason"]), ("not_started", "geo_restriction"))
        for field in ("listing_status", "verified_at", "first_party_verified", "apply_verified"):
            self.assertEqual(updated[field], row[field])

    def test_atomic_batch_applies_multiple_screen_decisions_once(self):
        first = self.seed_job()
        created = self.invoke_jobs(
            "add", "--company", "Second OperationCo", "--role", "Frontend Developer",
            "--source", "Manual", "--force", "--no-file",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        second = self.rows()[1]
        request = self.write_operation({
            "version": 1,
            "operation_id": "op-screen-batch-001",
            "command": "batch",
            "atomic": True,
            "operations": [
                {
                    "command": "screen",
                    "job_id": "job-0001",
                    "expected": {"application_status": "not_started", "last_update": first["last_update"]},
                    "args": {"decision_reason": "geo_restriction"},
                },
                {
                    "command": "screen",
                    "job_id": "job-0002",
                    "expected": {"application_status": "not_started", "last_update": second["last_update"]},
                    "args": {"decision_reason": "seniority_too_high"},
                },
            ],
        })

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
            "add", "--company", "Applied OperationCo", "--role", "Frontend Developer",
            "--source", "Manual", "--force", "--no-file",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        self.assertEqual(self.invoke_jobs("set", "job-0002", "application_status=applied").returncode, 0)
        second = self.rows()[1]
        before = (self.root / "data" / "jobs.csv").read_bytes()
        request = self.write_operation({
            "version": 1,
            "operation_id": "op-screen-batch-reject-001",
            "command": "batch",
            "atomic": True,
            "operations": [
                {
                    "command": "screen",
                    "job_id": "job-0001",
                    "expected": {"application_status": "not_started", "last_update": first["last_update"]},
                    "args": {"decision_reason": "geo_restriction"},
                },
                {
                    "command": "screen",
                    "job_id": "job-0002",
                    "expected": {"application_status": "applied", "last_update": second["last_update"]},
                    "args": {"decision_reason": "seniority_too_high"},
                },
            ],
        })

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 1)
        self.assertIn("только до фактической отправки", result.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        self.assertFalse((self.root / "data" / "operations" / "results" / "op-screen-batch-reject-001.json").exists())

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

    def test_medium_risk_status_records_user_confirmed_lifecycle_events(self):
        self.seed_job()
        operations = [
            ("op-status-applied-001", "not_started", {
                "application_status": "applied",
                "confirmed_by_user": True,
                "applied_at": "2026-08-11",
                "cv_version": "frontend-2026-08",
                "next_action": "follow-up",
            }),
            ("op-status-interview-001", "applied", {
                "application_status": "interviewing",
                "confirmed_by_user": True,
                "stage": "Recruiter screen",
                "response_at": "2026-08-12",
                "next_action": "prepare recruiter screen",
            }),
            ("op-status-offer-001", "interviewing", {
                "application_status": "offer",
                "confirmed_by_user": True,
            }),
            ("op-status-rejected-001", "offer", {
                "application_status": "rejected",
                "confirmed_by_user": True,
            }),
        ]
        for operation_id, expected_status, args in operations:
            request = self.write_operation({
                "version": 1,
                "operation_id": operation_id,
                "command": "status",
                "job_id": "job-0001",
                "expected": {"application_status": expected_status},
                "args": args,
            })
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
        request = self.write_operation({
            "version": 1,
            "operation_id": "op-status-unconfirmed-001",
            "command": "status",
            "job_id": "job-0001",
            "expected": {"application_status": "not_started", "last_update": row["last_update"]},
            "args": {
                "application_status": "applied",
                "confirmed_by_user": False,
            },
        })

        result = self.invoke_operation("validate", str(request), "--format", "json")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("confirmed_by_user must be true", result.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

    def test_atomic_batch_can_record_confirmed_ghosted_and_withdrawn_events(self):
        self.seed_job()
        created = self.invoke_jobs(
            "add", "--company", "Second OperationCo", "--role", "Frontend Developer",
            "--source", "Manual", "--force", "--no-file",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        for job_id in ("job-0001", "job-0002"):
            applied = self.invoke_jobs("status", job_id, "--application-status", "applied")
            self.assertEqual(applied.returncode, 0, applied.stderr)
        rows = self.rows()
        request = self.write_operation({
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
        })

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "medium"))
        rows = self.rows()
        self.assertEqual((rows[0]["application_status"], rows[0]["decision_reason"]), ("ghosted", "no_response_timeout"))
        self.assertEqual((rows[1]["application_status"], rows[1]["decision_reason"]), ("withdrawn", "withdrawn_by_me"))


if __name__ == "__main__":
    unittest.main()
