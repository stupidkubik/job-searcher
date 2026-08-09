import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class JobsCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in ("data", "applications", "scripts"):
            (self.root / directory).mkdir()
        shutil.copy2(PROJECT / "scripts" / "jobs.py", self.root / "scripts" / "jobs.py")
        header = (PROJECT / "data" / "jobs.csv").read_text(encoding="utf-8").splitlines()[0]
        (self.root / "data" / "jobs.csv").write_text(header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *arguments):
        return subprocess.run(
            [sys.executable, "scripts/jobs.py", *arguments], cwd=self.root,
            text=True, capture_output=True,
        )

    def rows(self):
        with (self.root / "data" / "jobs.csv").open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def add(self, company="ExampleCo", role="Frontend Developer", *extra):
        return self.invoke("add", "--company", company, "--role", role, "--source", "Manual", *extra)

    def test_empty_database_validates(self):
        result = self.invoke("validate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("проверено записей: 0; ошибок: 0", result.stdout)

    def test_new_job_board_sources_are_accepted(self):
        for source in ("Welcome to the Jungle", "We Work Remotely"):
            result = self.invoke(
                "add", "--company", f"{source} Co", "--role", "Frontend Developer",
                "--source", source, "--no-file",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_add_issues_id_and_creates_application_file(self):
        result = self.add("Example Co", "Frontend Engineer", "--status", "Reviewing")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows()[0]["id"], "job-0001")
        cards = list((self.root / "applications").glob("job-0001-*.md"))
        self.assertEqual(len(cards), 1)
        self.assertIn("company: Example Co", cards[0].read_text(encoding="utf-8"))

    def test_skipped_add_does_not_create_card(self):
        result = self.add("BlockedCo", "Frontend Developer", "--status", "Skipped", "--decision-reason", "geo_restriction")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows()[0]["status"], "Skipped")
        self.assertFalse(list((self.root / "applications").glob("job-*.md")))

    def test_canonical_url_duplicate_requires_explicit_decision(self):
        self.assertEqual(self.add("ExeQut", "Front-End Software Developer", "--original-url", "https://example.com/jobs/1/").returncode, 0)
        before = (self.root / "data" / "jobs.csv").read_bytes()
        duplicate = self.add("EXEQUT Ltd.", "Frontend Developer", "--original-url", "https://example.com/jobs/1?utm_source=board#apply")
        self.assertEqual(duplicate.returncode, 2)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        confirmed = self.add("EXEQUT Ltd.", "Frontend Developer", "--original-url", "https://mirror.example/jobs/1", "--duplicate-of", "job-0001")
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        row = self.rows()[1]
        self.assertEqual((row["status"], row["decision_reason"]), ("Duplicate", "duplicate_listing"))
        self.assertIn("job-0001", row["notes"])

    def test_set_advances_lifecycle_and_cannot_lower_stage(self):
        self.assertEqual(self.add("FlowCo", "Frontend Developer", "--no-file").returncode, 0)
        applied = self.invoke("set", "job-0001", "status=Applied", "cv_version=frontend-2026-08")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        row = self.rows()[0]
        self.assertEqual(row["stage_reached"], "Applied")
        self.assertTrue(row["applied_at"])
        screen = self.invoke("set", "job-0001", "--stage", "Recruiter screen")
        self.assertEqual(screen.returncode, 0, screen.stderr)
        self.assertEqual(self.rows()[0]["status"], "Interviewing")
        self.assertTrue(self.rows()[0]["response_at"])
        lower = self.invoke("set", "job-0001", "--stage", "Applied")
        self.assertNotEqual(lower.returncode, 0)
        self.assertIn("нельзя понижать", lower.stderr)

    def test_rejected_write_does_not_change_csv(self):
        self.assertEqual(self.add("SafeCo", "Frontend Developer", "--no-file").returncode, 0)
        before = (self.root / "data" / "jobs.csv").read_bytes()
        rejected = self.invoke("set", "job-0001", "match_score=nan")
        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("match_score", rejected.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

    def test_fuzzy_dupes_and_report(self):
        self.assertEqual(self.add("CoinsPaid", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(self.add("Coins Paid", "Software Engineer, Frontend", "--force", "--no-file").returncode, 0)
        dupes = self.invoke("dupes")
        self.assertEqual(dupes.returncode, 0)
        self.assertIn("пар-кандидатов: 1", dupes.stdout)
        report = self.invoke("report")
        self.assertEqual(report.returncode, 0)
        self.assertIn("## Воронка", report.stdout)


if __name__ == "__main__":
    unittest.main()
