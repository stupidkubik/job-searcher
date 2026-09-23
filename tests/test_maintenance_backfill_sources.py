import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
V1_FIXTURE = PROJECT / "tests" / "fixtures" / "jobs-v1.csv"
BACKFILL_SCRIPT = "scripts/maintenance/backfill_sources.py"
MIGRATE_SCRIPT = "scripts/maintenance/migrate_v2.py"


class BackfillSourcesTests(unittest.TestCase):
    """docs/agent-write-path-plan-2026-09-07.md, Э9/G-12: backfill-sources is
    a one-time historical migration, not part of the ongoing CLI/connector
    surface."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        (self.root / "scripts" / "maintenance").mkdir(parents=True)
        (self.root / "applications").mkdir()
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
        ):
            shutil.copy2(PROJECT / "scripts" / name, self.root / "scripts" / name)
        for script in (BACKFILL_SCRIPT, MIGRATE_SCRIPT):
            shutil.copy2(PROJECT / script, self.root / script)
        source_header = (PROJECT / "data" / "job_sources.csv").read_text(encoding="utf-8").splitlines()[0]
        (self.root / "data" / "job_sources.csv").write_text(source_header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke_backfill(self, *arguments):
        return subprocess.run(
            [sys.executable, BACKFILL_SCRIPT, *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def invoke_migrate(self, *arguments):
        return subprocess.run(
            [sys.executable, MIGRATE_SCRIPT, *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def rows(self, name):
        with (self.root / "data" / name).open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def test_backfill_redirects_legacy_duplicate_and_is_idempotent(self):
        shutil.copy2(V1_FIXTURE, self.root / "data" / "jobs.csv")
        self.assertEqual(self.invoke_migrate().returncode, 0)
        preview = self.invoke_backfill("--check")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("references created: 12", preview.stdout)
        self.assertEqual(len(self.rows("job_sources.csv")), 0)

        backfill = self.invoke_backfill()
        self.assertEqual(backfill.returncode, 0, backfill.stderr)
        references = self.rows("job_sources.csv")
        self.assertEqual(len(references), 12)
        duplicate_reference = next(row for row in references if row["source_url"] == "https://source.test/11")
        self.assertEqual(duplicate_reference["job_id"], "job-0001")

        repeated = self.invoke_backfill()
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("references created: 0", repeated.stdout)
        self.assertEqual(len(self.rows("job_sources.csv")), 12)


if __name__ == "__main__":
    unittest.main()
