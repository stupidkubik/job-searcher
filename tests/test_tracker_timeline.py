"""Read-only, targeted application timeline presentation."""

import argparse
import contextlib
import csv
import io
import json
import tempfile
import unittest
from pathlib import Path

from scripts import event_ledger, tracker_cli, tracker_timeline


JOB_ID = "job-9001"


def event(kind, number, *, occurred="2026-09-01", supersedes=None, evidence=None):
    return {
        "schema_version": 1, "event_id": f"timeline-{number}", "job_id": JOB_ID,
        "event_type": kind, "occurred_at": occurred,
        "precision": "unknown" if occurred is None else "date",
        "recorded_at": f"2026-09-24T12:00:{number:02d}Z",
        "source": "manual", "actor": "user", "confirmed_by_user": True,
        "evidence_ref": evidence, "payload": {}, "supersedes": supersedes,
    }


class TrackerTimelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        (self.root / "data").mkdir()
        self.row = {
            "id": JOB_ID, "company": "Synthetic Co", "role": "Frontend Developer",
            "application_status": "applied", "stage_reached": "Applied",
            "applied_at": "2026-09-01", "response_at": "",
            "next_action": "follow-up", "next_action_date": "2026-10-01",
        }
        self.save_row()

    def tearDown(self):
        self.temporary.cleanup()

    def save_row(self):
        with (self.root / "data/jobs.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=list(self.row))
            writer.writeheader()
            writer.writerow(self.row)

    def save_events(self, events):
        ledger = self.root / "data/application_events"
        ledger.mkdir(exist_ok=True)
        path = ledger / f"{JOB_ID}.jsonl"
        path.write_text("".join(json.dumps(item, sort_keys=True) + "\n" for item in events), encoding="utf-8")
        return path

    def test_legacy_snapshot_does_not_claim_event_history(self):
        before = (self.root / "data/jobs.csv").read_bytes()
        report = tracker_timeline.read_timeline(self.root, JOB_ID)
        self.assertEqual(report["history_state"], "legacy_snapshot_only")
        self.assertEqual(report["events"], [])
        self.assertEqual(report["next_commitment"], {"action": "follow-up", "date": "2026-10-01"})
        self.assertEqual((self.root / "data/jobs.csv").read_bytes(), before)
        self.assertFalse((self.root / "data/application_events").exists())

    def test_correction_and_evidence_are_visible_without_double_counting(self):
        submitted = event("application_submitted", 1)
        wrong = event("response_received", 2, occurred="2026-09-03", evidence="mail:message-1")
        void = event("event_voided", 3, occurred=None, supersedes=wrong["event_id"])
        path = self.save_events([submitted, wrong, void])
        before = path.read_bytes()
        report = tracker_timeline.read_timeline(self.root, JOB_ID)
        self.assertEqual([item["state"] for item in report["events"]], [
            "effective", "superseded", "void_marker",
        ])
        self.assertEqual(report["events"][1]["evidence_ref"], "mail:message-1")
        self.assertEqual(report["events"][1]["superseded_by"], void["event_id"])
        self.assertEqual(report["events"][2]["supersedes"], wrong["event_id"])
        self.assertEqual(report["events"][0]["precision"], "date")
        self.assertEqual(path.read_bytes(), before)

    def test_migrated_date_stays_date_only_and_unconfirmed(self):
        submitted = event("application_submitted", 1)
        submitted.update(source="migration", actor="migration", confirmed_by_user=False)
        self.save_events([submitted])
        report = tracker_timeline.read_timeline(self.root, JOB_ID)
        self.assertEqual(report["history_state"], "event_history")
        self.assertEqual(report["events"][0]["occurred_at"], "2026-09-01")
        self.assertEqual(report["events"][0]["precision"], "date")
        self.assertEqual(report["events"][0]["source"], "migration")
        self.assertFalse(report["events"][0]["confirmed_by_user"])

    def test_text_cli_shows_corrected_state_and_next_commitment(self):
        submitted = event("application_submitted", 1)
        wrong = event("response_received", 2, occurred="2026-09-03")
        corrected = event("rejection_received", 3, occurred="2026-09-04", supersedes=wrong["event_id"])
        self.row.update(application_status="rejected", response_at="2026-09-04",
                        next_action="", next_action_date="")
        self.save_row()
        self.save_events([submitted, wrong, corrected])
        original_root = tracker_cli.PATHS.root
        output = io.StringIO()
        try:
            tracker_cli.PATHS.root = self.root
            with contextlib.redirect_stdout(output):
                tracker_cli.cmd_timeline(argparse.Namespace(job_id=JOB_ID, format="text"))
        finally:
            tracker_cli.PATHS.root = original_root
        body = output.getvalue()
        self.assertIn("response_received  [superseded]", body)
        self.assertIn("rejection_received  [effective]", body)
        self.assertIn("2026-09-04 (date only)", body)
        self.assertIn("Next commitment: none", body)

    def test_snapshot_mismatch_and_unknown_job_fail_closed(self):
        self.save_events([event("application_submitted", 1), event("rejection_received", 2)])
        with self.assertRaises(event_ledger.EventValidationError) as caught:
            tracker_timeline.read_timeline(self.root, JOB_ID)
        self.assertEqual(caught.exception.code, "snapshot_mismatch")
        with self.assertRaises(event_ledger.EventValidationError) as caught:
            tracker_timeline.read_timeline(self.root, "job-9999")
        self.assertEqual(caught.exception.code, "missing_job")


if __name__ == "__main__":
    unittest.main()
