import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts.ci import audit_operation_results as audit


class OperationResultsAuditTests(unittest.TestCase):
    def run_evidence(self, status="queued", **extra):
        return {
            "id": 12,
            "event": "push",
            "head_branch": "main",
            "head_sha": "a" * 40,
            "status": status,
            **extra,
        }

    def test_each_active_state_and_active_rerun_excuses_only_its_request(self):
        for status in audit.ACTIVE:
            with self.subTest(status=status):
                runs = [
                    self.run_evidence("completed", conclusion="failure"),
                    self.run_evidence(status, id=13, run_attempt=2),
                ]
                self.assertEqual(audit.classify("operation-a", "a" * 40, runs)["state"], "pending")
                self.assertEqual(audit.classify("operation-b", "b" * 40, runs)["state"], "unknown")

    def test_terminal_success_failure_cancelled_without_result_are_lost(self):
        for conclusion in ("success", "failure", "cancelled", "skipped", "timed_out"):
            with self.subTest(conclusion=conclusion):
                self.assertEqual(
                    audit.classify(
                        "operation-a", "a" * 40, [self.run_evidence("completed", conclusion=conclusion)]
                    )["state"],
                    "lost",
                )

    def test_dispatch_matches_selected_request_even_on_unrelated_head_sha(self):
        run = self.run_evidence(
            event="workflow_dispatch",
            head_sha="b" * 40,
            display_title="operation data/operations/requests/operation-a.json",
        )
        self.assertEqual(audit.classify("operation-a", "a" * 40, [run])["state"], "pending")
        self.assertEqual(audit.classify("operation-b", "b" * 40, [run])["state"], "unknown")

    def test_old_active_dispatch_and_unknown_status_fail_closed(self):
        run = self.run_evidence(event="workflow_dispatch", display_title="agent operations")
        report = audit.classify("operation-a", "a" * 40, [self.run_evidence("completed"), run])
        self.assertEqual(report["state"], "unknown")
        self.assertEqual(
            audit.classify("operation-a", "a" * 40, [self.run_evidence("new_status")])["state"], "unknown"
        )

    def test_api_pagination_reads_all_pages_and_does_not_filter_historical_runs(self):
        api = audit.ActionsAPI("owner/repo", "fixture")
        with patch.object(
            api,
            "get",
            side_effect=[
                {"workflow_runs": [self.run_evidence()] * 100},
                {"workflow_runs": [self.run_evidence("completed")]},
            ],
        ) as get:
            self.assertEqual(len(api.runs()), 101)
            self.assertIn("page=2", get.call_args.args[0])

    def test_pending_then_settled_and_historical_orphan_in_temporary_repository(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            (root / audit.REQUESTS).mkdir(parents=True)
            (root / audit.RESULTS).mkdir(parents=True)
            audit.git(root, "init")
            audit.git(root, "config", "user.email", "test@example.invalid")
            audit.git(root, "config", "user.name", "fixture")
            request = root / audit.REQUESTS / "operation-a.json"
            request.write_text("{}")
            audit.git(root, "add", ".")
            audit.git(root, "commit", "-m", "request")
            sha = audit.git(root, "rev-parse", "HEAD")
            self.assertEqual(
                audit.inspect(root, [self.run_evidence(head_sha=sha)])["operation-a"]["state"], "pending"
            )
            self.assertEqual(audit.inspect(root, [])["operation-a"]["state"], "unknown")
            (root / audit.RESULTS / "operation-a.json").write_text(
                json.dumps({"operation_id": "operation-a"})
            )
            self.assertEqual(audit.inspect(root, []), {})

    def test_snapshot_registration_lag_is_bounded_and_not_claimed_lost(self):
        api = audit.ActionsAPI("owner/repo", "fixture")
        report = {"operation-a": {"state": "unknown", "reason": "no matching run"}}
        with (
            patch.object(audit, "git", return_value="a" * 40),
            patch.object(audit, "inspect", return_value=report),
            patch.object(api, "runs", return_value=[]),
            patch.object(api, "main_sha", return_value="a" * 40),
            patch.object(audit.time, "sleep") as sleep,
        ):
            result = audit.audit(Path("fixture"), api, sleep=sleep)
            self.assertFalse(result["ok"])
            self.assertEqual(sleep.call_count, 2)
            self.assertEqual(result["operations"]["operation-a"]["state"], "unknown")

    def test_terminal_evidence_is_rechecked_before_claiming_lost(self):
        api = audit.ActionsAPI("owner/repo", "fixture")
        with (
            patch.object(audit, "git", return_value="a" * 40),
            patch.object(
                audit,
                "inspect",
                side_effect=[
                    {"operation-a": {"state": "lost"}},
                    {"operation-a": {"state": "pending"}},
                ],
            ),
            patch.object(api, "runs", return_value=[]),
            patch.object(api, "main_sha", return_value="a" * 40),
            patch.object(audit.time, "sleep") as sleep,
        ):
            report = audit.audit(Path("fixture"), api, sleep=sleep)
            self.assertTrue(report["ok"])
            self.assertEqual(report["operations"]["operation-a"]["state"], "pending")
            sleep.assert_called_once_with(3)

    def test_main_changed_during_api_read_retries_and_api_errors_propagate(self):
        api = audit.ActionsAPI("owner/repo", "fixture")
        with (
            patch.object(audit, "git", return_value="a" * 40),
            patch.object(audit, "inspect", return_value={}),
            patch.object(api, "runs", return_value=[]),
            patch.object(api, "main_sha", side_effect=["b" * 40, "a" * 40]),
            patch.object(audit.time, "sleep") as sleep,
        ):
            self.assertTrue(audit.audit(Path("fixture"), api, sleep=sleep)["ok"])
            sleep.assert_called_once_with(3)
        with patch.object(audit, "git"), patch.object(api, "runs", side_effect=OSError("API unavailable")):
            with self.assertRaises(OSError):
                audit.audit(Path("fixture"), api)

    def test_queue_keeps_burst_capacity_and_audit_is_read_only(self):
        root = Path(__file__).resolve().parents[1]
        workflow = (root / ".github/workflows/agent-operations.yml").read_text()
        self.assertIn("queue: max", workflow)
        self.assertIn("cancel-in-progress: false", workflow)
        workflow = (root / ".github/workflows/operation-results-audit.yml").read_text()
        self.assertIn("contents: read", workflow)
        self.assertIn("actions: read", workflow)
        self.assertNotIn("contents: write", workflow)
        self.assertIn("ref: main", workflow)
        self.assertNotIn("download-artifact", workflow)


if __name__ == "__main__":
    unittest.main()
