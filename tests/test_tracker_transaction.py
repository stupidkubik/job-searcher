"""Fault and process-crash tests for the isolated v3 fileset prototype."""

import stat
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import tracker_transaction as txn


ROOT = Path(__file__).resolve().parents[1]
WRITES = {
    "data/application_events/job-0001.jsonl": b'{"event_id":"event-1"}\n',
    "data/index/active.csv": b"id,status\njob-0001,applied\n",
    "data/jobs.csv": b"id,status\njob-0001,applied\n",
    "data/operations/results/op-1.json": b'{"status":"completed"}\n',
    "docs/tracker.md": b"# Applied\n",
}
OLD_JOBS = b"id,status\njob-0001,not_started\n"
OLD_INDEX = b"id,status\njob-0001,not_started\n"
OLD_TRACKER = b"# Not started\n"
OLD_FILES = {
    "data/jobs.csv": OLD_JOBS,
    "data/index/active.csv": OLD_INDEX,
    "docs/tracker.md": OLD_TRACKER,
}


def setup_root(root):
    for directory in ("data/application_events", "data/index", "data/operations/results", "docs"):
        (root / directory).mkdir(parents=True)
    for name, content in OLD_FILES.items():
        (root / name).write_bytes(content)


def expected_old():
    return {name: txn.digest(OLD_FILES.get(name)) for name in WRITES}


CHILD = """
import os, sys
from scripts import tracker_transaction as txn
root, stage, wanted = sys.argv[1], sys.argv[2], sys.argv[3]
writes = {
    'data/application_events/job-0001.jsonl': b'{"event_id":"event-1"}\\n',
    'data/index/active.csv': b'id,status\\njob-0001,applied\\n',
    'data/jobs.csv': b'id,status\\njob-0001,applied\\n',
    'data/operations/results/op-1.json': b'{"status":"completed"}\\n',
    'docs/tracker.md': b'# Applied\\n',
}
old = {
    'data/index/active.csv': b'id,status\\njob-0001,not_started\\n',
    'data/jobs.csv': b'id,status\\njob-0001,not_started\\n',
    'docs/tracker.md': b'# Not started\\n',
}
expected = {name: txn.digest(old.get(name)) for name in writes}
def fault(at, index):
    if at == stage and str(index) == wanted:
        os._exit(75)
txn.publish(root, writes, expected, fault=fault)
"""

RACE_CHILD = """
import sys, time
from scripts import tracker_transaction as txn
root, token = sys.argv[1], sys.argv[2]
old = b'id,status\\njob-0001,not_started\\n'
try:
    txn.publish(root, {'data/jobs.csv': ('id,status\\njob-0001,' + token + '\\n').encode()},
                {'data/jobs.csv': txn.digest(old)},
                validate=lambda _root: time.sleep(0.1))
except txn.StaleRevision:
    sys.exit(3)
"""


