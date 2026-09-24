"""Conservative historical backfill and dry-run invariants."""

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import event_ledger, tracker_paths, tracker_transaction
from scripts.maintenance import backfill_application_events as migration


class BackfillApplicationEventsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        self.rows = [
            self.row("job-0001", "not_started", "None"),
            self.row("job-0002", "applied", "Applied", "2026-09-01"),
            self.row("job-0003", "rejected", "Applied", "2026-09-01", "2026-09-03"),
        ]
        self.save()

    def tearDown(self):
        self.temporary.cleanup()

    @staticmethod
    def row(job_id, status, stage, applied="", response=""):
        return {"id": job_id, "application_status": status, "stage_reached": stage,
                "applied_at": applied, "response_at": response}

    def save(self):
        with (self.root / "data/jobs.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.rows[0]))
            writer.writeheader()
            writer.writerows(self.rows)

    def test_dry_run_is_read_only_apply_is_idempotent_and_projection_exact(self):
        before = (self.root / "data/jobs.csv").read_bytes()
        summary, pending, revision = migration.plan(self.root, "2026-09-24T12:00:00Z")
        self.assertEqual(summary["pending_events"], 3)
        self.assertEqual(summary["untouched_jobs"], 1)
        self.assertEqual(summary["event_counts"], {
            "application_submitted": 2, "response_received": 0, "rejection_received": 1,
        })
        self.assertEqual(list(self.root.rglob("*")), [self.root / "data", self.root / "data/jobs.csv"])
        self.assertEqual(migration.apply(self.root, summary, pending, revision), "applied")
        self.assertEqual((self.root / "data/jobs.csv").read_bytes(), before)
        ledger = self.root / "data/application_events"
        files_before = {path.name: path.read_bytes() for path in ledger.iterdir()}
        report = event_ledger.mismatch_report(ledger, {row["id"]: row for row in self.rows})
        self.assertTrue(all(not item["mismatches"] for item in report.values()))
        second, pending, revision = migration.plan(self.root, "2026-09-25T12:00:00Z")
        self.assertEqual((second["pending_jobs"], second["existing_jobs"]), (0, 2))
        self.assertEqual(migration.apply(self.root, second, pending, revision), "already_complete")
        self.assertEqual(files_before, {path.name: path.read_bytes() for path in ledger.iterdir()})

    def test_cli_defaults_to_dry_run_without_creating_files(self):
        script = Path(migration.__file__)
        before = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        result = subprocess.run(
            [sys.executable, str(script), "--root", str(self.root), "--format", "json"],
            capture_output=True, text=True, check=True,
        )
        report = json.loads(result.stdout)
        self.assertTrue(report["dry_run"])
        self.assertEqual(report["pending_events"], 3)
        after = {path.relative_to(self.root): path.read_bytes() for path in self.root.rglob("*") if path.is_file()}
        self.assertEqual(after, before)
        self.assertFalse((self.root / "data/application_events").exists())

    def test_unproven_stage_blocks_entire_apply(self):
        self.rows.append(self.row("job-0004", "interviewing", "Recruiter screen", "2026-09-01", "2026-09-04"))
        self.save()
        summary, pending, revision = migration.plan(self.root, "2026-09-24T12:00:00Z")
        self.assertEqual(summary["blocked"], [{"job_id": "job-0004", "reason": "unproven_stage_chronology"}])
        with self.assertRaisesRegex(ValueError, "blocked lifecycle"):
            migration.apply(self.root, summary, pending, revision)
        self.assertFalse((self.root / "data/application_events").exists())

    def test_failed_publish_rolls_back_all_event_files(self):
        summary, pending, revision = migration.plan(self.root, "2026-09-24T12:00:00Z")
        real_publish = tracker_transaction.publish

        def fail_validation(root, writes, expected, *, validate):
            def reject(replacement_root):
                validate(replacement_root)
                raise ValueError("injected validation failure")
            return real_publish(root, writes, expected, validate=reject)

        with patch.object(migration, "publish", side_effect=fail_validation):
            with self.assertRaisesRegex(ValueError, "injected validation failure"):
                migration.apply(self.root, summary, pending, revision)
        self.assertFalse((self.root / "data/application_events").exists())

    def test_cutover_marker_and_events_commit_together_and_retry_is_noop(self):
        summary, pending, revision = migration.plan(self.root, "2026-09-24T12:00:00Z")
        self.assertFalse(tracker_paths.event_writes_enabled(self.root))
        self.assertEqual(migration.apply(self.root, summary, pending, revision, cutover=True), "applied")
        marker = self.root / migration.CUTOVER_MARKER
        self.assertEqual(marker.read_bytes(), migration.CUTOVER_BYTES)
        self.assertTrue(tracker_paths.event_writes_enabled(self.root))
        second, pending, revision = migration.plan(self.root, "2026-09-25T12:00:00Z")
        self.assertEqual(migration.apply(self.root, second, pending, revision, cutover=True), "already_complete")

    def test_failed_cutover_restores_marker_and_events(self):
        summary, pending, revision = migration.plan(self.root, "2026-09-24T12:00:00Z")
        real_publish = tracker_transaction.publish

        def fail_validation(root, writes, expected, *, validate):
            def reject(replacement_root):
                validate(replacement_root)
                raise ValueError("injected cutover failure")
            return real_publish(root, writes, expected, validate=reject)

        with patch.object(migration, "publish", side_effect=fail_validation):
            with self.assertRaisesRegex(ValueError, "injected cutover failure"):
                migration.apply(self.root, summary, pending, revision, cutover=True)
        self.assertFalse((self.root / migration.CUTOVER_MARKER).exists())
        self.assertFalse((self.root / "data/application_events").exists())
        self.assertFalse(tracker_paths.event_writes_enabled(self.root))

    def test_lifecycle_table_does_not_invent_missing_transitions(self):
        cases = [
            ("apply", "None", "", "", 0, None),
            ("applied", "Applied", "2026-09-01", "2026-09-03", 2, None),
            ("rejected", "Applied", "2026-09-01", "", 0, "missing_response_at"),
            ("ghosted", "Applied", "2026-09-01", "", 0, "undated_or_unrepresentable_transition"),
            ("withdrawn", "Applied", "2026-09-01", "", 0, "undated_or_unrepresentable_transition"),
            ("offer", "Offer", "2026-09-01", "2026-09-03", 0, "unproven_stage_chronology"),
            ("rejected", "Tech interview", "2026-09-01", "2026-09-03", 0, "unproven_stage_chronology"),
            ("applied", "Applied", "2026-09-03", "2026-09-01", 0, "invalid_lifecycle_dates"),
        ]
        for status, stage, applied, response, count, reason in cases:
            with self.subTest(status=status, stage=stage, applied=applied, response=response):
                events, actual = migration.candidate_events(
                    self.row("job-0007", status, stage, applied, response), "2026-09-24T12:00:00Z"
                )
                self.assertEqual(actual, reason)
                self.assertEqual(len(events or []), count)


if __name__ == "__main__":
    unittest.main()
