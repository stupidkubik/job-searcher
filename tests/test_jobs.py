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
        self.assertIn("id: job-0001\n", card)
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

    def test_status_records_user_confirmed_application_interview_and_rejection(self):
        self.assertEqual(self.add("LifecycleCo", "Frontend Developer", "--no-file").returncode, 0)

        applied = self.invoke(
            "status", "job-0001", "--application-status", "applied",
            "--applied-at", "2026-08-10", "--cv-version", "frontend-2026-08",
            "--next-action", "follow-up", "--format", "json",
        )
        self.assertEqual(applied.returncode, 0, applied.stderr)
        row = self.rows()[0]
        self.assertEqual(
            (row["application_status"], row["applied_at"], row["stage_reached"], row["cv_version"]),
            ("applied", "2026-08-10", "Applied", "frontend-2026-08"),
        )
        self.assertTrue(list((self.root / "applications").glob("job-0001-*.md")))

        interviewing = self.invoke(
            "status", "job-0001", "--application-status", "interviewing",
            "--stage", "Tech interview", "--response-at", "2026-08-11",
            "--next-action", "prepare technical interview",
            "--next-action-date", "2026-08-15", "--format", "json",
        )
        self.assertEqual(interviewing.returncode, 0, interviewing.stderr)
        row = self.rows()[0]
        self.assertEqual(
            (row["application_status"], row["response_at"], row["stage_reached"]),
            ("interviewing", "2026-08-11", "Tech interview"),
        )

        rejected = self.invoke(
            "status", "job-0001", "--application-status", "rejected", "--format", "json",
        )
        self.assertEqual(rejected.returncode, 0, rejected.stderr)
        row = self.rows()[0]
        self.assertEqual((row["application_status"], row["stage_reached"]), ("rejected", "Tech interview"))
        self.assertEqual((row["next_action"], row["next_action_date"]), ("", ""))

    def test_status_supports_pre_application_offer_ghosted_and_withdrawn_states(self):
        for company in ("ApplyCo", "OfferCo", "GhostCo", "WithdrawCo"):
            self.assertEqual(self.add(company, "Frontend Developer", "--force", "--no-file").returncode, 0)

        reviewing = self.invoke("status", "job-0001", "--application-status", "reviewing")
        self.assertEqual(reviewing.returncode, 0, reviewing.stderr)
        apply = self.invoke(
            "status", "job-0001", "--application-status", "apply",
            "--next-action", "submit application",
        )
        self.assertEqual(apply.returncode, 0, apply.stderr)

        self.assertEqual(
            self.invoke("status", "job-0002", "--application-status", "applied").returncode, 0,
        )
        offer = self.invoke("status", "job-0002", "--application-status", "offer")
        self.assertEqual(offer.returncode, 0, offer.stderr)

        self.assertEqual(
            self.invoke("status", "job-0003", "--application-status", "applied").returncode, 0,
        )
        ghosted = self.invoke("status", "job-0003", "--application-status", "ghosted")
        self.assertEqual(ghosted.returncode, 0, ghosted.stderr)

        self.assertEqual(
            self.invoke("status", "job-0004", "--application-status", "applied").returncode, 0,
        )
        withdrawn = self.invoke("status", "job-0004", "--application-status", "withdrawn")
        self.assertEqual(withdrawn.returncode, 0, withdrawn.stderr)

        rows = self.rows()
        self.assertEqual((rows[0]["application_status"], rows[0]["next_action"]), ("apply", "submit application"))
        self.assertEqual((rows[1]["application_status"], rows[1]["stage_reached"]), ("offer", "Offer"))
        self.assertEqual((rows[2]["application_status"], rows[2]["decision_reason"]), ("ghosted", "no_response_timeout"))
        self.assertEqual((rows[3]["application_status"], rows[3]["decision_reason"]), ("withdrawn", "withdrawn_by_me"))

    def test_status_rejects_invented_post_application_history_without_writing(self):
        self.assertEqual(self.add("UnsafeLifecycleCo", "Frontend Developer", "--no-file").returncode, 0)
        before = (self.root / "data" / "jobs.csv").read_bytes()

        rejected = self.invoke("status", "job-0001", "--application-status", "rejected")

        self.assertNotEqual(rejected.returncode, 0)
        self.assertIn("требует --applied-at", rejected.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

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

    def test_verify_migrates_missing_fields_in_legacy_application_card(self):
        added = self.invoke(
            "add", "--company", "LegacyCo", "--role", "Product Engineer",
            "--source", "Manual", "--application-status", "apply", "--no-file",
        )
        self.assertEqual(added.returncode, 0, added.stderr)
        card_path = self.root / "applications" / "job-0001-legacyco-product-engineer.md"
        card_path.write_text(
            "---\n"
            "id: job-0001\n"
            "company: LegacyCo\n"
            "role: Product Engineer\n"
            "original_url:\n"
            "---\n\n"
            "# Preserve this legacy application body\n",
            encoding="utf-8",
        )

        verified = self.invoke(
            "verify", "job-0001", "--listing-status", "open",
            "--first-party-verified", "yes", "--apply-verified", "yes",
            "--original-url", "https://careers.example.test/jobs/legacy",
            "--format", "json",
        )

        self.assertEqual(verified.returncode, 0, verified.stderr)
        card = card_path.read_text(encoding="utf-8")
        self.assertIn("# Preserve this legacy application body", card)
        self.assertIn(f"verified_at: {date.today().isoformat()}", card)
        self.assertIn("listing_status: open", card)
        self.assertIn("first_party_verified: yes", card)
        self.assertIn("apply_verified: yes", card)
        for field in (
            "id", "company", "role", "original_url", "verified_at",
            "listing_status", "first_party_verified", "apply_verified",
        ):
            self.assertEqual(card.count(f"{field}:"), 1)

    def test_verify_can_enrich_safe_job_facts_in_the_same_transaction(self):
        added = self.invoke(
            "add", "--company", "EnrichedCo", "--role", "Frontend Developer", "--source", "Himalayas",
            "--source-url", "https://himalayas.app/jobs/enriched", "--source-job-id", "enriched-001", "--no-file",
        )
        self.assertEqual(added.returncode, 0, added.stderr)

        verified = self.invoke(
            "verify", "job-0001", "--listing-status", "open",
            "--first-party-verified", "yes", "--apply-verified", "yes",
            "--original-url", "https://careers.example.test/jobs/enriched",
            "--level", "Intern", "--remote-policy", "Europe",
            "--stack", "React; TypeScript", "--salary", "1200 USD/month",
            "--match-score", "8.5", "--format", "json",
        )

        self.assertEqual(verified.returncode, 0, verified.stderr)
        row = self.rows()[0]
        self.assertEqual(
            {key: row[key] for key in ("level", "remote_policy", "stack", "salary", "match_score")},
            {
                "level": "Intern", "remote_policy": "Europe", "stack": "React; TypeScript",
                "salary": "1200 USD/month", "match_score": "8.5",
            },
        )

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

    def test_screen_records_a_skip_without_claiming_first_party_verification(self):
        self.assertEqual(self.add("ScreenCo", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(
            self.invoke(
                "set", "job-0001", "next_action=verify first-party",
                "next_action_date=2026-08-12",
            ).returncode,
            0,
        )
        before = self.rows()[0]

        screened = self.invoke(
            "screen", "job-0001", "--decision-reason", "geo_restriction",
            "--notes", "Discovery source restricts the role to Latin America.",
            "--format", "json",
        )

        self.assertEqual(screened.returncode, 0, screened.stderr)
        payload = json.loads(screened.stdout)
        self.assertEqual((payload["command"], payload["outcome"]), ("screen", "screened_out"))
        row = self.rows()[0]
        self.assertEqual((row["application_status"], row["decision_reason"]), ("not_started", "geo_restriction"))
        self.assertEqual((row["next_action"], row["next_action_date"]), ("", ""))
        for field in ("listing_status", "verified_at", "first_party_verified", "apply_verified"):
            self.assertEqual(row[field], before[field])

    def test_screen_rejects_a_job_after_application_without_writing(self):
        self.assertEqual(self.add("AppliedCo", "Frontend Developer", "--no-file").returncode, 0)
        self.assertEqual(self.invoke("set", "job-0001", "application_status=applied").returncode, 0)
        before = (self.root / "data" / "jobs.csv").read_bytes()

        screened = self.invoke("screen", "job-0001", "--decision-reason", "geo_restriction")

        self.assertEqual(screened.returncode, 1)
        self.assertIn("только до фактической отправки", screened.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

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

    def test_todo_can_filter_by_primary_source_and_inclusive_id_range(self):
        self.assertEqual(self.add("ManualCo", "Frontend Developer", "--no-file").returncode, 0)
        for number in (2, 3):
            added = self.invoke(
                "add", "--company", f"Himalayas {number}", "--role", "Frontend Developer",
                "--source", "Himalayas", "--source-url", f"https://himalayas.app/jobs/{number}", "--force", "--no-file",
            )
            self.assertEqual(added.returncode, 0, added.stderr)
        before = (self.root / "data" / "jobs.csv").read_bytes()

        result = self.invoke(
            "todo", "--source", "Himalayas", "--id-range", "job-0003:job-0003", "--format", "json",
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["filters"], {"source": "Himalayas", "id_range": "job-0003:job-0003"})
        self.assertEqual([item["id"] for item in payload["sections"]["verification_queue"]], ["job-0003"])
        self.assertTrue(all(
            item["id"] == "job-0003"
            for section in payload["sections"].values()
            for item in section
        ))
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

    def test_report_leads_with_derived_state_and_lists_open_as_a_property(self):
        self.assertEqual(
            self.add(
                "OpenButSkippedCo", "Frontend Developer", "--listing-status", "open",
                "--decision-reason", "geo_restriction", "--no-file",
            ).returncode,
            0,
        )

        stats = self.invoke("stats", "--format", "json")
        report = self.invoke("report")

        self.assertEqual(stats.returncode, 0, stats.stderr)
        self.assertEqual(json.loads(stats.stdout)["derived_state"], {"Skipped: geo_restriction": 1})
        self.assertEqual(report.returncode, 0, report.stderr)
        self.assertIn("## Основной статус", report.stdout)
        self.assertIn("| Skipped: geo_restriction | 1 |", report.stdout)
        self.assertIn("## Свойства объявлений", report.stdout)
        self.assertLess(report.stdout.index("## Основной статус"), report.stdout.index("## Свойства объявлений"))

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

    def test_himalayas_screening_repair_is_exact_and_idempotent(self):
        self.install_himalayas_screening_batch()
        before_bytes = (self.root / "data" / "jobs.csv").read_bytes()
        before = {row["id"]: row for row in self.rows()}
        excluded_ids = {"job-0102", "job-0110", "job-0111", "job-0124"}
        target_ids = set(before) - excluded_ids

        check = self.invoke("repair-himalayas-screening", "--check", "--format", "json")
        self.assertEqual(check.returncode, 0, check.stderr)
        check_payload = json.loads(check.stdout)
        self.assertEqual(check_payload["status"], "ready")
        self.assertEqual(check_payload["target_count"], 24)
        self.assertEqual(set(check_payload["target_ids"]), target_ids)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before_bytes)

        repair = self.invoke("repair-himalayas-screening", "--format", "json")
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

        repeated = self.invoke("repair-himalayas-screening", "--format", "json")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        self.assertEqual(json.loads(repeated.stdout)["status"], "already_applied")
        self.assertEqual(json.loads(repeated.stdout)["changed"], 0)
        validation = self.invoke("validate", "--strict")
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

        repair = self.invoke("repair-himalayas-screening", "--format", "json")

        self.assertNotEqual(repair.returncode, 0)
        self.assertIn("смешанное или неожиданное состояние", repair.stderr)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), before)

    def tracker_row(self, number, **changes):
        with (self.root / "data" / "jobs.csv").open(newline="", encoding="utf-8") as file:
            fields = csv.DictReader(file).fieldnames
        row = {field: "" for field in fields}
        row.update({
            "id": f"job-{number:04d}",
            "application_status": "not_started",
            "listing_status": "unknown",
            "company": f"Company {number}",
            "role": "Frontend Developer",
            "level": "Unknown",
            "source": "Manual",
            "remote_policy": "Unclear",
            "salary": "Unknown",
            "found_at": "2026-08-01",
            "stage_reached": "None",
            "first_party_verified": "unknown",
            "apply_verified": "unknown",
            "last_update": "2026-08-10",
        })
        row.update(changes)
        return row

    def write_tracker_dataset(self, rows, source_rows=()):
        with (self.root / "data" / "jobs.csv").open(newline="", encoding="utf-8") as file:
            fields = csv.DictReader(file).fieldnames
        with (self.root / "data" / "jobs.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(rows)
        with (self.root / "data" / "job_sources.csv").open(newline="", encoding="utf-8") as file:
            source_fields = csv.DictReader(file).fieldnames
        with (self.root / "data" / "job_sources.csv").open("w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=source_fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows(source_rows)

    def test_render_tracker_classifies_every_status_once_and_renders_links(self):
        rows = [
            self.tracker_row(1, listing_status="open", first_party_verified="yes", apply_verified="yes", verified_at="2026-08-09", original_url="https://careers.example.test/one", match_score="7", next_action="prepare CV", next_action_date="2026-08-13"),
            self.tracker_row(2, application_status="reviewing", listing_status="open", first_party_verified="yes", apply_verified="yes", verified_at="2026-08-09", original_url="https://careers.example.test/two", match_score="8"),
            self.tracker_row(3, application_status="apply", listing_status="open", first_party_verified="yes", apply_verified="yes", verified_at="2026-08-09", original_url="https://careers.example.test/three", match_score="9"),
            self.tracker_row(4),
            self.tracker_row(5, application_status="reviewing", listing_status="open", first_party_verified="no", apply_verified="no", verified_at="2026-08-09"),
            self.tracker_row(6, application_status="apply", first_party_verified="yes", apply_verified="yes", verified_at="2026-08-09", original_url="https://careers.example.test/six"),
            self.tracker_row(7, application_status="applied", listing_status="closed", applied_at="2026-08-05", stage_reached="Applied"),
            self.tracker_row(8, application_status="interviewing", applied_at="2026-08-05", response_at="2026-08-06", stage_reached="Tech interview"),
            self.tracker_row(9, application_status="offer", applied_at="2026-08-05", response_at="2026-08-06", stage_reached="Offer"),
            self.tracker_row(10, application_status="rejected", applied_at="2026-08-05", response_at="2026-08-06", stage_reached="Recruiter screen"),
            self.tracker_row(11, application_status="ghosted", applied_at="2026-08-05", stage_reached="Applied"),
            self.tracker_row(12, application_status="withdrawn", applied_at="2026-08-05", stage_reached="Applied", decision_reason="withdrawn_by_me"),
            self.tracker_row(13, listing_status="closed", decision_reason="closed_before_application"),
            self.tracker_row(14, listing_status="open", decision_reason="geo_restriction"),
            self.tracker_row(15, decision_reason="duplicate_listing", notes="Duplicate of job-0001"),
            self.tracker_row(16, company="Acme | [Web] <script> `do` *bold*", original_url="https://careers.example.test/special"),
            self.tracker_row(17, source_url="", original_url=""),
        ]
        source_rows = [{
            "job_id": "job-0017", "source": "Manual",
            "source_url": "https://source.example.test/primary", "source_job_id": "", "found_at": "2026-08-01",
        }]
        self.write_tracker_dataset(rows, source_rows)
        (self.root / "applications" / "job-0001-example.md").write_text("# Card\n", encoding="utf-8")

        result = self.invoke("render-tracker", "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload, {
            "ok": True,
            "command": "render-tracker",
            "path": "docs/tracker.md",
            "up_to_date": True,
            "counts": {"action_now": 3, "applications": 6, "to_verify": 5, "archive": 3},
        })
        tracker = (self.root / "docs" / "tracker.md").read_text(encoding="utf-8")
        self.assertIn("Dataset updated: **2026-08-10** · Jobs: **17**", tracker)
        self.assertIn("[Action now (3)](#action-now)", tracker)
        self.assertIn("Ready to apply", tracker)
        self.assertIn("Not checked", tracker)
        self.assertIn("Skipped: geo restriction", tracker)
        self.assertIn("[Company 1 — Frontend Developer](<https://careers.example.test/one>) · job-0001", tracker)
        self.assertIn("[Company 17 — Frontend Developer](<https://source.example.test/primary>) · job-0017", tracker)
        self.assertIn("[Open](../applications/job-0001-example.md)", tracker)
        self.assertIn(r"Acme \| \[Web\] \<script\> \`do\` \*bold\*", tracker)
        self.assertIn("First party + Apply + Listing", tracker)
        self.assertIn("<details>", tracker)
        action_now = tracker[tracker.index("## Action now"):tracker.index("## Applications")]
        applications = tracker[tracker.index("## Applications"):tracker.index("## To verify")]
        to_verify = tracker[tracker.index("## To verify"):tracker.index("## Archive")]
        archive = tracker[tracker.index("## Archive"):]
        self.assertIn("job-0003", action_now)
        self.assertIn("job-0007", applications)
        self.assertIn("job-0006", to_verify)
        self.assertIn("Listing | — | verify first-party", to_verify)
        self.assertIn("job-0014", archive)
        self.assertLess(tracker.index("<details>"), tracker.index("Skipped: geo restriction"))
        self.assertEqual(tracker.count("job-0006"), 1)
        self.assertEqual(tracker.count("job-0007"), 1)

    def test_render_tracker_is_deterministic_and_check_is_read_only(self):
        row = self.tracker_row(
            1, listing_status="open", first_party_verified="yes", apply_verified="yes",
            verified_at="2026-08-09", original_url="https://careers.example.test/one",
        )
        self.write_tracker_dataset([row])
        jobs_before = (self.root / "data" / "jobs.csv").read_bytes()
        sources_before = (self.root / "data" / "job_sources.csv").read_bytes()
        missing = self.invoke("render-tracker", "--check", "--format", "json")
        self.assertEqual(missing.returncode, 1)
        self.assertEqual(json.loads(missing.stdout)["up_to_date"], False)
        self.assertFalse((self.root / "docs" / "tracker.md").exists())

        first = self.invoke("render-tracker")
        self.assertEqual(first.returncode, 0, first.stderr)
        tracker_path = self.root / "docs" / "tracker.md"
        first_bytes = tracker_path.read_bytes()
        second = self.invoke("render-tracker")
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(tracker_path.read_bytes(), first_bytes)
        self.assertEqual((self.root / "data" / "jobs.csv").read_bytes(), jobs_before)
        self.assertEqual((self.root / "data" / "job_sources.csv").read_bytes(), sources_before)
        fresh = self.invoke("render-tracker", "--check", "--format", "json")
        self.assertEqual(fresh.returncode, 0, fresh.stderr)
        self.assertTrue(json.loads(fresh.stdout)["up_to_date"])

        tracker_path.write_text("stale tracker\n", encoding="utf-8")
        stale_before = tracker_path.read_bytes()
        stale = self.invoke("render-tracker", "--check", "--format", "json")
        self.assertEqual(stale.returncode, 1)
        self.assertEqual(json.loads(stale.stdout)["up_to_date"], False)
        self.assertEqual(tracker_path.read_bytes(), stale_before)

        self.assertEqual(self.invoke("render-tracker").returncode, 0)
        changed = self.tracker_row(
            1, company="Changed Company", listing_status="open", first_party_verified="yes",
            apply_verified="yes", verified_at="2026-08-09", original_url="https://careers.example.test/one",
        )
        self.write_tracker_dataset([changed])
        changed_check = self.invoke("render-tracker", "--check", "--format", "json")
        self.assertEqual(changed_check.returncode, 1)
        self.assertEqual(json.loads(changed_check.stdout)["ok"], False)

    def test_render_tracker_rejects_invalid_data_or_ambiguous_cards_without_overwriting(self):
        row = self.tracker_row(
            1, listing_status="open", first_party_verified="yes", apply_verified="yes",
            verified_at="2026-08-09", original_url="https://careers.example.test/one",
        )
        self.write_tracker_dataset([row])
        self.assertEqual(self.invoke("render-tracker").returncode, 0)
        tracker_path = self.root / "docs" / "tracker.md"
        before = tracker_path.read_bytes()

        invalid = self.tracker_row(1, company="")
        self.write_tracker_dataset([invalid])
        invalid_render = self.invoke("render-tracker")
        self.assertEqual(invalid_render.returncode, 1)
        self.assertIn("пустое обязательное поле company", invalid_render.stderr)
        self.assertEqual(tracker_path.read_bytes(), before)

        self.write_tracker_dataset([row])
        (self.root / "applications" / "job-0001-a.md").write_text("# One\n", encoding="utf-8")
        (self.root / "applications" / "job-0001-b.md").write_text("# Two\n", encoding="utf-8")
        ambiguous = self.invoke("render-tracker")
        self.assertEqual(ambiguous.returncode, 1)
        self.assertIn("multiple application cards match", ambiguous.stderr)
        self.assertEqual(tracker_path.read_bytes(), before)

    def test_render_tracker_empty_dataset_uses_empty_sections(self):
        result = self.invoke("render-tracker", "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["counts"], {
            "action_now": 0, "applications": 0, "to_verify": 0, "archive": 0,
        })
        tracker = (self.root / "docs" / "tracker.md").read_text(encoding="utf-8")
        self.assertEqual(tracker.count("No jobs."), 4)
        self.assertIn("<summary>Archive (0)</summary>", tracker)


if __name__ == "__main__":
    unittest.main()
