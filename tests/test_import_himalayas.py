import copy
import io
import json
import subprocess
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

from scripts import import_himalayas


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "tests" / "fixtures" / "himalayas-api-response.json"


class FakeResponse:
    def __init__(self, payload):
        self.payload = payload

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return False

    def read(self):
        return json.dumps(self.payload).encode("utf-8")


class HimalayasAdapterUnitTests(unittest.TestCase):
    def setUp(self):
        self.payload = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_normalization_keeps_raw_api_record_and_uses_guid_for_stable_id(self):
        first = import_himalayas.normalize_job(self.payload["jobs"][0], date(2026, 8, 11))
        self.assertEqual(first["source"], "Himalayas")
        self.assertEqual(first["source_job_id"], self.payload["jobs"][0]["guid"])
        self.assertEqual(first["source_url"], self.payload["jobs"][0]["guid"])
        self.assertEqual(first["application_url"], "https://careers.example.test/jobs/frontend")
        self.assertEqual(first["raw_location"], "Worldwide")
        self.assertEqual(first["payload"]["himalayas"], self.payload["jobs"][0])

        second = import_himalayas.normalize_job(self.payload["jobs"][1], date(2026, 8, 11))
        self.assertEqual(second["source_url"], "https://jobs.example.test/react")
        self.assertEqual(second["raw_location"], "Serbia")
        self.assertEqual(second["posted_at"], "2026-08-10")

    def test_collect_uses_registry_age_window_and_deduplicates_guid_across_queries(self):
        settings = {
            "search_url": "https://himalayas.example.test/jobs/api/search",
            "seniority": ["Entry-level", "Mid-level"],
            "employment_types": ["Full Time"],
        }
        run = {
            "selection": "narrow",
            "queries": ["Frontend Developer", "React Developer"],
            "cadence_hours": 24,
            "max_age_days": 7,
        }
        current = copy.deepcopy(self.payload["jobs"][1])
        current["guid"] = "guid-current"
        current["pubDate"] = "2026-08-10T08:00:00Z"
        old = copy.deepcopy(current)
        old["guid"] = "guid-old"
        old["pubDate"] = "2026-07-01T08:00:00Z"
        requested = []

        def fetch(url):
            requested.append(url)
            return {"jobs": [current, old]}

        records, summary, errors = import_himalayas.collect_records(
            settings, run, today_value=date(2026, 8, 11), fetch=fetch,
        )

        self.assertEqual(errors, [])
        self.assertEqual(len(records), 1)
        self.assertEqual(summary, {
            "queries": 2, "fetched": 4, "outside_age_window": 2,
            "duplicates": 1, "records": 1,
        })
        self.assertEqual(len(requested), 2)
        self.assertIn("seniority=Entry-level%2CMid-level", requested[0])
        self.assertIn("employment_type=Full+Time", requested[0])

    def test_fetch_retries_rate_limit_only_a_bounded_number_of_times(self):
        calls, delays = [], []

        def fake_urlopen(request, timeout):
            calls.append((request.full_url, timeout))
            if len(calls) == 1:
                raise HTTPError(request.full_url, 429, "Too Many Requests", {}, None)
            return FakeResponse({"jobs": []})

        result = import_himalayas.fetch_json(
            "https://himalayas.example.test/jobs/api/search?q=react",
            urlopen_func=fake_urlopen,
            sleep_func=delays.append,
        )

        self.assertEqual(result, {"jobs": []})
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0][1], import_himalayas.REQUEST_TIMEOUT_SECONDS)
        self.assertEqual(delays, [1])


class HimalayasAdapterCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in ("data/inbox", "data"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.settings = {
            "geo": ["Serbia", "worldwide", "Europe"],
            "search_url": "https://himalayas.example.test/jobs/api/search",
            "narrow_queries": ["Frontend Developer"],
            "broad_queries": ["Product Engineer"],
            "cadence_hours": 24,
            "broad_cadence_hours": 72,
            "max_age_days": 7,
            "fallback_max_age_days": 30,
            "seniority": ["Entry-level", "Mid-level"],
            "employment_types": ["Full Time", "Intern", "Contractor"],
        }
        self.records = [{
            "source": "Himalayas",
            "source_job_id": "raw-001",
            "company": "ExampleCo",
            "role": "Frontend Developer",
            "source_url": "https://himalayas.app/jobs/raw-001",
            "application_url": "https://careers.example.test/jobs/raw-001",
            "posted_at": "2026-08-10",
            "raw_location": "Worldwide",
            "found_at": "2026-08-11",
            "payload": {"himalayas": {"guid": "raw-001"}},
        }]
        self.summary = {
            "duplicates": 0, "fetched": 2, "outside_age_window": 1, "queries": 1, "records": 1,
        }

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *arguments):
        output = io.StringIO()
        with (
            patch.object(import_himalayas, "ROOT", self.root),
            patch.object(import_himalayas, "INBOX_DIR", self.root / "data" / "inbox"),
            patch.object(import_himalayas, "load_himalayas_settings", return_value=self.settings),
            patch.object(import_himalayas, "collect_records", return_value=(self.records, self.summary, [])),
            patch.object(sys, "argv", ["import_himalayas.py", *arguments]),
            redirect_stdout(output),
        ):
            import_himalayas.main()
        return json.loads(output.getvalue())

    def test_write_creates_one_valid_raw_batch_without_ingesting(self):
        output = self.root / "data" / "inbox" / "himalayas-test.jsonl"
        payload = self.invoke("--narrow", "--output", str(output))

        self.assertEqual((payload["mode"], payload["selection"]), ("write_raw_batch", "narrow"))
        self.assertEqual((payload["cadence_hours"], payload["max_age_days"]), (24, 7))
        self.assertEqual(payload["summary"], {
            "duplicates": 0, "fetched": 2, "outside_age_window": 1, "queries": 1, "records": 1,
        })
        self.assertEqual(payload["output"], "data/inbox/himalayas-test.jsonl")
        records = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()]
        self.assertEqual(len(records), 1)
        self.assertIn("himalayas", records[0]["payload"])

        validated = subprocess.run(
            [sys.executable, "scripts/inbox.py", "validate", str(output)],
            cwd=PROJECT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(validated.returncode, 0, validated.stderr)
        self.assertTrue(json.loads(validated.stdout)["ok"])

        self.assertFalse((self.root / "data" / "jobs.csv").exists())

    def test_broad_dry_run_does_not_create_a_raw_batch(self):
        payload = self.invoke("--broad", "--dry-run")

        self.assertEqual((payload["mode"], payload["selection"]), ("dry_run", "broad"))
        self.assertEqual((payload["cadence_hours"], payload["max_age_days"]), (72, 30))
        self.assertIsNone(payload["output"])
        self.assertFalse(list((self.root / "data" / "inbox").glob("*.jsonl")))


if __name__ == "__main__":
    unittest.main()