class TrackerTransactionTests(unittest.TestCase):
    def assert_original(self, root):
        for name, content in OLD_FILES.items():
            self.assertEqual((root / name).read_bytes(), content)
        self.assertFalse((root / "data/application_events/job-0001.jsonl").exists())
        self.assertFalse((root / "data/operations/results/op-1.json").exists())

    def assert_new(self, root):
        for name, content in WRITES.items():
            self.assertEqual((root / name).read_bytes(), content)

    def child(self, root, stage, index):
        return subprocess.run(
            [sys.executable, "-c", CHILD, str(root), stage, str(index)],
            cwd=ROOT, capture_output=True, text=True, check=False,
        )

    def test_normal_publish_and_stale_retry(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup_root(root)
            txn.publish(root, WRITES, expected_old())
            self.assert_new(root)
            self.assertEqual(txn.recover(root), "clean")
            with self.assertRaises(txn.StaleRevision):
                txn.publish(root, WRITES, expected_old())
            self.assert_new(root)

    def test_validation_failure_rolls_back_every_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup_root(root)
            def reject(_root):
                raise ValueError("projection mismatch")
            with self.assertRaisesRegex(ValueError, "projection mismatch"):
                txn.publish(root, WRITES, expected_old(), validate=reject)
            self.assert_original(root)
            self.assertEqual(txn.recover(root), "clean")

    def test_exception_at_every_boundary_rolls_back(self):
        for stage, index in [("after_prepare", None), *[("after_replace", i) for i in range(len(WRITES))]]:
            with self.subTest(stage=stage, index=index), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                setup_root(root)
                def fault(at, position):
                    if (at, position) == (stage, index):
                        raise OSError("injected failure")
                with self.assertRaisesRegex(OSError, "injected failure"):
                    txn.publish(root, WRITES, expected_old(), fault=fault)
                self.assert_original(root)
                self.assertEqual(txn.recover(root), "clean")

    def test_process_crash_at_every_boundary_recovers_original(self):
        for stage, index in [("after_prepare", None), *[("after_replace", i) for i in range(len(WRITES))]]:
            with self.subTest(stage=stage, index=index), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                setup_root(root)
                result = self.child(root, stage, index)
                self.assertEqual(result.returncode, 75, result.stderr)
                self.assertEqual(txn.recover(root), "rolled_back")
                self.assert_original(root)
                self.assertEqual(txn.recover(root), "clean")

    def test_crash_after_durable_commit_keeps_all_new_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup_root(root)
            result = self.child(root, "after_commit", None)
            self.assertEqual(result.returncode, 75, result.stderr)
            self.assertEqual(txn.recover(root), "kept_commit")
            self.assert_new(root)
            self.assertEqual(txn.recover(root), "clean")

    def test_reader_recovers_before_observing_file_set(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup_root(root)
            result = self.child(root, "after_replace", 1)
            self.assertEqual(result.returncode, 75, result.stderr)
            observed = txn.read_consistent(root, WRITES)
            self.assertEqual(observed["data/jobs.csv"], OLD_JOBS)
            self.assertIsNone(observed["data/application_events/job-0001.jsonl"])
            self.assertIsNone(observed["data/operations/results/op-1.json"])

    def test_concurrent_publishers_do_not_overwrite_a_stale_revision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup_root(root)
            processes = [
                subprocess.Popen(
                    [sys.executable, "-c", RACE_CHILD, str(root), token],
                    cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                )
                for token in ("A", "B")
            ]
            results = [process.communicate(timeout=10) for process in processes]
            self.assertEqual(sorted(process.returncode for process in processes), [0, 3], results)
            final = (root / "data/jobs.csv").read_bytes()
            self.assertIn(final, {b"id,status\njob-0001,A\n", b"id,status\njob-0001,B\n"})

    def test_corrupt_backup_fails_closed(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup_root(root)
            result = self.child(root, "after_replace", 1)
            self.assertEqual(result.returncode, 75, result.stderr)
            (root / txn.JOURNAL_NAME / "1.old").write_bytes(b"corrupted")
            with self.assertRaises(txn.RecoveryError):
                txn.recover(root)
            self.assertTrue((root / txn.JOURNAL_NAME).exists())

    def test_pending_journal_is_owner_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup_root(root)
            result = self.child(root, "after_prepare", None)
            self.assertEqual(result.returncode, 75, result.stderr)
            journal = root / txn.JOURNAL_NAME
            self.assertEqual(stat.S_IMODE(journal.stat().st_mode), 0o700)
            for path in journal.iterdir():
                self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(txn.recover(root), "rolled_back")

    def test_cleanup_failure_cannot_reopen_a_committed_transaction(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup_root(root)
            with patch.object(txn.shutil, "rmtree", side_effect=OSError("cleanup failed")):
                txn.publish(root, WRITES, expected_old())
            self.assert_new(root)
            self.assertFalse((root / txn.JOURNAL_NAME).exists())
            self.assertEqual(len(list(root.glob(".v3-finished-*"))), 1)
            self.assertEqual(txn.recover(root), "clean")
            self.assertFalse(list(root.glob(".v3-finished-*")))

    def test_rejects_path_escape_and_symlink_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            setup_root(root)
            with self.assertRaises(txn.TransactionError):
                txn.publish(root, {"../escape": b"x"}, {"../escape": None})
            outside = root.parent / f"outside-{root.name}"
            (root / "data/link").symlink_to(outside)
            with self.assertRaises(txn.TransactionError):
                txn.publish(root, {"data/link": b"x"}, {"data/link": None})


if __name__ == "__main__":
    unittest.main()
