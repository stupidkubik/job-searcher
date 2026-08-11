import csv
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
V1_FIXTURE = PROJECT / "tests" / "fixtures" / "jobs-v1.csv"
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

    def install_v1_fixture(self):
        shutil.copy2(V1_FIXTURE, self.root / "data" / "jobs.csv")

    def test_empty_database_validates(self):
        result = self.invoke("validate")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("проверено записей: 0; ошибок: 0", result.stdout)

    def test_new_job_board_sources_are_accepted(self):
        for source in (
            "Welcome to the Jungle", "We Work Remotely", "HiringCafe",
            "Hacker News — Who is Hiring?", "Hacker News — Who Wants to Be Hired?",
            "YC Work at a Startup", "Wellfound", "HelloWorld.rs", "Reactiflux Discord",
            "Find My Remote / Telegram", "Himalayas", "Startit Jobs",
        ):
            result = self.invoke(
                "add", "--company", f"{source} Co", "--role", "Frontend Developer",
                "--source", source, "--no-file",
            )
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_add_issues_id_creates_card_and_renders_verification_snapshot(self):
        result = self.add(
            "Example Co", "Frontend Engineer",
            "--application-status", "reviewing",
            "--listing-status", "open",
            "--original-url", "https://careers.example.test/jobs/frontend",
            "--first-party-verified", "yes",
            "--apply-verified", "yes",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        row = self.rows()[0]
        self.assertEqual(row["id"], "job-0001")
        self.assertEqual((row["application_status"], row["listing_status"]), ("reviewing", "open"))
        self.assertEqual(row["verified_at"], date.today().isoformat())
        cards = list((self.root / "applications").glob("job-0001-*.md"))
        self.assertEqual(len(cards), 1)
        card = cards[0].read_text(encoding="utf-8")
        self.assertIn("company: Example Co", card)
        self.assertIn("first_party_verified: yes", card)
        self.assertIn("apply_verified: yes", card)
        self.assertIn(f"verified_at: {date.today().isoformat()}", card)

    def test_skipped_add_does_not_create_card(self):
        result = self.add(
            "BlockedCo", "Frontend Developer",
            "--application-status", "not_started",
            "--decision-reason", "geo_restriction",
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.rows()[0]["application_status"], "not_started")
        self.assertFalse(list((self.root / "applications").glob("job-*.md")))

    def test_canonical_url_duplicate_requires_explicit_decision(self):
        self.assertEqual(self.add("ExeQut", "Front-End Software Developer", "--original-url", "https://example.com/jobs/1/", "--no-file").returncode, 0)
        before = (self.root / "data" / "jobs.csv").read_bytes()
        duplicate = self.add("EXEQUT Ltd.", "Frontend Developer", "--original-url", "https://example.com/jobs/1?utm_source=board#apply", "--no-file")
        self.assertEqual(duplicate.returncode, 2)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        confirmed = self.add("EXEQUT Ltd.", "Frontend Developer", "--original-url", "https://mirror.example/jobs/1", "--duplicate-of", "job-0001", "--no-file")
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        row = self.rows()[1]
        self.assertEqual(
            (row["application_status"], row["listing_status"], row["decision_reason"]),
            ("not_started", "unknown", "duplicate_listing"),
        )
        self.assertIn("job-0001", row["notes"])

    def test_set_advances_lifecycle_and_cannot_lower_stage(self):
        self.assertEqual(self.add("FlowCo", "Frontend Developer", "--no-file").returncode, 0)
        applied = self.invoke("set", "job-0001", "application_status=applied", "cv_version=frontend-2026-08")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        row = self.rows()[0]
        self.assertEqual(row["application_status"], "applied")
        self.assertTrue(row["applied_at"])
        screen = self.invoke("set", "job-0001", "--stage", "Recruiter screen")
        self.assertEqual(screen.returncode, 0, screen.stderr)
        self.assertEqual(self.rows()[0]["application_status"], "interviewing")
        self.assertTrue(self.rows()[0]["response_at"])
        lower = self.invoke("set", "job-0001", "--stage", "Applied")
        self.assertNotEqual(lower.returncode, 0)
        self.assertIn("нельзя понижать", lower.stderr)

    def test_listing_can_close_after_application_without_changing_application_history(self):
        self.assertEqual(self.add("LateCloseCo", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0001", "application_status=applied").returncode, 0)
        applied_at = self.rows()[0]["applied_at"]
        closed = self.invoke("set", "job-0001", "listing_status=closed")
        self.assertEqual(closed.returncode, 0, closed.stderr)
        row = self.rows()[0]
        self.assertEqual((row["application_status"], row["listing_status"]), ("applied", "closed"))
        self.assertEqual(row["applied_at"], applied_at)
        self.assertEqual(row["verified_at"], date.today().isoformat())

    def test_verification_invariants_reject_invalid_data_without_writing(self):
        before = (self.root / "data" / "jobs.csv").read_bytes()
        missing_url = self.add("NoUrlCo", "Frontend Developer", "--first-party-verified", "yes", "--no-file")
        self.assertNotEqual(missing_url.returncode, 0)
        self.assertIn("first_party_verified=yes требует original_url", missing_url.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

        apply_without_first_party = self.add(
            "ApplyOnlyCo", "Frontend Developer",
            "--original-url", "https://careers.example.test/apply-only",
            "--apply-verified", "yes", "--no-file",
        )
        self.assertNotEqual(apply_without_first_party.returncode, 0)
        self.assertIn("apply_verified=yes требует first_party_verified=yes", apply_without_first_party.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

        valid = self.add(
            "VerifiedCo", "Frontend Developer",
            "--original-url", "https://careers.example.test/verified",
            "--listing-status", "open",
            "--first-party-verified", "yes",
            "--apply-verified", "yes",
            "--no-file",
        )
        self.assertEqual(valid.returncode, 0, valid.stderr)
        row = self.rows()[0]
        self.assertEqual(row["verified_at"], date.today().isoformat())

        protected = self.invoke("set", "job-0001", "verified_at=2020-01-01")
        self.assertNotEqual(protected.returncode, 0)
        self.assertIn("управляется скриптом", protected.stderr)

    def test_verification_update_sets_date_and_remains_atomic_when_invalid(self):
        self.assertEqual(self.add("UnverifiedCo", "Frontend Developer", "--no-file").returncode, 0)
        opened = self.invoke("set", "job-0001", "listing_status=open")
        self.assertEqual(opened.returncode, 0, opened.stderr)
        self.assertEqual(self.rows()[0]["verified_at"], date.today().isoformat())
        before = (self.root / "data" / "jobs.csv").read_bytes()
        invalid = self.invoke("set", "job-0001", "first_party_verified=yes")
        self.assertNotEqual(invalid.returncode, 0)
        self.assertIn("first_party_verified=yes требует original_url", invalid.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

    def test_missing_cv_version_is_reported_without_validation_warning(self):
        self.assertEqual(self.add("HistoricalCo", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0001", "application_status=applied").returncode, 0)
        validation = self.invoke("validate")
        self.assertEqual(validation.returncode, 0, validation.stderr)
        self.assertIn("предупреждений: 0", validation.stdout)
        report = self.invoke("report")
        self.assertIn("| not recorded | 1 | 0 | 0% |", report.stdout)

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

    def test_migrate_v2_check_is_read_only_and_maps_every_legacy_status(self):
        self.install_v1_fixture()
        before = (self.root / "data" / "jobs.csv").read_bytes()
        check = self.invoke("migrate-v2", "--check")
        self.assertEqual(check.returncode, 0, check.stderr)
        self.assertIn("строк: 12", check.stdout)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

        migrate = self.invoke("migrate-v2")
        self.assertEqual(migrate.returncode, 0, migrate.stderr)
        rows = {row["id"]: row for row in self.rows()}
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
        validation = self.invoke("validate", "--strict")
        self.assertEqual(validation.returncode, 0, validation.stderr)
        repeated = self.invoke("migrate-v2", "--check")
        self.assertNotEqual(repeated.returncode, 0)
        self.assertIn("уже использует схему v2", repeated.stderr)


if __name__ == "__main__":
    unittest.main()
