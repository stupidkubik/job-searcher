"""Synthetic lifecycle fixtures for the read-only v3 event contract."""

import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from scripts import event_ledger as ledger


ROOT = Path(__file__).resolve().parents[1]
JOB_ID = "job-9001"
DAY = "2026-09-23"
NEXT_DAY = "2026-09-24"


def event(kind, number, *, occurred_at=DAY, precision="date", source="manual", **extra):
    payload = extra.pop("payload", {})
    row = {
        "schema_version": 1,
        "event_id": f"event-{number:03d}",
        "job_id": JOB_ID,
        "event_type": kind,
        "occurred_at": occurred_at,
        "precision": precision,
        "recorded_at": f"2026-09-25T12:00:{number:02d}Z",
        "source": source,
        "actor": "migration" if source == "migration" else "user",
        "confirmed_by_user": source != "migration",
        "evidence_ref": None,
        "payload": payload,
        "supersedes": None,
    }
    row.update(extra)
    return row


def snapshot(status, stage="Applied", applied=DAY, response=""):
    return {
        "application_status": status,
        "stage_reached": stage,
        "applied_at": applied,
        "response_at": response,
    }


class EventLedgerTests(unittest.TestCase):
    def assert_invalid(self, rows, code):
        with self.assertRaises(ledger.EventValidationError) as caught:
            ledger.project_events(rows, job_id=JOB_ID, job_ids={JOB_ID})
        self.assertEqual(caught.exception.code, code)

    def test_ten_required_scenarios(self):
        submitted = event("application_submitted", 1)
        scenarios = {
            "submit_no_response": (
                [submitted], snapshot("applied")
            ),
            "ack_screen_rejection": (
                [submitted, event("acknowledgement_received", 2),
                 event("interview_scheduled", 3, occurred_at=NEXT_DAY,
                       payload={"round_id": "screen-1", "round_kind": "recruiter"}),
                 event("rejection_received", 4, occurred_at=NEXT_DAY)],
                snapshot("rejected", "Recruiter screen", response=NEXT_DAY),
            ),
            "assessment_technical_offer": (
                [submitted,
                 event("assessment_invited", 2, occurred_at=NEXT_DAY,
                       payload={"assessment_id": "test-1"}),
                 event("assessment_completed", 3, occurred_at=NEXT_DAY,
                       payload={"assessment_id": "test-1"}),
                 event("interview_scheduled", 4, occurred_at=NEXT_DAY,
                       payload={"round_id": "tech-1", "round_kind": "technical"}),
                 event("offer_received", 5, occurred_at=NEXT_DAY)],
                snapshot("offer", "Offer", response=NEXT_DAY),
            ),
            "interview_rescheduled_completed": (
                [submitted,
                 event("interview_scheduled", 2, occurred_at=NEXT_DAY,
                       payload={"round_id": "screen-1", "round_kind": "recruiter"}),
                 event("interview_cancelled", 3, occurred_at=NEXT_DAY,
                       payload={"round_id": "screen-1", "round_kind": "recruiter"}),
                 event("interview_scheduled", 4, occurred_at=NEXT_DAY,
                       payload={"round_id": "screen-1", "round_kind": "recruiter"}),
                 event("interview_completed", 5, occurred_at=NEXT_DAY,
                       payload={"round_id": "screen-1", "round_kind": "recruiter"})],
                snapshot("interviewing", "Recruiter screen", response=NEXT_DAY),
            ),
            "withdrawal_before_response": (
                [submitted, event("candidate_withdrew", 2, occurred_at=NEXT_DAY)],
                snapshot("withdrawn"),
            ),
            "wrong_interview_voided_after_rejection": (
                [submitted,
                 event("interview_scheduled", 2, occurred_at=NEXT_DAY,
                       payload={"round_id": "wrong-1", "round_kind": "final"}),
                 event("rejection_received", 3, occurred_at=NEXT_DAY),
                 event("event_voided", 4, occurred_at=None, precision="unknown",
                       supersedes="event-002")],
                snapshot("rejected", response=NEXT_DAY),
            ),
            "listing_closes_after_submit": (
                [submitted], snapshot("applied")
            ),
            "duplicate_source_urls_one_job": (
                [submitted, event("follow_up_sent", 2, occurred_at=NEXT_DAY)],
                snapshot("applied"),
            ),
            "legacy_date_only": (
                [event("application_submitted", 1, source="migration")],
                snapshot("applied"),
            ),
            "hypothetical_mail_no_event": (
                [submitted], snapshot("applied")
            ),
        }
        self.assertEqual(len(scenarios), 10)
        for name, (rows, expected) in scenarios.items():
            with self.subTest(name=name):
                self.assertEqual(ledger.project_events(rows, job_id=JOB_ID), expected)
        self.assert_invalid(
            [submitted, event("interview_scheduled", 2, confirmed_by_user=False,
                              payload={"round_id": "fake-1", "round_kind": "technical"})],
            "bad_confirmation",
        )

    def test_date_precision_and_belgrade_boundary(self):
        rows = [event("application_submitted", 1,
                      occurred_at="2026-09-22T23:30:00Z", precision="instant")]
        self.assertEqual(ledger.project_events(rows)["applied_at"], DAY)
        rows[0]["occurred_at"] = "2026-09-23T01:30:00+02:00"
        self.assertEqual(ledger.project_events(rows)["applied_at"], DAY)
        rows[0]["occurred_at"] = "2026-09-23T01:30:00"
        self.assert_invalid(rows, "bad_precision")

    def test_correction_replaces_type_in_original_slot(self):
        rows = [event("application_submitted", 1),
                event("rejection_received", 2, occurred_at=NEXT_DAY),
                event("response_received", 3, occurred_at=NEXT_DAY,
                      supersedes="event-002")]
        self.assertEqual(ledger.project_events(rows), snapshot("applied", response=NEXT_DAY))
        self.assertEqual([item["event_id"] for item in ledger.effective_events(rows)],
                         ["event-001", "event-003"])

    def test_rejects_contract_and_correction_errors(self):
        submitted = event("application_submitted", 1)
        bad = dict(submitted, unexpected=1)
        self.assert_invalid([bad], "bad_fields")
        self.assert_invalid([dict(submitted, event_type="magic")], "bad_type")
        self.assert_invalid([dict(submitted, job_id="job-9999")], "missing_job")
        self.assert_invalid([submitted, dict(submitted)], "duplicate_event")
        self.assert_invalid([event("application_submitted", 2), submitted], "bad_order")
        self.assert_invalid([submitted, event("event_voided", 2, occurred_at=None,
                                              precision="unknown", supersedes="event-999")],
                            "bad_supersedes")
        self.assert_invalid([submitted, event("response_received", 2),
                             event("event_voided", 3, occurred_at=None,
                                   precision="unknown", supersedes="event-002"),
                             event("event_voided", 4, occurred_at=None,
                                   precision="unknown", supersedes="event-002")],
                            "forked_correction")
        self.assert_invalid([submitted, event("interview_scheduled", 2, payload={})],
                            "bad_payload")
        self.assert_invalid([submitted, event("interview_cancelled", 2,
                                             payload={"round_id": "missing-1", "round_kind": "recruiter"})],
                            "bad_transition")
        self.assert_invalid([submitted, event("rejection_received", 2),
                             event("offer_received", 3)], "bad_transition")
        self.assert_invalid([submitted, event("offer_received", 2),
                             event("interview_scheduled", 3,
                                   payload={"round_id": "late-1", "round_kind": "technical"})],
                            "bad_transition")
        with self.assertRaises(ledger.EventValidationError) as caught:
            ledger.project_events([submitted, event("response_received", 2,
                                                   job_id="job-9002")],
                                  job_ids={JOB_ID, "job-9002"})
        self.assertEqual(caught.exception.code, "job_mismatch")

    def test_equal_recorded_at_uses_event_id_as_tie_breaker(self):
        first = event("application_submitted", 1)
        second = event("follow_up_sent", 2, recorded_at=first["recorded_at"])
        self.assertEqual(ledger.project_events([first, second])["application_status"], "applied")
        self.assert_invalid([second, first], "bad_order")

    def test_parse_and_mismatch_report_are_read_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_dir = root / "events"
            event_dir.mkdir()
            path = event_dir / f"{JOB_ID}.jsonl"
            path.write_text(json.dumps(event("application_submitted", 1)) + "\n", encoding="utf-8")
            before = path.read_bytes()
            report = ledger.mismatch_report(event_dir, {JOB_ID: snapshot("reviewing")})
            self.assertEqual(report[JOB_ID]["mismatches"][0]["field"], "application_status")
            self.assertEqual(path.read_bytes(), before)
            self.assert_invalid([event("application_submitted", 1, precision="unknown",
                                       occurred_at=None)], "bad_precision")
            path.write_text(json.dumps(event("application_submitted", 1)), encoding="utf-8")
            with self.assertRaises(ledger.EventValidationError) as caught:
                ledger.parse_file(path)
            self.assertEqual(caught.exception.code, "bad_json")
            path.write_text('{"schema_version":1,"schema_version":1}\n', encoding="utf-8")
            with self.assertRaises(ledger.EventValidationError) as caught:
                ledger.parse_file(path)
            self.assertEqual(caught.exception.code, "bad_json")

    def test_cross_file_duplicate_event_id_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = event("application_submitted", 1)
            second = dict(first, job_id="job-9002")
            (root / f"{JOB_ID}.jsonl").write_text(json.dumps(first) + "\n", encoding="utf-8")
            (root / "job-9002.jsonl").write_text(json.dumps(second) + "\n", encoding="utf-8")
            with self.assertRaises(ledger.EventValidationError) as caught:
                ledger.mismatch_report(root, {
                    JOB_ID: snapshot("applied"), "job-9002": snapshot("applied")
                })
            self.assertEqual(caught.exception.code, "duplicate_event")

    def test_cli_reports_mismatch_without_mutation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            event_dir = root / "events"
            event_dir.mkdir()
            (event_dir / f"{JOB_ID}.jsonl").write_text(
                json.dumps(event("application_submitted", 1)) + "\n", encoding="utf-8"
            )
            csv_path = root / "jobs.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["id", *snapshot("applied")])
                writer.writeheader()
                writer.writerow({"id": JOB_ID, **snapshot("applied")})
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "event_ledger.py"),
                 str(event_dir), "--jobs-csv", str(csv_path)],
                capture_output=True, text=True, check=True,
            )
            self.assertTrue(json.loads(result.stdout)["ok"])
            with csv_path.open("w", newline="", encoding="utf-8") as stream:
                writer = csv.DictWriter(stream, fieldnames=["id", *snapshot("reviewing")])
                writer.writeheader()
                writer.writerow({"id": JOB_ID, **snapshot("reviewing")})
            mismatch = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "event_ledger.py"),
                 str(event_dir), "--jobs-csv", str(csv_path)],
                capture_output=True, text=True, check=False,
            )
            self.assertEqual(mismatch.returncode, 1)
            self.assertFalse(json.loads(mismatch.stdout)["ok"])


if __name__ == "__main__":
    unittest.main()
