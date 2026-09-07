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
            "data", "applications", "scripts",
            "data/operations/requests", "data/operations/results",
        ):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        for name in ("jobs.py", "agent_operations.py", "tracker_time.py"):
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
            cwd=self.root, text=True, capture_output=True,
        )

    def seed_job(self, company):
        created = self.invoke(
            "scripts/jobs.py", "add",
            "--company", company,
            "--role", "Frontend Developer",
            "--source", "Manual",
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
            "scripts/agent_operations.py", "apply", str(request), "--format", "json",
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
            "scripts/agent_operations.py", "apply", str(request), "--format", "json",
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
            "scripts/agent_operations.py", "validate", str(request), "--format", "json",
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
            "scripts/agent_operations.py", "apply", str(request), "--format", "json",
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
            "scripts/agent_operations.py", "apply", str(request), "--format", "json",
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
            "scripts/agent_operations.py", "apply", str(request), "--format", "json",
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
            "scripts/agent_operations.py", "validate", str(request), "--format", "json",
        )

        self.assertEqual(result.returncode, 1)
        self.assertIn("each job_id only once", result.stderr)


if __name__ == "__main__":
    unittest.main()
