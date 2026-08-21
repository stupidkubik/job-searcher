import io
import json
import tempfile
import unittest
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from scripts import import_telegram


NOW = datetime(2026, 8, 20, 10, 0, tzinfo=timezone.utc)
REAL_DOMAIN = import_telegram.telegram_leads


class FakeMessage:
    def __init__(self, message_id, text, *, age_hours=1, edit_date=None, entities=(), fwd_from=None):
        self.id = message_id
        self.message = text
        self.date = NOW - timedelta(hours=age_hours)
        self.edit_date = edit_date
        self.entities = entities
        self.fwd_from = fwd_from


class MalformedMessage:
    """A message Telethon can yield but the adapter cannot project at all."""

    def __init__(self, message_id):
        self.id = message_id
        self.message = "Frontend react"
        self.date = None
        self.edit_date = None
        self.entities = ()
        self.fwd_from = None


class MalformedHistoryClient:
    """Ascending history without server-side filtering of malformed messages."""

    def __init__(self, messages):
        self.messages = messages
        self.yielded = []

    async def get_entity(self, peer_id):
        return SimpleNamespace(
            title=f"Channel {abs(peer_id)}",
            username=f"channel{abs(peer_id)}",
            broadcast=True,
            megagroup=False,
        )

    def iter_messages(self, peer_id, *, limit, min_id, offset_date, reverse):
        async def iterate():
            selected = [
                message for message in self.messages
                if not isinstance(message.id, int) or message.id > min_id
            ]
            for message in sorted(selected, key=lambda item: item.id or 0)[:limit]:
                self.yielded.append(message.id)
                yield message

        return iterate()


class FloodWaitError(Exception):
    def __init__(self, seconds):
        super().__init__("sensitive provider error deliberately not surfaced")
        self.seconds = seconds


class FakeClient:
    def __init__(self, messages=None, failures=None):
        self.messages = messages or {}
        self.failures = failures or {}
        self.entities = {
            peer_id: SimpleNamespace(
                title=f"Channel {abs(peer_id)}",
                username=f"channel{abs(peer_id)}",
                broadcast=True,
                megagroup=False,
            )
            for peer_id in self.messages
        }
        self.iter_calls = []
        self.offset_dates = []
        self.entity_calls = []
        self.yielded = []

    async def get_entity(self, peer_id):
        self.entity_calls.append(peer_id)
        if peer_id in self.failures:
            raise self.failures[peer_id]
        return self.entities.get(peer_id, SimpleNamespace(title="Channel", username=None))

    def iter_messages(self, peer_id, *, limit, min_id, offset_date, reverse):
        self.iter_calls.append({
            "peer_id": peer_id, "limit": limit, "min_id": min_id, "reverse": reverse,
        })
        self.offset_dates.append(offset_date)

        async def iterate():
            messages = [message for message in self.messages.get(peer_id, ()) if message.id > min_id]
            if offset_date is not None and reverse:
                messages = [message for message in messages if message.date > offset_date]
            messages.sort(key=lambda message: message.id, reverse=not reverse)
            for message in messages[:limit]:
                if message.id <= min_id:
                    continue
                self.yielded.append((peer_id, message.id))
                yield message

        return iterate()


class FakeLeadDomain:
    def __init__(self, *, state=None, seen=None):
        self.state = state or {"version": 1, "peers": {}}
        self.seen = set(seen or ())
        self.commits = []
        self.build_calls = []
        self.lock_events = []
        self.locked = False

    @contextmanager
    def pull_lock(self, data_dir):
        self.lock_events.append(("enter", data_dir))
        self.locked = True
        try:
            yield data_dir / "pull.lock"
        finally:
            self.locked = False
            self.lock_events.append(("exit", data_dir))

    @staticmethod
    def normalize_peer_id(value):
        value = int(value)
        if value == 0:
            raise ValueError("invalid peer")
        return value

    @staticmethod
    def normalize_message_id(value):
        value = int(value)
        if value <= 0:
            raise ValueError("invalid message")
        return value

    def load_state(self, _data_dir):
        assert self.locked
        return self.state

    def load_seen_identities(self, _data_dir):
        assert self.locked
        return self.seen

    @staticmethod
    def match_keywords(text, terms):
        folded = text.casefold()
        return [term for term in terms if term.casefold() in folded]

    @staticmethod
    def extract_http_urls(text, _entities):
        return [word for word in text.split() if word.startswith(("http://", "https://"))]

    def build_lead(self, **values):
        self.build_calls.append(values)
        return {
            "identity": f"telegram:{values['peer_id']}:{values['message_id']}",
            "message_id": values["message_id"],
            "edited_at": values.get("edited_at"),
        }

    @staticmethod
    def deduplicate_leads(leads, seen):
        unique, identities = [], set(seen)
        duplicates = 0
        for lead in leads:
            if lead["identity"] in identities:
                duplicates += 1
            else:
                identities.add(lead["identity"])
                unique.append(lead)
        return unique, duplicates

    def commit_lead_batch(self, data_dir, leads, cursor_updates, *, run_at):
        assert self.locked
        self.commits.append({
            "data_dir": data_dir,
            "leads": leads,
            "cursor_updates": cursor_updates,
            "run_at": run_at,
        })
        for peer_id, message_id in cursor_updates.items():
            self.state["peers"][str(peer_id)] = {"last_message_id": message_id}
        self.seen.update(lead["identity"] for lead in leads)
        return data_dir / "leads" / "telegram-test.jsonl"


