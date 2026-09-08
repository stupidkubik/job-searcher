import hashlib
import json
import os
import stat
import subprocess
import sys
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from scripts import telegram_leads


PROJECT = Path(__file__).resolve().parents[1]


class TelegramLeadDomainTests(unittest.TestCase):
    def lead(self, **changes):
        values = {
            "peer_id": -1001234567890,
            "message_id": 42,
            "channel_title": "Frontend вакансии",
            "channel_username": "frontend_jobs",
            "posted_at": datetime(2026, 8, 19, 11, 30, tzinfo=timezone.utc),
            "found_at": date(2026, 8, 20),
            "permalink": "https://t.me/frontend_jobs/42",
            "text": "React роль https://careers.example.test/jobs/42",
            "entities": [],
            "matched_terms": ["react"],
        }
        values.update(changes)
        return telegram_leads.build_lead(**values)

    def test_message_and_vacancy_identities_are_stable(self):
        self.assertEqual(
            telegram_leads.message_identity("-1001234567890", "42"),
            "telegram:-1001234567890:42",
        )
        url = "https://careers.example.test/jobs/42?ref=tg"
        digest = hashlib.sha256(url.encode()).hexdigest()
        self.assertEqual(
            telegram_leads.vacancy_candidate_identity(-1001234567890, 42, application_url=url),
            f"-1001234567890:42:sha256:{digest}",
        )
        first = telegram_leads.vacancy_candidate_identity(
            -1001234567890,
            42,
            company="  Example  Co ",
            role="RÉACT Engineer",
        )
        second = telegram_leads.vacancy_candidate_identity(
            -1001234567890,
            42,
            company="example co",
            role="réact   engineer",
        )
        self.assertEqual(first, second)

    def test_extracts_entity_and_regex_urls_deduplicates_and_rejects_schemes(self):
        text = "😀 apply https://jobs.example.test/a and https://jobs.example.test/a. tg://resolve?id=1"
        utf16_offset = len("😀 apply ".encode("utf-16-le")) // 2
        entities = [
            {"url": "https://redirect.example.test/role"},
            {"url": "javascript:alert(1)"},
            {"offset": utf16_offset, "length": len("https://jobs.example.test/a")},
        ]
        self.assertEqual(
            telegram_leads.extract_http_urls(text, entities),
            [
                "https://redirect.example.test/role",
                "https://jobs.example.test/a",
            ],
        )

    def test_unicode_keyword_matching_and_empty_text_are_deterministic(self):
        self.assertEqual(
            telegram_leads.match_keywords("Ищем RÉACT / TypeScript", ["réact", "typescript", "Vue"]),
            ["réact", "typescript"],
        )
        lead = self.lead(text="", matched_terms=[], permalink="https://t.me/c/1234567890/42")
        self.assertEqual(lead["outbound_urls"], [])
        self.assertEqual(lead["text"], "")

    def test_found_at_datetime_uses_business_calendar(self):
        lead = self.lead(found_at=datetime(2026, 8, 19, 22, 30, tzinfo=timezone.utc))
        self.assertEqual(lead["found_at"], "2026-08-20")

    def test_forward_and_edit_metadata_are_local_lead_fields(self):
        lead = self.lead(
            edited_at="2026-08-19T12:00:00+00:00",
            forwarded_from={"channel_title": "Source channel", "message_id": 7},
        )
        self.assertEqual(lead["edited_at"], "2026-08-19T12:00:00Z")
        self.assertEqual(lead["forwarded_from"]["message_id"], 7)

    def test_strict_validation_rejects_inconsistent_identity_and_unknown_fields(self):
        lead = self.lead()
        with self.assertRaisesRegex(telegram_leads.TelegramLeadError, "message_identity"):
            telegram_leads.validate_lead({**lead, "message_identity": "telegram:1:42"})
        with self.assertRaisesRegex(telegram_leads.TelegramLeadError, "unknown fields"):
            telegram_leads.validate_lead({**lead, "session": "secret"})

    def test_dedupe_is_stable_within_batch_and_against_history(self):
        first = self.lead()
        second = self.lead(message_id=43, permalink="https://t.me/frontend_jobs/43")
        unique, duplicates = telegram_leads.deduplicate_leads(
            [first, first, second],
            seen_identities={first["message_identity"]},
        )
        self.assertEqual([lead["message_id"] for lead in unique], [43])
        self.assertEqual(duplicates, 2)

    def test_projection_has_confirmed_fields_and_no_raw_text(self):
        lead = self.lead(
            text="Two roles with private details and phone number",
            forwarded_from={"channel_title": "Private source"},
        )
        record = telegram_leads.project_confirmed_lead(
            lead,
            company="ExampleCo",
            role="Frontend Engineer",
            application_url="https://careers.example.test/jobs/frontend",
            raw_location="Europe",
        )
        serialized = json.dumps(record, ensure_ascii=False)
        self.assertEqual(record["source"], "Telegram")
        self.assertEqual(record["source_url"], "https://t.me/frontend_jobs/42")
        self.assertNotIn("private details", serialized)
        self.assertNotIn("text", record["payload"]["telegram"])
        self.assertEqual(record["posted_at"], "2026-08-19")

    def test_projection_uses_company_role_fallback_without_exact_outbound_url(self):
        lead = self.lead(text="Two roles, contact the author", matched_terms=["role"])
        frontend = telegram_leads.project_confirmed_lead(
            lead,
            company="ExampleCo",
            role="Frontend Engineer",
            application_url="https://careers.example.test/jobs/shared",
            raw_location="Europe",
        )
        designer = telegram_leads.project_confirmed_lead(
            lead,
            company="ExampleCo",
            role="Product Designer",
            application_url="https://careers.example.test/jobs/shared",
            raw_location="Europe",
        )
        self.assertNotEqual(frontend["source_job_id"], designer["source_job_id"])
        self.assertEqual(
            frontend["source_job_id"],
            telegram_leads.vacancy_candidate_identity(
                lead["peer_id"],
                lead["message_id"],
                company="ExampleCo",
                role="Frontend Engineer",
            ),
        )


class TelegramLeadStorageTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.data_dir = self.root / "private" / "telegram"

    def tearDown(self):
        self.temporary.cleanup()

    def lead(self, message_id=42):
        return telegram_leads.build_lead(
            peer_id=-1001234567890,
            message_id=message_id,
            channel_title="Example jobs",
            posted_at="2026-08-19T11:30:00Z",
            found_at="2026-08-20",
            permalink=f"https://t.me/example_jobs/{message_id}",
            text=f"Frontend https://careers.example.test/jobs/{message_id}",
            matched_terms=["Frontend"],
        )

    def test_data_dir_precedence_and_private_allowlist(self):
        explicit = self.root / "explicit"
        self.assertEqual(
            telegram_leads.resolve_data_dir(explicit, environ={telegram_leads.DATA_DIR_ENV: "/ignored"}),
            explicit.resolve(),
        )
        env_path = self.root / "from-env"
        self.assertEqual(
            telegram_leads.resolve_data_dir(environ={telegram_leads.DATA_DIR_ENV: str(env_path)}),
            env_path.resolve(),
        )
        path = telegram_leads.write_allowlist(self.data_dir, [-1002, "-1001", -1002])
        self.assertEqual(telegram_leads.load_allowlist(self.data_dir), [-1002, -1001])
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(stat.S_IMODE(self.data_dir.stat().st_mode), 0o700)

    def test_private_dir_hardens_created_ancestors_and_spares_existing_ones(self):
        shared = self.root / "shared"
        shared.mkdir()
        os.chmod(shared, 0o755)
        target = shared / "nested" / "job-tracker" / "telegram"
        telegram_leads.ensure_private_dir(target)
        if os.name == "nt":
            return
        # A directory holding credentials, session and raw message text must not
        # sit under world-traversable parents this call created itself.
        for created in (shared / "nested", shared / "nested" / "job-tracker", target):
            self.assertEqual(stat.S_IMODE(created.stat().st_mode), 0o700, created)
        # An already existing directory above the target may be a shared user
        # directory, so its permissions are left alone.
        self.assertEqual(stat.S_IMODE(shared.stat().st_mode), 0o755)

    def test_inbox_batch_publishes_without_changing_shared_directory_permissions(self):
        record = telegram_leads.project_confirmed_lead(
            self.lead(),
            company="ExampleCo",
            role="Frontend Engineer",
            application_url="https://careers.example.test/jobs/42",
            raw_location="Worldwide",
        )
        inbox_dir = self.root / "shared-inbox"
        inbox_dir.mkdir()
        os.chmod(inbox_dir, 0o755)
        batch = telegram_leads.write_inbox_batch(inbox_dir, [record], validate=True)
        if os.name == "nt":
            return
        # data/inbox is a shared repository directory holding only confirmed
        # facts; publishing a Telegram batch must not silently reduce access to
        # it for the operator or other adapters.
        self.assertEqual(stat.S_IMODE(inbox_dir.stat().st_mode), 0o755)
        self.assertEqual(stat.S_IMODE(batch.stat().st_mode), 0o600)

    def test_immutable_batches_collision_safe_and_seen_identity_dedupe(self):
        run_at = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        with patch.object(
            telegram_leads.secrets, "token_hex", side_effect=["aaaaaaaa", "aaaaaaaa", "bbbbbbbb"]
        ):
            first = telegram_leads.write_lead_batch(self.data_dir, [self.lead()], run_at=run_at)
            second = telegram_leads.write_lead_batch(self.data_dir, [self.lead(43)], run_at=run_at)
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), first.read_bytes())
        self.assertEqual(
            telegram_leads.load_seen_identities(self.data_dir),
            {
                "telegram:-1001234567890:42",
                "telegram:-1001234567890:43",
            },
        )
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)

    def test_serialization_or_publish_error_never_exposes_final_batch(self):
        inbox_dir = self.root / "data" / "inbox"
        with self.assertRaisesRegex(telegram_leads.TelegramLeadError, "immutable batch"):
            telegram_leads.write_inbox_batch(
                inbox_dir,
                [{"not_json": object()}],
                validate=False,
            )
        self.assertEqual(list(inbox_dir.glob("telegram-*.jsonl")), [])
        self.assertEqual(list(inbox_dir.glob(".*.tmp")), [])

        with patch.object(telegram_leads.os, "link", side_effect=OSError("publish failed")):
            with self.assertRaisesRegex(telegram_leads.TelegramLeadError, "publish failed"):
                telegram_leads.write_inbox_batch(
                    inbox_dir,
                    [{"complete": True}],
                    validate=False,
                )
        self.assertEqual(list(inbox_dir.glob("telegram-*.jsonl")), [])
        self.assertEqual(list(inbox_dir.glob(".*.tmp")), [])

    def test_publish_fsyncs_file_before_link_and_parent_after_link(self):
        inbox_dir = self.root / "data" / "inbox"
        events = []
        real_fsync = telegram_leads.os.fsync
        real_link = telegram_leads.os.link

        def observed_fsync(descriptor):
            events.append("fsync")
            return real_fsync(descriptor)

        def observed_link(source, target):
            events.append("link")
            return real_link(source, target)

        with (
            patch.object(telegram_leads.os, "fsync", side_effect=observed_fsync),
            patch.object(telegram_leads.os, "link", side_effect=observed_link),
        ):
            path = telegram_leads.write_inbox_batch(
                inbox_dir,
                [{"complete": True}],
                validate=False,
            )

        self.assertTrue(path.exists())
        self.assertEqual(events, ["fsync", "link", "fsync"])

    def test_parent_fsync_failure_leaves_complete_batch_but_never_advances_cursor(self):
        peer_id = -1001234567890
        calls = 0

        def fail_batch_directory(_path):
            nonlocal calls
            calls += 1
            raise OSError("directory fsync failed")

        with patch.object(telegram_leads, "_fsync_directory", side_effect=fail_batch_directory):
            with self.assertRaisesRegex(telegram_leads.TelegramLeadError, "directory fsync failed"):
                telegram_leads.commit_lead_batch(
                    self.data_dir,
                    [self.lead()],
                    {peer_id: 42},
                )

        self.assertEqual(calls, 1)
        published = list((self.data_dir / "leads").glob("telegram-leads-*.jsonl"))
        self.assertEqual(len(published), 1)
        self.assertEqual(len(published[0].read_text(encoding="utf-8").splitlines()), 1)
        self.assertEqual(telegram_leads.load_state(self.data_dir)["peers"], {})

    def test_commit_writes_batch_before_cursor_and_fault_preserves_old_state(self):
        peer_id = -1001234567890
        run_at = datetime(2026, 8, 20, 12, tzinfo=timezone.utc)
        first = telegram_leads.commit_lead_batch(
            self.data_dir,
            [self.lead()],
            {peer_id: 42},
            run_at=run_at,
        )
        self.assertTrue(first.exists())
        self.assertEqual(
            telegram_leads.load_state(self.data_dir)["peers"][str(peer_id)]["last_message_id"],
            42,
        )

        def crash(batch_path):
            self.assertTrue(batch_path.exists())
            raise RuntimeError("simulated crash")

        with self.assertRaisesRegex(RuntimeError, "simulated crash"):
            telegram_leads.commit_lead_batch(
                self.data_dir,
                [self.lead(43)],
                {peer_id: 43},
                run_at=run_at,
                before_state_write=crash,
            )
        self.assertEqual(
            telegram_leads.load_state(self.data_dir)["peers"][str(peer_id)]["last_message_id"],
            42,
        )
        self.assertIn("telegram:-1001234567890:43", telegram_leads.load_seen_identities(self.data_dir))

    def test_find_requires_exactly_one_and_summary_hides_text(self):
        telegram_leads.write_lead_batch(self.data_dir, [self.lead()])
        found = telegram_leads.find_lead(self.data_dir, "telegram:-1001234567890:42")
        self.assertNotIn("text", telegram_leads.lead_summary(found))
        self.assertIn("text", telegram_leads.lead_summary(found, include_text=True))
        with self.assertRaisesRegex(telegram_leads.TelegramLeadError, "found 0"):
            telegram_leads.find_lead(self.data_dir, "telegram:-1001234567890:999")

    def test_pull_lock_is_owner_only_nonblocking_and_reusable(self):
        with telegram_leads.pull_lock(self.data_dir) as lock_path:
            self.assertTrue(lock_path.exists())
            if os.name != "nt":
                self.assertEqual(stat.S_IMODE(lock_path.stat().st_mode), 0o600)
            with self.assertRaisesRegex(
                telegram_leads.TelegramLeadError,
                "another Telegram pull is already running",
            ):
                with telegram_leads.pull_lock(self.data_dir):
                    self.fail("concurrent lock must not be acquired")
            contender = subprocess.run(
                [
                    sys.executable,
                    "-c",
                    (
                        "import sys; "
                        "from scripts.telegram_leads import pull_lock, TelegramLeadError; "
                        "\ntry:\n with pull_lock(sys.argv[1]): pass"
                        "\nexcept TelegramLeadError as error:\n print(error); raise SystemExit(3)"
                    ),
                    str(self.data_dir),
                ],
                cwd=PROJECT,
                text=True,
                capture_output=True,
            )
            self.assertEqual(contender.returncode, 3, contender.stderr)
            self.assertIn("another Telegram pull is already running", contender.stdout)

        with telegram_leads.pull_lock(self.data_dir) as reused_path:
            self.assertEqual(reused_path, lock_path)

    def test_write_inbox_batch_is_immutable_owner_only(self):
        record = telegram_leads.project_confirmed_lead(
            self.lead(),
            company="ExampleCo",
            role="Frontend Engineer",
            application_url="https://careers.example.test/jobs/42",
            raw_location="Worldwide",
        )
        inbox_dir = self.root / "data" / "inbox"
        first = telegram_leads.write_inbox_batch(inbox_dir, [record], validate=True)
        second = telegram_leads.write_inbox_batch(inbox_dir, [record], validate=True)
        self.assertNotEqual(first, second)
        saved = json.loads(first.read_text(encoding="utf-8"))
        self.assertEqual(saved, record)
        if os.name != "nt":
            self.assertEqual(stat.S_IMODE(first.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
