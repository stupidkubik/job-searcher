import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
SCRIPT = "scripts/maintenance/backfill_original_url.py"


class BackfillOriginalUrlTests(unittest.TestCase):
    """docs/agent-write-path-plan-2026-09-07.md, Э5/G-7(B): fill original_url
    only where the source already is the first-party listing, idempotently,
    and without touching rows that already carry a value."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        (self.root / "scripts" / "maintenance").mkdir(parents=True)
        (self.root / "applications").mkdir()
        for name in ("jobs.py", "tracker_time.py"):
            shutil.copy2(PROJECT / "scripts" / name, self.root / "scripts" / name)
        shutil.copy2(
            PROJECT / "scripts" / "maintenance" / "backfill_original_url.py",
            self.root / "scripts" / "maintenance" / "backfill_original_url.py",
        )
        for name in ("jobs.csv", "job_sources.csv"):
            header = (PROJECT / "data" / name).read_text(encoding="utf-8").splitlines()[0]
            (self.root / "data" / name).write_text(header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke_jobs(self, *arguments):
        result = subprocess.run(
            [sys.executable, "scripts/jobs.py", *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return result

    def invoke_backfill(self, *arguments):
        return subprocess.run(
            [sys.executable, SCRIPT, *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def rows(self):
        with (self.root / "data" / "jobs.csv").open(newline="", encoding="utf-8") as file:
            return {row["id"]: row for row in csv.DictReader(file)}

    def test_backfill_fills_only_first_party_source_rows_and_is_idempotent(self):
        self.invoke_jobs(
            "add",
            "--company",
            "FirstPartyCo",
            "--role",
            "Frontend Developer",
            "--source",
            "Company Careers",
            "--source-url",
            "https://careers.firstpartyco.example/jobs/1",
            "--no-file",
        )
        self.invoke_jobs(
            "add",
            "--company",
            "AlreadySetCo",
            "--role",
            "Frontend Developer",
            "--source",
            "Company Careers",
            "--source-url",
            "https://careers.alreadysetco.example/jobs/2",
            "--original-url",
            "https://careers.alreadysetco.example/jobs/2-canonical",
            "--no-file",
        )
        self.invoke_jobs(
            "add",
            "--company",
            "AggregatorCo",
            "--role",
            "Frontend Developer",
            "--source",
            "LinkedIn",
            "--source-url",
            "https://www.linkedin.com/jobs/view/3",
            "--no-file",
        )
        before = (self.root / "data" / "jobs.csv").read_bytes()

        dry_run = self.invoke_backfill("--dry-run", "--format", "json")
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        dry_payload = json.loads(dry_run.stdout)
        self.assertEqual(dry_payload["dry_run"], True)
        self.assertEqual([entry["id"] for entry in dry_payload["changed"]], ["job-0001"])
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

        applied = self.invoke_backfill("--format", "json")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        applied_payload = json.loads(applied.stdout)
        self.assertEqual([entry["id"] for entry in applied_payload["changed"]], ["job-0001"])

        rows = self.rows()
        self.assertEqual(rows["job-0001"]["original_url"], "https://careers.firstpartyco.example/jobs/1")
        self.assertEqual(
            rows["job-0002"]["original_url"], "https://careers.alreadysetco.example/jobs/2-canonical"
        )
        self.assertEqual(rows["job-0003"]["original_url"], "")

        after_first_apply = (self.root / "data" / "jobs.csv").read_bytes()
        repeated = self.invoke_backfill("--format", "json")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["changed"], [])
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), after_first_apply)


if __name__ == "__main__":
    unittest.main()
