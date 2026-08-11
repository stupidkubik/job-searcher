import csv
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
V1_FIXTURE = PROJECT / "tests" / "fixtures" / "jobs-v1.csv"
VALID_JSON_FIXTURE = PROJECT / "tests" / "fixtures" / "job-input-valid.json"
INVALID_JSON_FIXTURE = PROJECT / "tests" / "fixtures" / "job-input-invalid.json"
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
        source_header = (PROJECT / "data" / "job_sources.csv").read_text(encoding="utf-8").splitlines()[0]
        (self.root / "data" / "job_sources.csv").write_text(source_header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *arguments, input_text=None):
        return subprocess.run(
            [sys.executable, "scripts/jobs.py", *arguments], cwd=self.root,
            text=True, input=input_text, capture_output=True,
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
        self.assertIn("проверено записей: 0; source references: 0; ошибок: 0", result.stdout)

    def test_new_job_board_sources_are_accepted(self):
        for index, source in enumerate((
            "Welcome to the Jungle", "We Work Remotely", "HiringCafe",
            "Hacker News — Who is Hiring?", "Hacker News — Who Wants to Be Hired?",
            "YC Work at a Startup", "Wellfound", "HelloWorld.rs", "Reactiflux Discord",
            "Find My Remote / Telegram", "Himalayas", "Startit Jobs",
        ), start=1):
            result = self.invoke(
                "add", "--company", f"{source} Co", "--role", "Frontend Developer",
                "--source", source, "--source-url", f"https://source.example.test/{index}", "--no-file",
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

    def test_add_fails_without_template_before_writing_csv_or_card(self):
        (self.root / "applications" / "_TEMPLATE.md").unlink()
        before = (self.root / "data" / "jobs.csv").read_bytes()
        result = self.add("TemplateMissingCo", "Frontend Developer")
        self.assertEqual(result.returncode, 1)
        self.assertIn("не найден шаблон", result.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        self.assertFalse(list((self.root / "applications").glob("job-*.md")))

    def test_invalid_cli_input_uses_exit_code_one(self):
        result = self.invoke("add", "--company", "MissingRoleAndSource")
        self.assertEqual(result.returncode, 1)
        self.assertIn("для add без --json/--stdin обязательны", result.stderr)

    def test_add_accepts_json_file_and_returns_canonical_json(self):
        result = self.invoke("add", "--json", str(VALID_JSON_FIXTURE), "--format", "json")
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["ok"], payload["command"]), (True, "add"))
        self.assertEqual(payload["job"]["id"], "job-0001")
        self.assertEqual(payload["job"]["company"], "Json ExampleCo")
        self.assertEqual(payload["job"]["last_update"], date.today().isoformat())
        self.assertTrue(payload["application_path"].startswith("applications/job-0001-"))
        self.assertTrue(list((self.root / "applications").glob("job-0001-*.md")))

    def test_add_accepts_json_from_stdin_without_cli_field_merge(self):
        input_text = json.dumps({
            "company": "Stdin ExampleCo",
            "role": "Frontend Developer",
            "source": "Manual",
        })
        result = self.invoke("add", "--stdin", "--no-file", "--format", "json", input_text=input_text)
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["job"]["company"], "Stdin ExampleCo")
        self.assertIsNone(payload["application_path"])

    def test_add_rejects_unknown_or_authoritative_json_fields_without_writing(self):
        before = (self.root / "data" / "jobs.csv").read_bytes()
        invalid = self.invoke("add", "--json", str(INVALID_JSON_FIXTURE), "--no-file")
        self.assertEqual(invalid.returncode, 1)
        self.assertIn("id, last_update, unexpected_field", invalid.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

        merged = self.invoke("add", "--json", str(VALID_JSON_FIXTURE), "--company", "ConflictingCo")
        self.assertEqual(merged.returncode, 1)
        self.assertIn("нельзя совмещать", merged.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

        mutually_exclusive = self.invoke(
            "add", "--json", str(VALID_JSON_FIXTURE), "--stdin",
            input_text='{"company":"Ignored","role":"Frontend Developer","source":"Manual"}',
        )
        self.assertEqual(mutually_exclusive.returncode, 1)
        self.assertIn("not allowed with argument", mutually_exclusive.stderr)

    def test_set_validate_and_dupes_support_single_json_output(self):
        self.assertEqual(self.add("MachineCo", "Frontend Developer", "--no-file").returncode, 0)
        updated = self.invoke("set", "job-0001", "listing_status=open", "--format", "json")
        self.assertEqual(updated.returncode, 0, updated.stderr)
        update_payload = json.loads(updated.stdout)
        self.assertEqual((update_payload["ok"], update_payload["command"]), (True, "set"))
        self.assertEqual(update_payload["job"]["listing_status"], "open")

        validated = self.invoke("validate", "--strict", "--format", "json")
        self.assertEqual(validated.returncode, 0, validated.stderr)
        validation_payload = json.loads(validated.stdout)
        self.assertEqual((validation_payload["ok"], validation_payload["checked"]), (True, 1))

        dupes = self.invoke("dupes", "--format", "json")
        self.assertEqual(dupes.returncode, 0, dupes.stderr)
        duplicate_payload = json.loads(dupes.stdout)
        self.assertEqual((duplicate_payload["ok"], duplicate_payload["command"], duplicate_payload["candidates"]), (True, "dupes", []))

    def test_canonical_url_duplicate_requires_explicit_decision(self):
        self.assertEqual(self.add("ExeQut", "Front-End Software Developer", "--original-url", "https://example.com/jobs/1/", "--source-url", "https://source.example.test/exequt", "--no-file").returncode, 0)
        before = (self.root / "data" / "jobs.csv").read_bytes()
        duplicate = self.add("EXEQUT Ltd.", "Frontend Developer", "--original-url", "https://example.com/jobs/1?utm_source=board#apply", "--no-file", "--format", "json")
        self.assertEqual(duplicate.returncode, 2)
        payload = json.loads(duplicate.stdout)
        self.assertEqual((payload["ok"], payload["error"]), (False, "unresolved_duplicate"))
        self.assertEqual(payload["candidates"][0]["id"], "job-0001")
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)
        confirmed = self.add("EXEQUT Ltd.", "Frontend Developer", "--source-url", "https://mirror.example/jobs/1", "--duplicate-of", "job-0001", "--no-file")
        self.assertEqual(confirmed.returncode, 0, confirmed.stderr)
        self.assertEqual(len(self.rows()), 1)
        with (self.root / "data" / "job_sources.csv").open(newline="", encoding="utf-8") as file:
            sources = list(csv.DictReader(file))
        self.assertEqual((len(sources), sources[1]["job_id"], sources[1]["source_url"]), (2, "job-0001", "https://mirror.example/jobs/1"))

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

    def test_verify_promotes_a_confirmed_candidate_and_creates_a_card(self):
        added = self.invoke(
            "add", "--company", "CandidateCo", "--role", "Frontend Developer", "--source", "Himalayas",
            "--source-url", "https://himalayas.app/jobs/candidate", "--source-job-id", "candidate-001", "--no-file",
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        verified = self.invoke(
            "verify", "job-0001", "--listing-status", "open",
            "--first-party-verified", "yes", "--apply-verified", "yes",
            "--original-url", "https://careers.example.test/jobs/candidate", "--format", "json",
        )
        self.assertEqual(verified.returncode, 0, verified.stderr)
        payload = json.loads(verified.stdout)
        self.assertEqual((payload["command"], payload["outcome"]), ("verify", "ready_for_review"))
        self.assertTrue(payload["application_card_created"])
        row = self.rows()[0]
        self.assertEqual((row["application_status"], row["listing_status"]), ("reviewing", "open"))
        self.assertEqual((row["first_party_verified"], row["apply_verified"]), ("yes", "yes"))
        self.assertEqual(row["verified_at"], date.today().isoformat())
        card = next((self.root / "applications").glob("job-0001-*.md"))
        self.assertIn("listing_status: open", card.read_text(encoding="utf-8"))

    def test_verify_records_a_hard_blocker_without_creating_a_card(self):
        self.assertEqual(
            self.invoke(
                "add", "--company", "GeoCo", "--role", "Frontend Developer", "--source", "Himalayas",
                "--source-url", "https://himalayas.app/jobs/geo", "--source-job-id", "geo-001", "--no-file",
            ).returncode,
            0,
        )
        blocked = self.invoke(
            "verify", "job-0001", "--listing-status", "open",
            "--first-party-verified", "yes", "--apply-verified", "yes",
            "--original-url", "https://careers.example.test/jobs/geo",
            "--decision-reason", "geo_restriction",
        )
        self.assertEqual(blocked.returncode, 0, blocked.stderr)
        row = self.rows()[0]
        self.assertEqual((row["application_status"], row["decision_reason"]), ("not_started", "geo_restriction"))
        self.assertFalse(list((self.root / "applications").glob("job-*.md")))

    def test_verify_can_close_listing_after_application_without_rewriting_history(self):
        self.assertEqual(self.add("VerifiedCloseCo", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0001", "application_status=applied").returncode, 0)
        applied_at = self.rows()[0]["applied_at"]
        closed = self.invoke(
            "verify", "job-0001", "--listing-status", "closed",
            "--first-party-verified", "yes", "--apply-verified", "no",
            "--original-url", "https://careers.example.test/jobs/closed",
        )
        self.assertEqual(closed.returncode, 0, closed.stderr)
        row = self.rows()[0]
        self.assertEqual((row["application_status"], row["listing_status"]), ("applied", "closed"))
        self.assertEqual(row["applied_at"], applied_at)

    def test_missing_cv_version_is_reported_without_validation_warning(self):
        self.assertEqual(self.add("HistoricalCo", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0001", "application_status=applied").returncode, 0)
        validation = self.invoke("validate")
        self.assertEqual(validation.returncode, 0, validation.stderr)
        self.assertIn("предупреждений: 0", validation.stdout)
        report = self.invoke("report")
        self.assertIn("| not recorded | 1 | 0 | 0% |", report.stdout)

    def test_stale_lists_only_active_candidates_and_never_mutates_dataset(self):
        self.assertEqual(self.add("StaleCo", "Frontend Developer", "--match-score", "8", "--no-file").returncode, 0)
        self.assertEqual(
            self.add(
                "SkippedCo", "Frontend Developer", "--decision-reason", "geo_restriction", "--no-file",
            ).returncode,
            0,
        )
        self.assertEqual(self.add("FreshCo", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0003", "listing_status=open").returncode, 0)
        before = (self.root / "data" / "jobs.csv").read_bytes()

        result = self.invoke("stale", "--days", "7", "--date", date.today().isoformat(), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual((payload["command"], payload["count"]), ("stale", 1))
        self.assertEqual(payload["jobs"][0]["id"], "job-0001")
        self.assertEqual(payload["jobs"][0]["reason"], "never_verified")
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

    def test_daily_commands_reject_invalid_arguments_without_mutating_dataset(self):
        result = self.add("Acme", "Frontend Engineer", "--application-status", "reviewing", "--no-file")
        self.assertEqual(result.returncode, 0, result.stderr)
        before = (self.root / "data" / "jobs.csv").read_bytes()

        stale = self.invoke("stale", "--days", "0", "--format", "json")
        self.assertEqual(stale.returncode, 1)
        self.assertIn("положительное целое", stale.stderr)

        todo = self.invoke("todo", "--date", "not-a-date", "--format", "json")
        self.assertEqual(todo.returncode, 1)
        self.assertIn("ожидается дата", todo.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

    def test_todo_has_stable_sections_ordering_and_date_override(self):
        reference = date.today()
        yesterday = (reference.fromordinal(reference.toordinal() - 1)).isoformat()
        tomorrow = (reference.fromordinal(reference.toordinal() + 1)).isoformat()
        self.assertEqual(self.add("OverdueLow", "Frontend Developer", "--match-score", "6", "--no-file").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0001", "next_action=follow-up", f"next_action_date={yesterday}").returncode, 0)
        self.assertEqual(self.add("OverdueHigh", "Frontend Developer", "--match-score", "9", "--no-file").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0002", "next_action=follow-up", f"next_action_date={yesterday}").returncode, 0)
        self.assertEqual(self.add("TodayCo", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0003", "next_action=follow-up", f"next_action_date={reference.isoformat()}").returncode, 0)
        self.assertEqual(self.add("FutureFollow", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0004", "next_action=follow-up", f"next_action_date={tomorrow}").returncode, 0)
        self.assertEqual(self.add("ApplyCo", "Frontend Developer", "--application-status", "apply", "--no-file").returncode, 0)
        self.assertEqual(self.add("ReviewCo", "Frontend Developer", "--application-status", "reviewing", "--no-file").returncode, 0)
        self.assertEqual(self.add("VerifyCo", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(self.add("InterviewCo", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0008", "application_status=applied").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0008", "--stage", "Tech interview").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0008", "next_action=prepare technical interview", f"next_action_date={tomorrow}").returncode, 0)
        before = (self.root / "data" / "jobs.csv").read_bytes()

        result = self.invoke("todo", "--date", reference.isoformat(), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        sections = payload["sections"]
        self.assertEqual(payload["section_order"], [
            "overdue", "today", "follow_ups", "apply_not_submitted", "stale_review",
            "verification_queue", "upcoming_interview_test",
        ])
        self.assertEqual([item["id"] for item in sections["overdue"]], ["job-0002", "job-0001"])
        self.assertEqual([item["id"] for item in sections["today"]], ["job-0003"])
        self.assertEqual([item["id"] for item in sections["follow_ups"]], ["job-0004"])
        self.assertEqual([item["id"] for item in sections["apply_not_submitted"]], ["job-0005"])
        self.assertEqual([item["id"] for item in sections["stale_review"]], ["job-0006"])
        self.assertIn("job-0007", [item["id"] for item in sections["verification_queue"]])
        self.assertEqual([item["id"] for item in sections["upcoming_interview_test"]], ["job-0008"])
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

    def test_stats_and_report_use_structured_v2_fields(self):
        self.assertEqual(
            self.add(
                "VerifiedCo", "Frontend Developer", "--application-status", "reviewing",
                "--listing-status", "open", "--original-url", "https://careers.example.test/verified",
                "--first-party-verified", "yes", "--apply-verified", "yes", "--no-file",
            ).returncode,
            0,
        )
        self.assertEqual(self.invoke("set", "job-0001", "application_status=applied").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0001", "--stage", "Recruiter screen").returncode, 0)
        self.assertEqual(self.add("Second Employer", "Frontend Developer", "--no-file").returncode, 0)

        stats = self.invoke("stats", "--date", date.today().isoformat(), "--format", "json")

        self.assertEqual(stats.returncode, 0, stats.stderr)
        payload = json.loads(stats.stdout)
        self.assertEqual((payload["command"], payload["jobs_total"]), ("stats", 2))
        self.assertEqual(payload["application_status"]["interviewing"], 1)
        self.assertEqual(payload["listing_status"]["open"], 1)
        self.assertEqual(payload["verification"]["fully_verified"], 1)
        self.assertEqual(payload["verification"]["coverage_percent"], 50.0)
        self.assertEqual(payload["stale"]["count"], 1)
        self.assertEqual(payload["funnel"]["applications"], 1)
        self.assertEqual(payload["funnel"]["responses"], 1)
        self.assertEqual(payload["sources"], [{
            "source": "Manual", "found": 2, "applied": 1, "responses": 1, "response_rate": 100.0,
        }])
        report = self.invoke("report", "--date", date.today().isoformat())
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertIn("## Verification coverage", report.stdout)
        self.assertIn("## Stale verification", report.stdout)
        self.assertIn("## Воронка", report.stdout)

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
