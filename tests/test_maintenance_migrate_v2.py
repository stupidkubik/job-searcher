import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
V1_FIXTURE = PROJECT / "tests" / "fixtures" / "jobs-v1.csv"
SCRIPT = "scripts/maintenance/migrate_v2.py"
V1_STATUS_MAPPING = {
    "New": ("not_started", "unknown"),
    "Reviewing": ("reviewing", "unknown"),
    "Apply": ("apply", "unknown"),
    "Applied": ("applied", "unknown"),
    "Interviewing": ("interviewing", "unknown"),
    "Offer": ("offer", "unknown"),
    "Rejected": ("rejected", "unknown"),
    "Ghosted": ("ghosted", "unknown"),
    "Skipped": ("not_started", "unknown"),
    "Closed": ("not_started", "closed"),
    "Duplicate": ("not_started", "unknown"),
    "Withdrawn": ("withdrawn", "unknown"),
}


class MigrateV2Tests(unittest.TestCase):
    """docs/agent-write-path-plan-2026-09-07.md, Э9/G-12: migrate-v2 is a
    disaster-recovery tool, not part of the ongoing CLI/connector surface."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        (self.root / "scripts" / "maintenance").mkdir(parents=True)
        (self.root / "applications").mkdir()
        for name in ("jobs.py", "tracker_time.py"):
            shutil.copy2(PROJECT / "scripts" / name, self.root / "scripts" / name)
        shutil.copy2(PROJECT / SCRIPT, self.root / SCRIPT)
        shutil.copy2(V1_FIXTURE, self.root / "data" / "jobs.csv")
        source_header = (PROJECT / "data" / "job_sources.csv").read_text(encoding="utf-8").splitlines()[0]
        (self.root / "data" / "job_sources.csv").write_text(source_header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke_migrate(self, *arguments):
        return subprocess.run(
            [sys.executable, SCRIPT, *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def invoke_jobs(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/jobs.py", *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def rows(self):
        import csv

        with (self.root / "data" / "jobs.csv").open(newline="", encoding="utf-8") as file:
            return {row["id"]: row for row in csv.DictReader(file)}

    def test_migrate_v2_check_is_read_only_and_maps_every_legacy_status(self):
        before = (self.root / "data" / "jobs.csv").read_bytes()
        check = self.invoke_migrate("--check")
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertIn("rows: 12", check.stdout)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

        migrate = self.invoke_migrate()
        self.assertEqual(migrate.returncode, 0, migrate.stderr)
        rows = self.rows()
        self.assertEqual(len(rows), 12)
        for index, (legacy_status, expected) in enumerate(V1_STATUS_MAPPING.items(), start=1):
            with self.subTest(legacy_status=legacy_status):
                row = rows[f"job-{index:04d}"]
                self.assertEqual((row["application_status"], row["listing_status"]), expected)
                self.assertEqual(
                    (row["verified_at"], row["first_party_verified"], row["apply_verified"]),
                    ("", "unknown", "unknown"),
                )
        self.assertEqual(rows["job-0010"]["decision_reason"], "closed_before_application")
        self.assertEqual(rows["job-0011"]["decision_reason"], "duplicate_listing")
        validation = self.invoke_jobs("validate", "--strict")
        self.assertEqual(validation.returncode, 0, validation.stderr)
        repeated = self.invoke_migrate("--check")
        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("already uses the v2 schema", repeated.stderr)


if __name__ == "__main__":
    unittest.main()
