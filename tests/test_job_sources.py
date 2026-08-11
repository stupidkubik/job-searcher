import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
V1_FIXTURE = PROJECT / "tests" / "fixtures" / "jobs-v1.csv"


class JobSourcesTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in ("data", "applications", "scripts"):
            (self.root / directory).mkdir()
        shutil.copy2(PROJECT / "scripts" / "jobs.py", self.root / "scripts" / "jobs.py")
        for name in ("jobs.csv", "job_sources.csv"):
            header = (PROJECT / "data" / name).read_text(encoding="utf-8").splitlines()[0]
            (self.root / "data" / name).write_text(header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/jobs.py", *arguments], cwd=self.root,
            text=True, capture_output=True,
        )

    def rows(self, name):
        with (self.root / "data" / name).open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def add_linkedin(self, company, role, source_url, *extra):
        return self.invoke(
            "add", "--company", company, "--role", role, "--source", "LinkedIn",
            "--source-url", source_url, "--no-file", *extra,
        )

    def test_new_external_job_creates_primary_source_reference(self):
        created = self.add_linkedin("ReferenceCo", "Frontend Developer", "https://www.linkedin.com/jobs/view/100")
        self.assertEqual(created.returncode, 0, created.stderr)
        references = self.rows("job_sources.csv")
        self.assertEqual(len(references), 1)
        self.assertEqual(
            (references[0]["job_id"], references[0]["source"], references[0]["source_url"]),
            ("job-0001", "LinkedIn", "https://www.linkedin.com/jobs/view/100"),
        )

    def test_confirmed_duplicate_adds_reference_without_new_job_and_is_idempotent(self):
        self.assertEqual(self.add_linkedin("CanonicalCo", "Frontend Developer", "https://www.linkedin.com/jobs/view/101").returncode, 0)
        duplicate = self.add_linkedin(
            "CanonicalCo", "Frontend Developer", "https://www.linkedin.com/jobs/view/102",
            "--duplicate-of", "job-0001",
        )
        self.assertEqual(duplicate.returncode, 0, duplicate.stderr)
        self.assertEqual(len(self.rows("jobs.csv")), 1)
        self.assertEqual(len(self.rows("job_sources.csv")), 2)
        self.assertEqual(self.rows("job_sources.csv")[1]["job_id"], "job-0001")

        repeated = self.add_linkedin(
            "CanonicalCo", "Frontend Developer", "https://www.linkedin.com/jobs/view/102",
            "--duplicate-of", "job-0001",
        )
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(len(self.rows("jobs.csv")), 1)
        self.assertEqual(len(self.rows("job_sources.csv")), 2)

    def test_source_job_id_cannot_point_to_two_canonical_jobs(self):
        first = self.add_linkedin(
            "FirstCo", "Frontend Developer", "https://www.linkedin.com/jobs/view/201",
            "--source-job-id", "linkedin-201",
        )
        self.assertEqual(first.returncode, 0, first.stderr)
        before_jobs = (self.root / "data" / "jobs.csv").read_bytes()
        before_sources = (self.root / "data" / "job_sources.csv").read_bytes()
        conflicting = self.add_linkedin(
            "SecondCo", "Frontend Developer", "https://www.linkedin.com/jobs/view/202",
            "--source-job-id", "linkedin-201", "--force",
        )
        self.assertEqual(conflicting.returncode, 2)
        self.assertIn("source + source_job_id", conflicting.stdout)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before_jobs)
        self.assertEqual((self.root / "data" / "job_sources.csv").read_bytes(), before_sources)

    def test_shared_discovery_url_requires_explicit_force(self):
        self.assertEqual(self.add_linkedin("FirstCo", "Frontend Developer", "https://wellfound.com/jobs").returncode, 0)
        blocked = self.add_linkedin("SecondCo", "Frontend Developer", "https://wellfound.com/jobs")
        self.assertEqual(blocked.returncode, 2)
        self.assertIn("source_url уже принадлежит", blocked.stdout)
        forced = self.add_linkedin("SecondCo", "Frontend Developer", "https://wellfound.com/jobs", "--force")
        self.assertEqual(forced.returncode, 0, forced.stderr)
        self.assertEqual(len(self.rows("job_sources.csv")), 2)

    def test_backfill_redirects_legacy_duplicate_and_is_idempotent(self):
        shutil.copy2(V1_FIXTURE, self.root / "data" / "jobs.csv")
        self.assertEqual(self.invoke("migrate-v2").returncode, 0)
        preview = self.invoke("backfill-sources", "--check")
        self.assertEqual(preview.returncode, 0, preview.stderr)
        self.assertIn("создано references: 12", preview.stdout)
        self.assertEqual(len(self.rows("job_sources.csv")), 0)

        backfill = self.invoke("backfill-sources")
        self.assertEqual(backfill.returncode, 0, backfill.stderr)
        references = self.rows("job_sources.csv")
        self.assertEqual(len(references), 12)
        duplicate_reference = next(row for row in references if row["source_url"] == "https://source.test/11")
        self.assertEqual(duplicate_reference["job_id"], "job-0001")

        repeated = self.invoke("backfill-sources")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertIn("создано references: 0", repeated.stdout)
        self.assertEqual(len(self.rows("job_sources.csv")), 12)

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