class TelegramPullTests(unittest.IsolatedAsyncioTestCase):
    async def test_initial_pull_starts_at_retention_cutoff_instead_of_oldest_history(self):
        peer_id = -100123
        client = FakeClient({peer_id: [
            FakeMessage(1, "old frontend", age_hours=24 * 30),
            FakeMessage(2, "recent frontend", age_hours=24),
        ]})
        domain = FakeLeadDomain()
        with patch.object(import_telegram, "telegram_leads", domain):
            summary = await import_telegram.collect_pull(
                client,
                Path("/local/telegram"),
                peer_ids=[peer_id],
                max_age_days=7,
                keywords=["frontend"],
                now=NOW,
            )

        self.assertEqual(client.offset_dates, [NOW - timedelta(days=7)])
        self.assertEqual(client.yielded, [(peer_id, 2)])
        self.assertEqual(summary["fetched"], 1)
        self.assertEqual(domain.commits[0]["cursor_updates"], {peer_id: 2})

    async def test_fake_client_pull_runs_end_to_end_with_real_domain_and_storage(self):
        peer_id = -100123
        client = FakeClient({
            peer_id: [FakeMessage(
                15,
                "Frontend https://jobs.example.test/15",
                edit_date=NOW - timedelta(minutes=5),
                fwd_from=SimpleNamespace(from_name="Recruiter", channel_id=None, from_id=None),
            )],
        })
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            summary = await import_telegram.collect_pull(
                client,
                data_dir,
                peer_ids=[peer_id],
                keywords=["frontend"],
                now=NOW,
            )
            leads = list(REAL_DOMAIN.iter_stored_leads(data_dir))
            state = REAL_DOMAIN.load_state(data_dir)

        self.assertEqual(summary["status"], "ok")
        self.assertEqual((summary["matched"], summary["written"]), (1, 1))
        self.assertEqual(leads[0]["message_identity"], f"telegram:{peer_id}:15")
        self.assertEqual(leads[0]["forwarded_from"], {"from_name": "Recruiter"})
        self.assertEqual(leads[0]["edited_at"], "2026-08-20T09:55:00Z")
        self.assertEqual(state["peers"][str(peer_id)]["last_message_id"], 15)

    async def test_pull_is_bounded_to_allowlist_and_keeps_edit_metadata(self):
        peer_id = -100123
        edited_at = NOW - timedelta(minutes=10)
        client = FakeClient({
            peer_id: [
                FakeMessage(14, "Frontend role", edit_date=edited_at),
                FakeMessage(13, "https://jobs.example.test/role"),
                FakeMessage(12, "unrelated announcement"),
                FakeMessage(11, "old frontend", age_hours=24 * 8),
            ],
            -100999: [FakeMessage(50, "frontend outside allowlist")],
        })
        domain = FakeLeadDomain(state={
            "version": 1,
            "peers": {str(peer_id): {"last_message_id": 10}},
        })
        with patch.object(import_telegram, "telegram_leads", domain):
            summary = await import_telegram.collect_pull(
                client,
                Path("/local/telegram"),
                peer_ids=[peer_id],
                max_age_days=7,
                max_messages_per_peer=25,
                keywords=["frontend"],
                now=NOW,
            )

        self.assertEqual(client.entity_calls, [peer_id])
        self.assertEqual(client.iter_calls, [{
            "peer_id": peer_id, "limit": 26, "min_id": 10, "reverse": True,
        }])
        self.assertEqual(client.yielded, [
            (peer_id, 11), (peer_id, 12), (peer_id, 13), (peer_id, 14),
        ])
        self.assertNotIn((-100999, 50), client.yielded)
        self.assertEqual(summary["fetched"], 4)
        self.assertEqual(summary["matched"], 2)
        self.assertEqual(summary["written"], 2)
        self.assertEqual(domain.build_calls[-1]["edited_at"], edited_at)
        self.assertEqual(domain.commits[0]["cursor_updates"], {peer_id: 14})
        self.assertEqual(domain.lock_events, [
            ("enter", Path("/local/telegram")), ("exit", Path("/local/telegram")),
        ])

    async def test_empty_channel_still_commits_successful_cursor_transaction(self):
        peer_id = -100123
        client = FakeClient({peer_id: []})
        domain = FakeLeadDomain()
        with patch.object(import_telegram, "telegram_leads", domain):
            summary = await import_telegram.collect_pull(
                client, Path("/local/telegram"), peer_ids=[peer_id], keywords=["frontend"], now=NOW
            )
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["written"], 0)
        self.assertEqual(domain.commits[0]["cursor_updates"], {})

    async def test_seen_identity_is_counted_as_duplicate(self):
        peer_id = -100123
        identity = f"telegram:{peer_id}:15"
        client = FakeClient({peer_id: [FakeMessage(15, "frontend")]})
        domain = FakeLeadDomain(seen={identity})
        with patch.object(import_telegram, "telegram_leads", domain):
            summary = await import_telegram.collect_pull(
                client, Path("/local/telegram"), peer_ids=[peer_id], keywords=["frontend"], now=NOW
            )
        self.assertEqual((summary["duplicates"], summary["written"]), (1, 0))

    async def test_exact_n_messages_is_not_reported_as_backlog(self):
        peer_id = -100123
        client = FakeClient({peer_id: [
            FakeMessage(message_id, "frontend") for message_id in (13, 12, 11)
        ]})
        domain = FakeLeadDomain(state={
            "version": 1, "peers": {str(peer_id): {"last_message_id": 10}},
        })
        with patch.object(import_telegram, "telegram_leads", domain):
            summary = await import_telegram.collect_pull(
                client,
                Path("/local/telegram"),
                peer_ids=[peer_id],
                max_messages_per_peer=3,
                keywords=["frontend"],
                now=NOW,
            )
        self.assertEqual(summary["status"], "ok")
        self.assertEqual(summary["backlog_peers"], [])
        self.assertEqual(summary["fetched"], 3)
        self.assertEqual(domain.commits[0]["cursor_updates"], {peer_id: 13})

    async def test_n_plus_one_sentinel_advances_n_then_next_run_finishes_without_skip(self):
        peer_id = -100123
        client = FakeClient({peer_id: [
            FakeMessage(message_id, "frontend") for message_id in (14, 13, 12, 11)
        ]})
        domain = FakeLeadDomain(state={
            "version": 1, "peers": {str(peer_id): {"last_message_id": 10}},
        })
        with patch.object(import_telegram, "telegram_leads", domain):
            first = await import_telegram.collect_pull(
                client,
                Path("/local/telegram"),
                peer_ids=[peer_id],
                max_messages_per_peer=3,
                keywords=["frontend"],
                now=NOW,
            )
            second = await import_telegram.collect_pull(
                client,
                Path("/local/telegram"),
                peer_ids=[peer_id],
                max_messages_per_peer=3,
                keywords=["frontend"],
                now=NOW + timedelta(minutes=1),
            )

        self.assertEqual(first["fetched"], 3)
        self.assertEqual(first["backlog_peers"], [peer_id])
        self.assertEqual(domain.commits[0]["cursor_updates"], {peer_id: 13})
        self.assertEqual(second["fetched"], 1)
        self.assertEqual(second["backlog_peers"], [])
        self.assertEqual(domain.commits[1]["cursor_updates"], {peer_id: 14})
        self.assertEqual(
            [call["message_id"] for call in domain.build_calls], [11, 12, 13, 14]
        )

    async def test_peer_failure_produces_partial_summary_and_does_not_advance_failed_cursor(self):
        good, failed = -100111, -100222
        client = FakeClient(
            {good: [FakeMessage(7, "frontend")]}, failures={failed: RuntimeError("private detail")}
        )
        domain = FakeLeadDomain()
        with patch.object(import_telegram, "telegram_leads", domain):
            summary = await import_telegram.collect_pull(
                client,
                Path("/local/telegram"),
                peer_ids=[good, failed],
                keywords=["frontend"],
                now=NOW,
            )
        self.assertEqual(summary["status"], "partial")
        self.assertEqual(summary["peers"], {
            "requested": 2, "completed": 1, "failed": 1, "backlog": 0,
        })
        self.assertEqual(summary["errors"], [{"peer_id": failed, "kind": "RuntimeError"}])
        self.assertEqual(domain.commits[0]["cursor_updates"], {good: 7})

    async def test_unusable_message_does_not_strand_the_rest_of_the_peer(self):
        peer_id = -100123
        client = MalformedHistoryClient([
            FakeMessage(11, "Frontend https://jobs.example.test/11"),
            MalformedMessage(12),
            FakeMessage(13, "Frontend https://jobs.example.test/13"),
        ])
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            first = await import_telegram.collect_pull(
                client, data_dir, peer_ids=[peer_id], keywords=["frontend"], now=NOW,
            )
            state = REAL_DOMAIN.load_state(data_dir)
            second = await import_telegram.collect_pull(
                client,
                data_dir,
                peer_ids=[peer_id],
                keywords=["frontend"],
                now=NOW + timedelta(minutes=1),
            )
            identities = [
                lead["message_identity"] for lead in REAL_DOMAIN.iter_stored_leads(data_dir)
            ]

        # The unusable message is reported instead of aborting the peer: the rest
        # of the channel is collected on the same run and the cursor moves past
        # it, so the next run is not a permanent retry of the same failure.
        self.assertEqual(first["peers"], {
            "requested": 1, "completed": 1, "failed": 0, "backlog": 0,
        })
        self.assertEqual((first["fetched"], first["written"], first["skipped"]), (3, 2, 1))
        self.assertEqual(first["skipped_messages"], [{
            "peer_id": peer_id,
            "kind": "TelegramImportError",
            "detail": "Telegram returned a message without a valid date",
            "message_id": 12,
        }])
        self.assertEqual(first["status"], "partial")
        self.assertEqual(state["peers"][str(peer_id)]["last_message_id"], 13)
        self.assertEqual(identities, [f"telegram:{peer_id}:11", f"telegram:{peer_id}:13"])
        self.assertEqual(
            (second["status"], second["fetched"], second["duplicates"]), ("ok", 0, 0)
        )

    async def test_message_without_usable_id_is_skipped_and_a_later_message_advances(self):
        peer_id = -100123
        unidentified = FakeMessage(None, "Frontend https://jobs.example.test/unknown")
        client = MalformedHistoryClient([
            unidentified, FakeMessage(21, "Frontend https://jobs.example.test/21"),
        ])
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary)
            summary = await import_telegram.collect_pull(
                client, data_dir, peer_ids=[peer_id], keywords=["frontend"], now=NOW,
            )
            state = REAL_DOMAIN.load_state(data_dir)
            identities = [
                lead["message_identity"] for lead in REAL_DOMAIN.iter_stored_leads(data_dir)
            ]

        # Without an ID the cursor cannot skip this message on its own, so the
        # next identified message is what advances past it.
        self.assertEqual(summary["skipped_messages"][0]["message_id"], None)
        self.assertEqual(summary["skipped_messages"][0]["kind"], "TelegramLeadError")
        self.assertEqual((summary["fetched"], summary["written"]), (2, 1))
        self.assertEqual(state["peers"][str(peer_id)]["last_message_id"], 21)
        self.assertEqual(identities, [f"telegram:{peer_id}:21"])

    def test_skip_reports_own_contract_detail_but_never_provider_text(self):
        own = import_telegram._safe_message_error(
            -100123, 12, import_telegram.TelegramImportError("safe operator detail"),
        )
        domain = import_telegram._safe_message_error(
            -100123, 12, REAL_DOMAIN.TelegramLeadError("permalink must be a non-empty string"),
        )
        provider = import_telegram._safe_message_error(
            -100123, 12, RuntimeError("session id 12345"),
        )
        self.assertEqual(own["detail"], "safe operator detail")
        self.assertEqual(domain["detail"], "permalink must be a non-empty string")
        self.assertEqual(provider, {"peer_id": -100123, "kind": "RuntimeError", "message_id": 12})

    async def test_flood_wait_is_reported_without_retry(self):
        peer_id = -100123
        client = FakeClient(failures={peer_id: FloodWaitError(91)})
        domain = FakeLeadDomain()
        with patch.object(import_telegram, "telegram_leads", domain):
            summary = await import_telegram.collect_pull(
                client, Path("/local/telegram"), peer_ids=[peer_id], keywords=["frontend"], now=NOW
            )
        self.assertEqual(client.entity_calls, [peer_id])
        self.assertEqual(summary["errors"], [{
            "peer_id": peer_id, "kind": "FloodWaitError", "retry_after_seconds": 91,
        }])

    async def test_pull_refuses_empty_allowlist_without_touching_client(self):
        client = FakeClient({-100123: [FakeMessage(1, "frontend")]})
        domain = FakeLeadDomain()
        with patch.object(import_telegram, "telegram_leads", domain):
            with self.assertRaisesRegex(import_telegram.TelegramImportError, "allowlist"):
                await import_telegram.collect_pull(
                    client, Path("/local/telegram"), peer_ids=[], keywords=["frontend"], now=NOW
                )
        self.assertEqual(client.entity_calls, [])


