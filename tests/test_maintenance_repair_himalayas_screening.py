import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/maintenance/repair_himalayas_screening.py"


class RepairHimalayasScreeningTests(unittest.TestCase):
    """docs/agent-write-path-plan-2026-09-07.md, Э9/G-12:
    repair-himalayas-screening targets one closed incident and is not part
    of the ongoing CLI/connector surface."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        (self.root / "scripts" / "maintenance").mkdir(parents=True)
        (self.root / "applications").mkdir()
        for name in ("jobs.py", "tracker_time.py"):
            shutil.copy2(PROJECT / "scripts" / name, self.root / "scripts" / name)
        shutil.copy2(PROJECT / SCRIPT, self.root / SCRIPT)
        for name in ("jobs.csv", "job_sources.csv"):
            header = (PROJECT / "data" / name).read_text(encoding="utf-8").splitlines()[0]
            (self.root / "data" / name).write_text(header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke_repair(self, *arguments):
        return subprocess.run(
            [sys.executable, SCRIPT, *arguments], cwd=self.root,
            text=True, capture_output=True,
        )

    def invoke_jobs(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/jobs.py", *arguments], cwd=self.root,
            text=True, capture_output=True,
        )

    def rows(self):
        with (self.root / "data" / "jobs.csv").open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def install_himalayas_screening_batch(self):
        with (self.root / "data" / "jobs.csv").open(newline="", encoding="utf-8") as file:
            fields = csv.DictReader(file).fieldnames
        exclusions = {"job-0102", "job-0110", "job-0111", "job-0124"}
        rows = []
        for number in range(99, 127):
            job_id = f"job-{number:04d}"
            row = {field: "" for field in fields}
            row.update({
                "id": job_id,
                "application_status": "not_started",
                "listing_status": "open",
                "company": f"Himalayas Co {number}",
                "role": "Frontend Developer",
                "level": "Unknown",
                "source": "Himalayas",
                "remote_policy": "Unclear",
                "salary": "Unknown",
                "found_at": "2026-08-11",
                "stage_reached": "None",
                "decision_reason": "geo_restriction",
                "verified_at": "2026-08-11",
                "first_party_verified": "no",
                "apply_verified": "no",
                "last_update": "2026-08-11",
                "notes": f"Preserve note {number}",
            })
            if job_id in exclusions:
                row["original_url"] = f"https://careers.example.test/{job_id}"
                row["first_party_verified"] = "yes"
                if job_id == "job-0102":
                    row["listing_status"] = "closed"
                    row["decision_reason"] = "closed_before_application"
                else:
                    row["apply_verified"] = "yes"
                if job_id == "job-0124":
                    row["application_status"] = "apply"
                    row["decision_reason"] = ""
                    row["next_action"] = "Prepare application"
            rows.append(row)
        with (self.root / "data" / "jobs.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)

    def test_himalayas_screening_repair_is_exact_and_idempotent(self):
        self.install_himalayas_screening_batch()
        before_bytes = (self.root / "data" / "jobs.csv").read_bytes()
        before = {row["id"]: row for row in self.rows()}
        excluded_ids = {"job-0102", "job-0110", "job-0111", "job-0124"}
        target_ids = set(before) - excluded_ids

        check = self.invoke_repair("--check", "--format", "json")
        self.assertEqual(check.returncode, 0, check.stderr)
        check_payload = json.loads(check.stdout)
        self.assertEqual(check_payload["status"], "ready")
        self.assertEqual(check_payload["target_count"], 24)
        self.assertEqual(set(check_payload["target_ids"]), target_ids)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before_bytes)

        repair = self.invoke_repair("--format", "json")
        self.assertEqual(repair.returncode, 0, repair.stderr)
        self.assertEqual(json.loads(repair.stdout)["changed"], 24)
        after = {row["id"]: row for row in self.rows()}
        for job_id in target_ids:
            self.assertEqual(
                {key: after[job_id][key] for key in (
                    "listing_status", "first_party_verified", "apply_verified", "verified_at",
                )},
                {
                    "listing_status": "unknown",
                    "first_party_verified": "unknown",
                    "apply_verified": "unknown",
                    "verified_at": "",
                },
            )
            changed = {key for key in before[job_id] if before[job_id][key] != after[job_id][key]}
            self.assertEqual(
                changed,
                {"listing_status", "first_party_verified", "apply_verified", "verified_at"},
            )
            self.assertEqual(after[job_id]["decision_reason"], before[job_id]["decision_reason"])
            self.assertEqual(after[job_id]["notes"], before[job_id]["notes"])
        for job_id in excluded_ids:
            self.assertEqual(after[job_id], before[job_id])

        repeated = self.invoke_repair("--format", "json")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["status"], "already_applied")
        self.assertEqual(json.loads(repeated.stdout)["changed"], 0)
        validation = self.invoke_jobs("validate", "--strict")
        self.assertEqual(validation.returncode, 0, validation.stderr)

    def test_himalayas_screening_repair_rejects_mixed_state_without_writing(self):
        self.install_himalayas_screening_batch()
        rows = self.rows()
        rows[0]["first_party_verified"] = "yes"
        fields = list(rows[0])
        with (self.root / "data" / "jobs.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        before = (self.root / "data" / "jobs.csv").read_bytes()

        repair = self.invoke_repair("--format", "json")

        self.assertNotEqual(repair.returncode, 0)
        self.assertIn("mixed or unexpected state", repair.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
