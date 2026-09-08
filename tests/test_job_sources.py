import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT = Path(__file__).resolve().parents[1]


class JobSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in ("data", "applications", "scripts"):
            (self.root / directory).mkdir()
        for name in ("jobs.py", "tracker_time.py"):
            shutil.copy2(PROJECT / "scripts" / name, self.root / "scripts" / name)
        for name in ("jobs.csv", "job_sources.csv"):
            header = (PROJECT / "data" / name).read_text(encoding="utf-8").splitlines()[0]
            (self.root / "data" / name).write_text(header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/jobs.py", *arguments],
            cwd=self.root,
            text=True,
            capture_output=True,
        )

    def rows(self, name):
        with (self.root / "data" / name).open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def add_linkedin(self, company, role, source_url, *extra):
        return self.invoke(
            "add",
            "--company",
            company,
            "--role",
            role,
            "--source",
            "LinkedIn",
            "--source-url",
            source_url,
            "--no-file",
            *extra,
        )

    def test_new_external_job_creates_primary_source_reference(self):
        created = self.add_linkedin(
            "ReferenceCo", "Frontend Developer", "https://www.linkedin.com/jobs/view/100"
        )
        self.assertEqual(created.returncode, 0, created.stderr)
        references = self.rows("job_sources.csv")
        self.assertEqual(len(references), 1)
        self.assertEqual(
            (references[0]["job_id"], references[0]["source"], references[0]["source_url"]),
            ("job-0001", "LinkedIn", "https://www.linkedin.com/jobs/view/100"),
        )

    def test_confirmed_duplicate_adds_reference_without_new_job_and_is_idempotent(self):
        self.assertEqual(
            self.add_linkedin(
                "CanonicalCo",
                "Frontend Developer",
                "https://www.linkedin.com/jobs/view/101",
                "--found-at",
                "2026-08-01",
            ).returncode,
            0,
        )
        duplicate = self.add_linkedin(
            "CanonicalCo",
            "Frontend Developer",
            "https://www.linkedin.com/jobs/view/102",
            "--duplicate-of",
            "job-0001",
        )
        self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
        self.assertEqual(len(self.rows("jobs.csv")), 1)
        self.assertEqual(len(self.rows("job_sources.csv")), 2)
        self.assertEqual(self.rows("job_sources.csv")[1]["job_id"], "job-0001")
        tracker_today = datetime.now(timezone.utc).astimezone(ZoneInfo("Europe/Belgrade")).date().isoformat()
        self.assertEqual(self.rows("job_sources.csv")[1]["found_at"], tracker_today)

        repeated = self.add_linkedin(
            "CanonicalCo",
            "Frontend Developer",
            "https://www.linkedin.com/jobs/view/102",
            "--duplicate-of",
            "job-0001",
        )
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(len(self.rows("jobs.csv")), 1)
        self.assertEqual(len(self.rows("job_sources.csv")), 2)

    def test_confirmed_duplicate_preserves_explicit_source_found_at(self):
        self.assertEqual(
            self.add_linkedin(
                "CanonicalCo",
                "Frontend Developer",
                "https://www.linkedin.com/jobs/view/111",
                "--found-at",
                "2026-08-01",
            ).returncode,
            0,
        )
        duplicate = self.add_linkedin(
            "CanonicalCo",
            "Frontend Developer",
            "https://www.linkedin.com/jobs/view/112",
            "--duplicate-of",
            "job-0001",
            "--found-at",
            "2026-08-13",
        )

        self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
        self.assertEqual(self.rows("job_sources.csv")[1]["found_at"], "2026-08-13")

    def test_source_job_id_cannot_point_to_two_canonical_jobs(self):
        first = self.add_linkedin(
            "FirstCo",
            "Frontend Developer",
            "https://www.linkedin.com/jobs/view/201",
            "--source-job-id",
            "linkedin-201",
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        before_jobs = (self.root / "data" / "jobs.csv").read_bytes()
        before_sources = (self.root / "data" / "job_sources.csv").read_bytes()
        conflicting = self.add_linkedin(
            "SecondCo",
            "Frontend Developer",
            "https://www.linkedin.com/jobs/view/202",
            "--source-job-id",
            "linkedin-201",
            "--force",
        )
        self.assertEqual(conflicting.returncode, 2)
        self.assertIn("source + source_job_id", conflicting.stdout)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before_jobs)
        self.assertEqual((self.root / "data" / "job_sources.csv").read_bytes(), before_sources)

    def test_shared_discovery_url_requires_explicit_force(self):
        self.assertEqual(
            self.add_linkedin("FirstCo", "Frontend Developer", "https://wellfound.com/jobs").returncode, 0
        )
        blocked = self.add_linkedin("SecondCo", "Frontend Developer", "https://wellfound.com/jobs")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("source_url уже принадлежит", blocked.stdout)
        forced = self.add_linkedin("SecondCo", "Frontend Developer", "https://wellfound.com/jobs", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual(len(self.rows("job_sources.csv")), 2)

    def test_validate_rejects_foreign_key(self):
        (self.root / "data" / "job_sources.csv").write_text(
            "job_id,source,source_url,source_job_id,found_at\n"
            "job-9999,LinkedIn,https://www.linkedin.com/jobs/view/999,,2026-08-11\n",
            encoding="utf-8",
        )
        validation = self.invoke("validate")
        self.assertEqual(validation.returncode, 1)
        self.assertIn("job_id не найден в jobs.csv", validation.stderr)


if __name__ == "__main__":
    unittest.main()
