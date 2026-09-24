"""Integrated event/snapshot publication on a synthetic tracker checkout."""

import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import agent_operations, event_ledger, tracker_event_write, tracker_transaction, tracker_validate, tracker_write
from scripts.tracker_schema import FIELDS, JOB_SOURCE_FIELDS


PROJECT = Path(__file__).resolve().parents[1]


def event(kind, number, job_id="job-0001"):
    return {
        "schema_version": 1,
        "event_id": f"synthetic-{number}",
        "job_id": job_id,
        "event_type": kind,
        "occurred_at": "2026-09-24",
        "precision": "date",
        "recorded_at": f"2026-09-24T12:00:{number:02d}Z",
        "source": "manual",
        "actor": "user",
        "confirmed_by_user": True,
        "evidence_ref": None,
        "payload": {},
        "supersedes": None,
    }


class TrackerEventWriteTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in ("data", "applications", "docs"):
            (self.root / directory).mkdir()
        shutil.copy2(PROJECT / "applications/_TEMPLATE.md", self.root / "applications/_TEMPLATE.md")
        row = tracker_write.build_add_row([], {
            "company": "Synthetic Co", "role": "Frontend Developer", "source": "Manual",
            "application_status": "reviewing",
        })
        (self.root / "data/jobs.csv").write_bytes(tracker_write.csv_bytes(FIELDS, [row]))
        (self.root / "data/job_sources.csv").write_bytes(tracker_write.csv_bytes(JOB_SOURCE_FIELDS, []))
        self.old_jobs = (self.root / "data/jobs.csv").read_bytes()
        self.original_root = tracker_write.PATHS.root
        tracker_write.PATHS.root = self.root

    def tearDown(self):
        tracker_write.PATHS.root = self.original_root
        self.temporary.cleanup()

    @property
    def event_path(self):
        return self.root / "data/application_events/job-0001.jsonl"

    def test_append_updates_snapshot_and_identical_retry_is_noop(self):
        submitted = event("application_submitted", 1)
        result = tracker_event_write.append_application_event(submitted)
        self.assertEqual(result["outcome"], "recorded")
        self.assertEqual(result["job"]["application_status"], "applied")
        self.assertEqual(result["job"]["applied_at"], "2026-09-24")
        self.assertEqual(event_ledger.parse_file(self.event_path), [submitted])
        self.assertFalse(event_ledger.mismatch_report(
            self.event_path.parent, {"job-0001": result["job"]}
        )["job-0001"]["mismatches"])
        old_bytes = self.event_path.read_bytes()
        self.assertEqual(tracker_event_write.append_application_event(submitted)["outcome"], "already_recorded")
        self.assertEqual(self.event_path.read_bytes(), old_bytes)
        self.assertTrue((self.root / "docs/tracker.md").exists())

    def test_conflicting_retry_and_legacy_row_fail_closed(self):
        submitted = event("application_submitted", 1)
        tracker_event_write.append_application_event(submitted)
        changed = dict(submitted, evidence_ref="different")
        with self.assertRaisesRegex(event_ledger.EventValidationError, "different content"):
            tracker_event_write.append_application_event(changed)
        self.assertEqual(len(event_ledger.parse_file(self.event_path)), 1)

    def test_cross_job_event_id_collision_rolls_back(self):
        tracker_event_write.append_application_event(event("application_submitted", 1))
        rows, sources, revisions = tracker_write.load_for_write()
        second = tracker_write.build_add_row(rows, {
            "company": "Another Synthetic Co", "role": "Engineer", "source": "Manual",
            "application_status": "reviewing",
        })
        tracker_write.apply_dataset_transaction([*rows, second], sources, expected_revisions=revisions)
        before = (self.root / "data/jobs.csv").read_bytes()
        with self.assertRaisesRegex(event_ledger.EventValidationError, "cross-file event_id collision"):
            tracker_event_write.append_application_event(event("application_submitted", 1, job_id="job-0002"))
        self.assertEqual((self.root / "data/jobs.csv").read_bytes(), before)
        self.assertFalse((self.root / "data/application_events/job-0002.jsonl").exists())

    def test_legacy_snapshot_mutation_cannot_diverge_from_event_history(self):
        tracker_event_write.append_application_event(event("application_submitted", 1))
        rows, sources, revisions = tracker_write.load_for_write()
        before = (self.root / "data/jobs.csv").read_bytes()
        rows[0]["applied_at"] = "2026-09-23"
        with self.assertRaisesRegex(OSError, "projection disagrees"):
            tracker_write.apply_dataset_transaction(rows, sources, expected_revisions=revisions)
        self.assertEqual((self.root / "data/jobs.csv").read_bytes(), before)
        self.assertEqual(len(event_ledger.parse_file(self.event_path)), 1)

    def test_failure_after_event_replacement_restores_snapshot_and_event(self):
        with patch.dict(os.environ, {"JOBS_INGEST_FAIL_AFTER_REPLACE": "1"}):
            with self.assertRaisesRegex(OSError, "injected ingest replacement failure"):
                tracker_event_write.append_application_event(event("application_submitted", 1))
        self.assertEqual((self.root / "data/jobs.csv").read_bytes(), self.old_jobs)
        self.assertFalse(self.event_path.exists())
        self.assertEqual(tracker_transaction.recover(self.root), "clean")

    def test_killed_writer_recovers_event_and_snapshot_together(self):
        payload = json.dumps(event("application_submitted", 1))
        script = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "from scripts import tracker_event_write, tracker_write\n"
            "tracker_write.PATHS.root = Path(sys.argv[1])\n"
            "tracker_event_write.append_application_event(json.loads(sys.argv[2]))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.root), payload], cwd=PROJECT,
            env={**os.environ, "JOBS_INGEST_KILL_AFTER_REPLACE": "1"},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(event_ledger.read_report(
            self.event_path.parent, self.root / "data/jobs.csv"
        ), {})
        self.assertEqual(tracker_transaction.recover(self.root), "clean")
        self.assertEqual((self.root / "data/jobs.csv").read_bytes(), self.old_jobs)
        self.assertFalse(self.event_path.exists())
        self.assertEqual(tracker_event_write.append_application_event(event("application_submitted", 1))["outcome"], "recorded")

    def test_process_kill_at_every_integrated_replace_boundary(self):
        payload = json.dumps(event("application_submitted", 1))
        script = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "from scripts import tracker_event_write, tracker_write\n"
            "tracker_write.PATHS.root = Path(sys.argv[1])\n"
            "tracker_event_write.append_application_event(json.loads(sys.argv[2]))\n"
        )
        for count in range(9):  # prepare, then event + CSV pair + four views + card
            with self.subTest(count=count):
                result = subprocess.run(
                    [sys.executable, "-c", script, str(self.root), payload], cwd=PROJECT,
                    env={**os.environ, "JOBS_INGEST_KILL_AFTER_REPLACE": str(count)},
                    capture_output=True, text=True,
                )
                self.assertEqual(result.returncode, 75, result.stderr)
                self.assertEqual(tracker_transaction.recover(self.root), "rolled_back")
                self.assertEqual((self.root / "data/jobs.csv").read_bytes(), self.old_jobs)
                self.assertFalse(self.event_path.exists())
                self.assertFalse((self.root / "docs/tracker.md").exists())
                self.assertFalse(list((self.root / "applications").glob("job-*.md")))

    def test_process_kill_after_commit_keeps_event_and_snapshot(self):
        submitted = event("application_submitted", 1)
        script = (
            "import json, sys\n"
            "from pathlib import Path\n"
            "from scripts import tracker_event_write, tracker_write\n"
            "tracker_write.PATHS.root = Path(sys.argv[1])\n"
            "tracker_event_write.append_application_event(json.loads(sys.argv[2]))\n"
        )
        result = subprocess.run(
            [sys.executable, "-c", script, str(self.root), json.dumps(submitted)], cwd=PROJECT,
            env={**os.environ, "JOBS_INGEST_KILL_AFTER_COMMIT": "1"},
            capture_output=True, text=True,
        )
        self.assertEqual(result.returncode, 75, result.stderr)
        self.assertEqual(tracker_transaction.recover(self.root), "kept_commit")
        self.assertEqual(event_ledger.parse_file(self.event_path), [submitted])
        self.assertEqual(tracker_event_write.append_application_event(submitted)["outcome"], "already_recorded")

    def test_stale_snapshot_prevents_event_append(self):
        original_apply = tracker_event_write.apply_dataset_transaction

        def change_snapshot_first(*args, **kwargs):
            rows, sources, revisions = tracker_write.load_for_write()
            rows[0]["notes"] = "concurrent edit"
            original_apply(rows, sources, expected_revisions=revisions)
            return original_apply(*args, **kwargs)

        with patch.object(tracker_event_write, "apply_dataset_transaction", side_effect=change_snapshot_first):
            with self.assertRaises(tracker_write.ValidationError) as caught:
                tracker_event_write.append_application_event(event("application_submitted", 1))
        self.assertEqual(caught.exception.code, "stale_operation")
        self.assertFalse(self.event_path.exists())
        self.assertEqual(tracker_write.load()[0]["notes"], "concurrent edit")

    def test_direct_maintenance_saves_fail_after_ledger_creation(self):
        self.event_path.parent.mkdir()
        with self.assertRaisesRegex(RuntimeError, "disabled after event-ledger cutover"):
            tracker_validate.save([])
        with self.assertRaisesRegex(RuntimeError, "disabled after event-ledger cutover"):
            tracker_validate.save_job_sources([])
        self.assertEqual((self.root / "data/jobs.csv").read_bytes(), self.old_jobs)

    def stage_connector_event(self):
        result_name = "data/operations/results/op-synthetic-event.json"
        with agent_operations.temporary_tracker_workspace(include_snapshot=True) as (temp_root, baseline):
            tracker_event_write.append_application_event(event("application_submitted", 1))
            result_path = temp_root / result_name
            result_path.parent.mkdir(parents=True)
            result_path.write_text(
                '{"version":1,"operation_id":"op-synthetic-event","status":"completed"}\n',
                encoding="utf-8",
            )
            writes, expected = agent_operations.staged_changes(
                temp_root, baseline, result_name, include_canonical=True,
            )
        self.assertIn("data/application_events/job-0001.jsonl", writes)
        self.assertIn(result_name, writes)
        return writes, expected, result_name

    def test_connector_stages_event_and_result_in_one_publication(self):
        writes, expected, result_name = self.stage_connector_event()
        self.assertFalse(self.event_path.exists())
        agent_operations.publish_staged_operation(self.root, writes, expected)
        self.assertEqual(event_ledger.parse_file(self.event_path), [event("application_submitted", 1)])
        self.assertTrue((self.root / result_name).exists())
        self.assertEqual(tracker_write.load()[0]["application_status"], "applied")

    def test_connector_crash_rolls_back_event_snapshot_and_result(self):
        writes, expected, result_name = self.stage_connector_event()
        payload = json.dumps({
            "writes": {name: base64.b64encode(body).decode("ascii") for name, body in writes.items()},
            "expected": expected,
        })
        script = (
            "import base64, json, sys\n"
            "from pathlib import Path\n"
            "from scripts import agent_operations as ops, tracker_write\n"
            "root = Path(sys.argv[1])\n"
            "tracker_write.PATHS.root = root\n"
            "payload = json.load(sys.stdin)\n"
            "writes = {name: base64.b64decode(body) for name, body in payload['writes'].items()}\n"
            "ops.publish_staged_operation(root, writes, payload['expected'])\n"
        )
        names = sorted(writes)
        for name in ("data/application_events/job-0001.jsonl", result_name):
            with self.subTest(name=name):
                result = subprocess.run(
                    [sys.executable, "-c", script, str(self.root)], cwd=PROJECT,
                    input=payload, capture_output=True, text=True,
                    env={**os.environ, "JOBS_CONNECTOR_KILL_AFTER_REPLACE": str(names.index(name) + 1)},
                )
                self.assertEqual(result.returncode, 75, result.stderr)
                self.assertEqual(tracker_transaction.recover(self.root), "rolled_back")
                self.assertEqual((self.root / "data/jobs.csv").read_bytes(), self.old_jobs)
                self.assertFalse(self.event_path.exists())
                self.assertFalse((self.root / result_name).exists())
        agent_operations.publish_staged_operation(self.root, writes, expected)
        self.assertTrue(self.event_path.exists())
        self.assertTrue((self.root / result_name).exists())
