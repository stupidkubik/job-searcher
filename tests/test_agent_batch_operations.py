import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class AgentBatchOperationsTests(unittest.TestCase):
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

    def invoke(self, script, *arguments):
        return subprocess.run(
            [sys.executable, script, *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def seed_job(self, company):
        created = self.invoke(
            "scripts/jobs.py",
            "add",
            "--company",
            company,
            "--role",
            "Frontend Developer",
            "--source",
            "Manual",
            "--no-file",
        )
        self.assertEqual(created.returncode, 0, created.stderr)

    def rows(self):
        with (self.root / "data" / "jobs.csv").open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def write_batch(self, operation_id, operations):
        request = {
            "version": 1,
            "operation_id": operation_id,
            "command": "batch",
            "atomic": True,
            "operations": operations,
        }
        path = self.root / "data" / "operations" / "requests" / f"{operation_id}.json"
        path.write_text(json.dumps(request), encoding="utf-8")
        return path.relative_to(self.root)

    def blocker(self, job_id, row, reason):
        return {
            "command": "verify",
            "job_id": job_id,
            "expected": {
                "application_status": row["application_status"],
                "last_update": row["last_update"],
            },
            "args": {
                "listing_status": "open",
                "first_party_verified": "no",
                "apply_verified": "no",
                "decision_reason": reason,
            },
        }

    def add_child(self, client_ref, company, source_job_id):
        return {
            "command": "add",
            "client_ref": client_ref,
            "args": {
                "company": company,
                "role": "Frontend Developer",
                "source": "Himalayas",
                "source_job_id": source_job_id,
                "decision_reason": "geo_restriction",
                "notes": "Remote is limited to the United States.",
            },
        }

    def test_atomic_batch_adds_allocate_ids_inside_one_transaction(self):
        request = self.write_batch(
            "batch-add-001",
            [
                self.add_child("himalayas:one", "OneCo", "himalayas-one"),
                self.add_child("himalayas:two", "TwoCo", "himalayas-two"),
            ],
        )

        result = self.invoke(
            "scripts/agent_operations.py",
            "apply",
            str(request),
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["status"], payload["risk"]), ("completed", "medium"))
        operations = payload["result"]["result"]["operations"]
        self.assertEqual(
            [(entry["client_ref"], entry["job_id"]) for entry in operations],
            [("himalayas:one", "job-0001"), ("himalayas:two", "job-0002")],
        )
        self.assertEqual([row["company"] for row in self.rows()], ["OneCo", "TwoCo"])

    def test_later_add_conflict_rolls_back_every_earlier_add(self):
        self.seed_job("ExistingCo")
        before_jobs = (self.root / "data" / "jobs.csv").read_bytes()
        before_sources = (self.root / "data" / "job_sources.csv").read_bytes()
        request = self.write_batch(
            "batch-add-conflict-001",
            [
                self.add_child("himalayas:new", "NewCo", "himalayas-new"),
                self.add_child("himalayas:duplicate", "ExistingCo", "himalayas-duplicate"),
            ],
        )

        result = self.invoke(
            "scripts/agent_operations.py",
            "apply",
            str(request),
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        details = payload["result"]["result"]
        self.assertEqual((payload["status"], details["reason"]), ("conflict", "batch_child_conflict"))
        self.assertEqual((details["index"], details["client_ref"]), (1, "himalayas:duplicate"))
        self.assertEqual(details["conflict"]["reason"], "unresolved_duplicate")
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before_jobs)
        self.assertEqual((self.root / "data" / "job_sources.csv").read_bytes(), before_sources)
        self.assertFalse(list((self.root / "applications").glob("job-0002-*.md")))

    def test_batch_rejects_duplicate_add_client_refs(self):
        child = self.add_child("himalayas:same", "OneCo", "himalayas-one")
        request = self.write_batch("batch-add-ref-conflict-001", [child, child])

        result = self.invoke(
            "scripts/agent_operations.py",
            "validate",
            str(request),
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("each add client_ref only once", result.stderr)

    def test_atomic_batch_applies_multiple_jobs_once(self):
        self.seed_job("OneCo")
        self.seed_job("TwoCo")
        before = self.rows()
        request = self.write_batch(
            "batch-apply-001",
            [
                self.blocker("job-0001", before[0], "geo_restriction"),
                self.blocker("job-0002", before[1], "seniority_too_high"),
            ],
        )

        result = self.invoke(
            "scripts/agent_operations.py",
            "apply",
            str(request),
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "completed")
        self.assertEqual(payload["result"]["result"]["outcome"], "atomic_batch_applied")
        self.assertEqual(payload["result"]["result"]["count"], 2)
        rows = self.rows()
        self.assertEqual(rows[0]["decision_reason"], "geo_restriction")
        self.assertEqual(rows[1]["decision_reason"], "seniority_too_high")

    def test_stale_child_conflicts_before_any_canonical_write(self):
        self.seed_job("OneCo")
        self.seed_job("TwoCo")
        before_rows = self.rows()
        before_bytes = (self.root / "data" / "jobs.csv").read_bytes()
        first = self.blocker("job-0001", before_rows[0], "geo_restriction")
        second = self.blocker("job-0002", before_rows[1], "geo_restriction")
        second["expected"]["application_status"] = "reviewing"
        request = self.write_batch("batch-conflict-001", [first, second])

        result = self.invoke(
            "scripts/agent_operations.py",
            "apply",
            str(request),
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "conflict")
        self.assertEqual(payload["result"]["result"]["reason"], "stale_operation")
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before_bytes)

    def test_runtime_failure_after_first_child_still_leaves_canonical_untouched(self):
        self.seed_job("OneCo")
        self.seed_job("TwoCo")
        rows = self.rows()
        before_bytes = (self.root / "data" / "jobs.csv").read_bytes()
        first = self.blocker("job-0001", rows[0], "geo_restriction")
        second = {
            "command": "set",
            "job_id": "job-0002",
            "expected": {
                "application_status": rows[1]["application_status"],
                "last_update": rows[1]["last_update"],
            },
            "args": {"listing_status": "closed"},
        }
        request = self.write_batch("batch-runtime-fail-001", [first, second])

        result = self.invoke(
            "scripts/agent_operations.py",
            "apply",
            str(request),
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["ok"], payload["status"]), (False, "rejected"))
        self.assertEqual(payload["result"]["error"]["code"], "invariant_violation")
        self.assertIn("allowed only after an application exists", payload["result"]["error"]["message"])
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before_bytes)
        result_files = list((self.root / "data" / "operations" / "results").glob("*.json"))
        self.assertEqual(len(result_files), 1)
        self.assertEqual(json.loads(result_files[0].read_text(encoding="utf-8"))["status"], "rejected")

    def test_batch_rejects_duplicate_job_ids(self):
        self.seed_job("OneCo")
        row = self.rows()[0]
        child = self.blocker("job-0001", row, "geo_restriction")
        request = self.write_batch("batch-duplicate-001", [child, child])

        result = self.invoke(
            "scripts/agent_operations.py",
            "validate",
            str(request),
            "--format",
            "json",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("each job_id only once", result.stderr)


class BatchAtomicityTests(unittest.TestCase):
    """Э4: atomic:false keeps whatever batch children succeed instead of
    rolling back the whole request over one bad child, atomic:true is capped
    at a much smaller size since it still discards everything on one
    conflict, and every conflicting child comes with a ready-to-resend retry
    fragment (docs/agent-write-path-plan-2026-09-07.md, Э4)."""

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

    def write_operation(self, operation):
        path = self.root / "data" / "operations" / "requests" / f"{operation['operation_id']}.json"
        path.write_text(json.dumps(operation), encoding="utf-8")
        return path

    def seed_job(self, company, role="Frontend Developer"):
        created = self.invoke_jobs(
            "add",
            "--company",
            company,
            "--role",
            role,
            "--source",
            "Manual",
            "--no-file",
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        return self.rows()[-1]

    def test_atomic_batch_over_the_ten_child_limit_is_rejected_by_contract(self):
        operations = [
            {
                "command": "screen",
                "job_id": "job-0001",
                "expected": {"application_status": "not_started"},
                "args": {"decision_reason": "geo_restriction"},
            }
            for _ in range(11)
        ]
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "atomic-over-limit",
                "command": "batch",
                "atomic": True,
                "operations": operations,
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "rejected")
        self.assertEqual(payload["result"]["error"]["code"], "bad_format")
        self.assertIn("atomic=false", payload["result"]["error"]["hint"])

    def test_non_atomic_batch_allows_up_to_a_hundred_children(self):
        operations = [
            {
                "command": "screen",
                "job_id": "job-0001",
                "expected": {"application_status": "not_started"},
                "args": {"decision_reason": "geo_restriction"},
            }
            for _ in range(101)
        ]
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "partial-over-limit",
                "command": "batch",
                "atomic": False,
                "operations": operations,
            }
        )

        result = self.invoke_operation("validate", str(request), "--format", "json")

        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exceeds 100 entries", result.stderr)

    def test_non_atomic_batch_applies_the_rest_when_one_add_child_conflicts(self):
        self.seed_job("Existing OperationCo")
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "partial-add-conflict",
                "command": "batch",
                "atomic": False,
                "operations": [
                    {
                        "command": "add",
                        "client_ref": "child-duplicate",
                        "args": {
                            "company": "Existing OperationCo",
                            "role": "Frontend Developer",
                            "source": "LinkedIn",
                            "source_url": "https://www.linkedin.com/jobs/view/111",
                        },
                    },
                    {
                        "command": "add",
                        "client_ref": "child-new",
                        "args": {
                            "company": "Second OperationCo",
                            "role": "Backend Developer",
                            "source": "LinkedIn",
                            "source_url": "https://www.linkedin.com/jobs/view/222",
                        },
                    },
                ],
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "partial")
        operations = payload["result"]["result"]["operations"]
        statuses = {op["client_ref"]: op["status"] for op in operations}
        self.assertEqual(statuses, {"child-duplicate": "conflict", "child-new": "completed"})
        self.assertEqual(payload["result"]["result"]["count"], 1)
        self.assertEqual(payload["result"]["result"]["total"], 2)
        self.assertEqual(len(self.rows()), 2)  # the seeded job plus child-new only

        conflict = next(op for op in operations if op["client_ref"] == "child-duplicate")
        retry = conflict["conflict"]["retry"]
        self.assertIn("as_duplicate", retry)
        self.assertIn("as_separate", retry)
        self.assertEqual(retry["as_duplicate"]["args"]["duplicate_of"], "job-0001")
        self.assertTrue(retry["as_separate"]["args"]["force"])

        from scripts import agent_operations as ops

        ops.validate_child(retry["as_duplicate"])
        ops.validate_child(retry["as_separate"])

    def test_non_atomic_batch_skips_a_stale_child_and_offers_a_refreshed_retry(self):
        first = self.seed_job("Stale One Co")
        second = self.seed_job("Stale Two Co", role="Backend Developer")
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "partial-stale-conflict",
                "command": "batch",
                "atomic": False,
                "operations": [
                    {
                        "command": "screen",
                        "job_id": first["id"],
                        "expected": {
                            "application_status": "not_started",
                            "last_update": first["last_update"],
                        },
                        "args": {"decision_reason": "geo_restriction"},
                    },
                    {
                        "command": "screen",
                        "job_id": second["id"],
                        "expected": {"application_status": "not_started", "last_update": "2000-01-01"},
                        "args": {"decision_reason": "seniority_too_high"},
                    },
                ],
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "partial")
        operations = payload["result"]["result"]["operations"]
        applied = next(op for op in operations if op["job_id"] == first["id"])
        conflict = next(op for op in operations if op["job_id"] == second["id"])
        self.assertEqual(applied["status"], "completed")
        self.assertEqual((conflict["status"], conflict["reason"]), ("conflict", "stale_operation"))
        self.assertEqual(conflict["retry"]["expected"]["last_update"], second["last_update"])

        from scripts import agent_operations as ops

        ops.validate_child(conflict["retry"])

        rows_by_id = {row["id"]: row for row in self.rows()}
        self.assertEqual(rows_by_id[first["id"]]["decision_reason"], "geo_restriction")
        self.assertEqual(rows_by_id[second["id"]]["decision_reason"], "")

    def test_non_atomic_batch_with_every_child_conflicting_changes_nothing(self):
        self.seed_job("Solo Existing Co")
        before = (self.root / "data" / "jobs.csv").read_bytes()
        request = self.write_operation(
            {
                "version": 1,
                "operation_id": "partial-all-conflict",
                "command": "batch",
                "atomic": False,
                "operations": [
                    {
                        "command": "add",
                        "client_ref": "only-child",
                        "args": {
                            "company": "Solo Existing Co",
                            "role": "Frontend Developer",
                            "source": "LinkedIn",
                            "source_url": "https://www.linkedin.com/jobs/view/999",
                        },
                    },
                ],
            }
        )

        result = self.invoke_operation("apply", str(request), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["status"], "conflict")
        self.assertEqual(payload["result"]["result"]["outcome"], "batch_fully_conflicted")
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