class TelegramCliTests(unittest.TestCase):
    def test_network_allowlist_and_normalize_reject_data_dir_inside_checkout(self):
        forbidden = import_telegram.ROOT / "data" / "telegram-private"
        commands = [
            ["login"],
            ["allowlist", "show"],
            [
                "normalize", "telegram:-100123:9",
                "--company", "Example",
                "--role", "Frontend Developer",
                "--application-url", "https://example.test/jobs/9",
                "--raw-location", "Serbia",
            ],
        ]
        for command in commands:
            with self.subTest(command=command):
                stderr = io.StringIO()
                with redirect_stderr(stderr):
                    exit_code = import_telegram.main([
                        "--data-dir", str(forbidden), *command,
                    ])
                self.assertEqual(exit_code, 1)
                self.assertIn("outside the repository checkout", stderr.getvalue())
        self.assertFalse(forbidden.exists())

    def test_partial_pull_exits_nonzero_so_skips_are_not_silently_accepted(self):
        summaries = {
            "ok": {"status": "ok", "skipped": 0, "errors": []},
            "partial": {"status": "partial", "skipped": 1, "errors": []},
        }
        for status, summary in summaries.items():
            with self.subTest(status=status):
                stdout = io.StringIO()
                with patch.object(
                    import_telegram, "_run_network_command", new=AsyncMock(return_value=summary)
                ), redirect_stdout(stdout):
                    exit_code = import_telegram.main(["--data-dir", "/tmp/telegram-test", "pull"])
                self.assertEqual(exit_code, 0 if status == "ok" else 2)

    def test_provider_exception_text_is_not_logged(self):
        stderr = io.StringIO()
        with patch.object(
            import_telegram, "_run_network_command", new=AsyncMock(side_effect=RuntimeError("secret detail"))
        ), redirect_stderr(stderr):
            exit_code = import_telegram.main(["--data-dir", "/tmp/telegram-test", "login"])
        self.assertEqual(exit_code, 1)
        self.assertIn("RuntimeError", stderr.getvalue())
        self.assertNotIn("secret detail", stderr.getvalue())

    def test_client_disables_automatic_flood_wait_and_uses_private_session_dir(self):
        calls = []

        class Client:
            def __init__(self, *args, **kwargs):
                calls.append((args, kwargs))

        runtime = import_telegram.TelegramRuntime(client_class=Client, get_peer_id=lambda value: value)
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "telegram"
            resolved_data_dir = data_dir.resolve()
            import_telegram.create_client(
                runtime,
                data_dir,
                environ={"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "super-secret"},
            )
            mode = data_dir.stat().st_mode & 0o777
        self.assertEqual(mode, 0o700)
        self.assertEqual(calls[0][0], (
            str(resolved_data_dir / "telegram"), 123, "super-secret",
        ))
        self.assertEqual(calls[0][1], {"flood_sleep_threshold": 0, "request_retries": 1})

    def test_optional_dependency_is_lazy_and_missing_dependency_has_safe_error(self):
        real_import = import_telegram.importlib.import_module

        def missing(name):
            if name == "telethon":
                error = ModuleNotFoundError("No module named telethon")
                error.name = "telethon"
                raise error
            return real_import(name)

        with patch.object(import_telegram.importlib, "import_module", side_effect=missing):
            with self.assertRaisesRegex(import_telegram.TelegramImportError, "requirements/telegram.txt"):
                import_telegram.load_telethon()

    def test_credentials_are_presence_checked_without_returning_them_in_doctor(self):
        domain = SimpleNamespace(load_allowlist=lambda _path: [-100123])
        with patch.object(import_telegram, "telegram_leads", domain):
            result = import_telegram.doctor(
                Path("/does/not/exist"),
                environ={"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "super-secret"},
                runtime_loader=lambda: object(),
            )
        serialized = json.dumps(result)
        self.assertEqual(result["status"], "ok")
        self.assertNotIn("super-secret", serialized)
        self.assertNotIn("123", serialized)

    def test_doctor_treats_missing_allowlist_as_setup_step_not_broken_prerequisite(self):
        domain = SimpleNamespace(load_allowlist=lambda _path: [])
        with patch.object(import_telegram, "telegram_leads", domain):
            result = import_telegram.doctor(
                Path("/does/not/exist"),
                environ={"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "super-secret"},
                runtime_loader=lambda: object(),
            )

        self.assertEqual(result["status"], "ok")
        self.assertFalse(result["ready_for_pull"])
        self.assertEqual(result["next_action"], "configure allowlist")
        self.assertFalse(result["checks"]["allowlist"]["ok"])

    @staticmethod
    def _private_tree(data_dir):
        """Build the tree a real login and pull leave behind."""
        REAL_DOMAIN.ensure_private_dir(data_dir)
        REAL_DOMAIN.write_allowlist(data_dir, [-100123])
        lead = REAL_DOMAIN.build_lead(
            peer_id=-100123,
            message_id=5,
            channel_title="Channel",
            channel_username="channel",
            posted_at=NOW,
            found_at=NOW,
            permalink="https://t.me/channel/5",
            text="Frontend react, salary and recruiter contact",
        )
        REAL_DOMAIN.commit_lead_batch(data_dir, [lead], {-100123: 5}, run_at=NOW)
        with REAL_DOMAIN.pull_lock(data_dir):
            pass
        session = data_dir / f"{import_telegram.SESSION_BASENAME}.session"
        session.write_text("session material", encoding="utf-8")
        session.chmod(0o600)
        return next((data_dir / "leads").glob("*.jsonl"))

    def test_permission_audit_covers_the_raw_lead_spool_subdirectory(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "telegram"
            batch = self._private_tree(data_dir)
            # A top-level-only audit reports owner-only here while the full
            # message text is world-readable.
            (data_dir / "leads").chmod(0o755)
            batch.chmod(0o644)
            issues = import_telegram.owner_only_permission_issues(data_dir)
            result = import_telegram.doctor(
                data_dir,
                environ={"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "hash"},
                runtime_loader=lambda: object(),
            )

        self.assertEqual(issues, ["leads", f"leads/{batch.name}"])
        self.assertFalse(result["checks"]["permissions"]["ok"])
        self.assertEqual(result["checks"]["permissions"]["paths"], issues)
        self.assertEqual(result["status"], "error")
        self.assertFalse(result["ready_for_pull"])

    def test_permission_audit_accepts_the_tree_a_real_pull_leaves_behind(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "telegram"
            self._private_tree(data_dir)
            issues = import_telegram.owner_only_permission_issues(data_dir)
            missing = import_telegram.owner_only_permission_issues(Path(temporary) / "absent")

        # A check which cried wolf over session, state, allowlist, lock and lead
        # files would be ignored in practice.
        self.assertEqual(issues, [])
        self.assertEqual(missing, [])

    def test_permission_audit_reports_symlinks_instead_of_following_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "telegram"
            self._private_tree(data_dir)
            public = Path(temporary) / "public"
            public.mkdir(mode=0o755)
            (public / "copy.jsonl").write_text("{}", encoding="utf-8")
            (public / "copy.jsonl").chmod(0o644)
            (data_dir / "escape").symlink_to(public)
            issues = import_telegram.owner_only_permission_issues(data_dir)

        # Reported by name only: the audit must not walk out of the private
        # boundary, and a symlink's own mode bits say nothing about its target.
        self.assertEqual(issues, ["escape (symlink)"])

    def test_list_dialogs_only_returns_broadcasts_and_supergroups(self):
        entities = [
            SimpleNamespace(id=1, title="News", username="news", broadcast=True, megagroup=False),
            SimpleNamespace(id=2, title="Jobs", username=None, broadcast=False, megagroup=True),
            SimpleNamespace(id=3, title="Personal", username=None, broadcast=False, megagroup=False),
        ]

        class DialogClient:
            def iter_dialogs(self):
                async def iterate():
                    for entity in entities:
                        yield SimpleNamespace(entity=entity)
                return iterate()

        result = __import__("asyncio").run(
            import_telegram.list_dialogs(DialogClient(), get_peer_id=lambda entity: -100 - entity.id)
        )
        self.assertEqual([item["type"] for item in result], ["supergroup", "broadcast"])
        self.assertEqual([item["peer_id"] for item in result], [-102, -101])

    def test_normalize_cli_is_a_thin_human_confirmed_projection_without_raw_text(self):
        lead = REAL_DOMAIN.build_lead(
            peer_id=-100123,
            message_id=9,
            channel_title="Example jobs",
            channel_username="example_jobs",
            posted_at=NOW,
            found_at=NOW,
            permalink="https://t.me/example_jobs/9",
            text="private raw post https://example.test/jobs/9",
            matched_terms=["frontend"],
        )
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            data_dir, inbox_dir = root / "local", root / "inbox"
            REAL_DOMAIN.write_lead_batch(data_dir, [lead], run_at=NOW)
            stdout = io.StringIO()
            with redirect_stdout(stdout):
                exit_code = import_telegram.main([
                    "--data-dir", str(data_dir),
                    "normalize", lead["message_identity"],
                    "--company", "Example",
                    "--role", "Frontend Developer",
                    "--application-url", "https://example.test/jobs/9",
                    "--raw-location", "Serbia",
                    "--inbox-dir", str(inbox_dir),
                ])
            payload = json.loads(stdout.getvalue())
            record = json.loads(Path(payload["inbox_batch"]).read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(record["company"], "Example")
        self.assertEqual(record["source_job_id"], payload["source_job_id"])
        self.assertEqual(record["payload"]["telegram"]["message_identity"], lead["message_identity"])
        self.assertNotIn("text", record["payload"]["telegram"])
        self.assertNotIn("private raw post", stdout.getvalue())

    def test_leads_cli_lists_without_text_and_requires_opt_in_to_show_text(self):
        leads = [
            REAL_DOMAIN.build_lead(
                peer_id=-100123,
                message_id=message_id,
                channel_title="Example jobs",
                channel_username="example_jobs",
                posted_at=NOW,
                found_at=NOW,
                permalink=f"https://t.me/example_jobs/{message_id}",
                text=f"private message {message_id}",
                matched_terms=["frontend"],
            )
            for message_id in (9, 10)
        ]
        with tempfile.TemporaryDirectory() as temporary:
            data_dir = Path(temporary) / "local"
            REAL_DOMAIN.write_lead_batch(data_dir, leads, run_at=NOW)

            listed_stdout = io.StringIO()
            with redirect_stdout(listed_stdout):
                list_exit = import_telegram.main([
                    "--data-dir", str(data_dir), "leads", "list", "--limit", "1",
                ])
            listed = json.loads(listed_stdout.getvalue())

            hidden_stdout = io.StringIO()
            with redirect_stdout(hidden_stdout):
                hidden_exit = import_telegram.main([
                    "--data-dir", str(data_dir), "leads", "show", leads[0]["message_identity"],
                ])
            hidden = json.loads(hidden_stdout.getvalue())

            shown_stdout = io.StringIO()
            with redirect_stdout(shown_stdout):
                shown_exit = import_telegram.main([
                    "--data-dir", str(data_dir), "leads", "show", leads[0]["message_identity"],
                    "--include-text",
                ])
            shown = json.loads(shown_stdout.getvalue())

        self.assertEqual((list_exit, hidden_exit, shown_exit), (0, 0, 0))
        self.assertEqual((listed["count"], listed["returned"]), (2, 1))
        self.assertEqual(listed["leads"][0]["message_identity"], leads[1]["message_identity"])
        self.assertNotIn("text", listed["leads"][0])
        self.assertNotIn("text", hidden["lead"])
        self.assertEqual(shown["lead"]["text"], "private message 9")


if __name__ == "__main__":
    unittest.main()
