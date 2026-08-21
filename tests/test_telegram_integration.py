import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scripts import jobs, telegram_leads
from scripts.inbox import validate_batch
from scripts.source_config import CONFIG_PATH, load_source_config


class TelegramRepositoryIntegrationTests(unittest.TestCase):
    def telegram_record(self):
        lead = telegram_leads.build_lead(
            peer_id=-1001234567890,
            message_id=42,
            channel_title="Example jobs",
            channel_username="example",
            posted_at="2026-08-19T10:00:00Z",
            found_at="2026-08-20",
            permalink="https://t.me/example/42",
            text="Private raw post text https://careers.example.test/jobs/frontend",
            matched_terms=["frontend"],
        )
        return telegram_leads.project_confirmed_lead(
            lead,
            company="Example Co",
            role="Frontend Developer",
            application_url="https://careers.example.test/jobs/frontend",
            raw_location="Serbia or remote",
        )

    def write_batch(self, record):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "telegram.jsonl"
        records = record if isinstance(record, list) else [record]
        path.write_text(
            "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in records),
            encoding="utf-8",
        )
        return path

    def test_new_and_legacy_telegram_sources_remain_supported(self):
        sources = load_source_config(CONFIG_PATH)

        self.assertIn("Telegram", sources)
        self.assertIn("Telegram", jobs.SOURCES)
        self.assertIn("Find My Remote / Telegram", jobs.SOURCES)
        self.assertTrue(sources["Telegram"]["aggregator"])
        self.assertEqual(
            sources["Telegram"]["verification"],
            {"first_party_required": True, "apply_required": True},
        )

    def test_confirmed_projection_validates_and_plans_unverified_ingest(self):
        record = self.telegram_record()
        self.assertNotIn("text", record)
        self.assertNotIn("text", record["payload"]["telegram"])
        self.assertNotIn("Private raw post text", json.dumps(record, ensure_ascii=False))
        path = self.write_batch(record)

        validation = validate_batch(path)
        self.assertTrue(validation["ok"], validation["errors"])

        with patch.object(jobs, "load", return_value=[]), patch.object(
            jobs, "load_job_sources", return_value=[]
        ):
            plan = jobs.plan_ingest(path)

        self.assertFalse(plan.invalid, plan.errors)
        self.assertEqual(plan.summary["pending"], 1)
        self.assertEqual(plan.jobs_created, 1)
        self.assertEqual(plan.rows[0]["source"], "Telegram")
        self.assertEqual(plan.rows[0]["application_status"], "not_started")
        self.assertEqual(plan.rows[0]["first_party_verified"], "unknown")
        self.assertEqual(plan.rows[0]["apply_verified"], "unknown")
        self.assertEqual(plan.rows[0]["next_action"], "verify first-party")
        self.assertEqual(plan.rows[0]["original_url"], "")

    def test_one_telegram_post_can_create_distinct_vacancies_with_distinct_source_ids(self):
        lead = telegram_leads.build_lead(
            peer_id=-1001234567890,
            message_id=43,
            channel_title="Example jobs",
            channel_username="example",
            posted_at="2026-08-19T10:00:00Z",
            found_at="2026-08-20",
            permalink="https://t.me/example/43",
            text=(
                "Frontend https://careers.example.test/jobs/frontend "
                "and mobile frontend https://careers.example.test/jobs/mobile"
            ),
            matched_terms=["frontend"],
        )
        records = [
            telegram_leads.project_confirmed_lead(
                lead,
                company="Example Co",
                role="Frontend Developer",
                application_url="https://careers.example.test/jobs/frontend",
                raw_location="Serbia or remote",
            ),
            telegram_leads.project_confirmed_lead(
                lead,
                company="Example Co",
                role="Mobile Frontend Developer",
                application_url="https://careers.example.test/jobs/mobile",
                raw_location="Serbia or remote",
            ),
        ]
        self.assertEqual(records[0]["source_url"], records[1]["source_url"])
        self.assertNotEqual(records[0]["source_job_id"], records[1]["source_job_id"])
        path = self.write_batch(records)

        validation = validate_batch(path)
        self.assertTrue(validation["ok"], validation["errors"])
        with patch.object(jobs, "load", return_value=[]), patch.object(
            jobs, "load_job_sources", return_value=[]
        ):
            plan = jobs.plan_ingest(path)

        self.assertFalse(plan.invalid, plan.errors)
        self.assertEqual(plan.summary["pending"], 2)
        self.assertEqual(plan.jobs_created, 2)
        self.assertEqual(plan.source_references_created, 2)
        self.assertEqual(
            [item["outcome"] for item in plan.outcomes],
            ["pending", "pending"],
        )

    def test_shared_url_exception_does_not_weaken_other_source_conflicts(self):
        existing = {
            "job_id": "job-0001",
            "source": "LinkedIn",
            "source_url": "https://www.linkedin.com/jobs/view/collection",
            "source_job_id": "linkedin-1",
            "found_at": "2026-08-20",
        }
        candidate = {
            **existing,
            "job_id": "job-0002",
            "source_job_id": "linkedin-2",
        }

        with self.assertRaises(jobs.SourceReferenceConflict):
            jobs.prepare_source_reference([existing], candidate)


if __name__ == "__main__":
    unittest.main()
