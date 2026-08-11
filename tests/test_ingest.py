import csv
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]
FIXTURE = PROJECT / "tests" / "fixtures" / "inbox" / "himalayas-small.jsonl"


class RawInboxTests(unittest.TestCase):
    def invoke(self, path):
        return subprocess.run(
            [sys.executable, "scripts/inbox.py", "validate", str(path)],
            cwd=PROJECT,
            text=True,
            capture_output=True,
        )

    def valid_record(self, **changes):
        record = {
            "source": "Himalayas",
            "source_job_id": "raw-001",
            "company": "ExampleCo",
            "role": "Frontend Developer",
            "source_url": "https://himalayas.app/jobs/raw-001",
            "application_url": "https://careers.example.test/jobs/raw-001",
            "posted_at": "2026-08-10",
            "raw_location": "Worldwide",
            "found_at": "2026-08-11",
        }
        record.update(changes)
        return record

    def test_committed_fixture_is_valid_immutable_and_has_stable_batch_id(self):
        before = FIXTURE.read_bytes()
        first = self.invoke(FIXTURE)
        second = self.invoke(FIXTURE)

        self.assertEqual(first.returncode, 0, first.stderr)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(len(first.stdout.splitlines()), 1)
        first_summary = json.loads(first.stdout)
        second_summary = json.loads(second.stdout)
        self.assertTrue(first_summary["ok"])
        self.assertEqual(first_summary["records"], 2)
        self.assertEqual(first_summary["errors"], [])
        self.assertTrue(first_summary["batch_id"].startswith("sha256:"))
        self.assertEqual(first_summary["batch_id"], second_summary["batch_id"])
        self.assertEqual(FIXTURE.read_bytes(), before)

    def test_rejects_non_utf8_json_shape_required_fields_dates_and_urls(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "invalid.jsonl"
            path.write_bytes(b"\xff\xfe")
            non_utf8 = self.invoke(path)
            self.assertEqual(non_utf8.returncode, 1)
            self.assertIn("input не UTF-8", json.loads(non_utf8.stdout)["errors"][0])

            invalid_lines = [
                json.dumps([self.valid_record()]),
                json.dumps(self.valid_record(role="")),
                json.dumps(self.valid_record(posted_at="2026/08/10")),
                "",
                json.dumps(self.valid_record(source_url="not-a-url")),
                json.dumps(self.valid_record(unexpected="field")),
                json.dumps(self.valid_record(payload={"hard_filter_reason": "not_a_reason"})),
            ]
            path.write_text("\n".join(invalid_lines), encoding="utf-8")
            before = path.read_bytes()
            invalid = self.invoke(path)

            self.assertEqual(invalid.returncode, 1)
            self.assertEqual(len(invalid.stdout.splitlines()), 1)
            summary = json.loads(invalid.stdout)
            messages = "\n".join(summary["errors"])
            self.assertFalse(summary["ok"])
            self.assertEqual(summary["records"], 7)
            self.assertIn("ожидается JSON object", messages)
            self.assertIn("role должен быть непустой строкой", messages)
            self.assertIn("posted_at должен иметь формат YYYY-MM-DD", messages)
            self.assertIn("source_url должен быть абсолютным http(s) URL", messages)
            self.assertIn("неизвестные поля: unexpected", messages)
            self.assertIn("payload.hard_filter_reason не входит в canonical enum", messages)
            self.assertIn("пустая строка", messages)
            self.assertEqual(path.read_bytes(), before)

    def test_batch_id_depends_on_exact_immutable_input_bytes(self):
        with tempfile.TemporaryDirectory() as temporary:
            first_path = Path(temporary) / "first.jsonl"
            second_path = Path(temporary) / "second.jsonl"
            first_path.write_text(json.dumps(self.valid_record()) + "\n", encoding="utf-8")
            second_path.write_text(json.dumps(self.valid_record(company="OtherCo")) + "\n", encoding="utf-8")

            first = json.loads(self.invoke(first_path).stdout)
            second = json.loads(self.invoke(second_path).stdout)
            self.assertTrue(first["ok"])
            self.assertTrue(second["ok"])
            self.assertNotEqual(first["batch_id"], second["batch_id"])


class IngestCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        for directory in ("data", "applications", "scripts", "config", "inbox"):
            (self.root / directory).mkdir()
        for name in ("jobs.py", "ingestion.py", "inbox.py", "source_config.py"):
            shutil.copy2(PROJECT / "scripts" / name, self.root / "scripts" / name)
        shutil.copy2(PROJECT / "config" / "sources.toml", self.root / "config" / "sources.toml")
        for name in ("jobs.csv", "job_sources.csv"):
            header = (PROJECT / "data" / name).read_text(encoding="utf-8").splitlines()[0]
            (self.root / "data" / name).write_text(header + "\n", encoding="utf-8")
        shutil.copy2(PROJECT / "applications" / "_TEMPLATE.md", self.root / "applications" / "_TEMPLATE.md")

    def tearDown(self):
        self.temporary.cleanup()

    def invoke(self, *arguments, env=None):
        return subprocess.run(
            [sys.executable, "scripts/jobs.py", *arguments], cwd=self.root,
            text=True, capture_output=True, env=env,
        )

    def rows(self, name):
        with (self.root / "data" / name).open(newline="", encoding="utf-8") as file:
            return list(csv.DictReader(file))

    def record(self, suffix, **changes):
        raw = {
            "source": "Himalayas",
            "source_job_id": f"himalayas-{suffix}",
            "company": f"Example {suffix}",
            "role": "Frontend Developer",
            "source_url": f"https://himalayas.app/jobs/{suffix}",
            "application_url": f"https://careers.example.test/jobs/{suffix}",
            "posted_at": "2026-08-10",
            "raw_location": "Worldwide",
            "found_at": "2026-08-11",
        }
        raw.update(changes)
        return raw

    def write_batch(self, entries, name="batch.jsonl"):
        path = self.root / "inbox" / name
        lines = [entry if isinstance(entry, str) else json.dumps(entry) for entry in entries]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def write_resolutions(self, batch, resolutions, name="batch.resolution.json", batch_id=None):
        path = self.root / "inbox" / name
        batch_id = batch_id or "sha256:" + hashlib.sha256(batch.read_bytes()).hexdigest()
        path.write_text(json.dumps({
            "version": 1,
            "batch_id": batch_id,
            "resolutions": resolutions,
        }), encoding="utf-8")
        return path

    def snapshot(self):
        return {
            "jobs": (self.root / "data" / "jobs.csv").read_bytes(),
            "sources": (self.root / "data" / "job_sources.csv").read_bytes(),
            "cards": sorted(path.name for path in (self.root / "applications").glob("job-*.md")),
        }

    def test_dry_run_classifies_every_line_without_writing(self):
        duplicate_url = "https://careers.example.test/jobs/existing"
        seeded = self.invoke(
            "add", "--company", "ExistingCo", "--role", "Frontend Developer", "--source", "Manual",
            "--original-url", duplicate_url, "--no-file",
        )
        self.assertEqual(seeded.returncode, 0, seeded.stderr)
        batch = self.write_batch([
            self.record("pending"),
            self.record("noise", role="Account Executive"),
            self.record("senior", role="Senior Frontend Engineer"),
            self.record("duplicate", company="ExistingCo", application_url=duplicate_url),
        ])
        before = self.snapshot()

        result = self.invoke("ingest", str(batch), "--dry-run", "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertTrue(payload["ok"])
        self.assertEqual(payload["mode"], "dry_run")
        self.assertEqual(payload["summary"], {
            "input": 4, "invalid": 0, "noise": 1, "skipped": 1, "duplicates": 1, "pending": 1,
        })
        self.assertEqual([item["outcome"] for item in payload["outcomes"]], ["pending", "noise", "skipped", "duplicate"])
        self.assertEqual(payload["outcomes"][2]["reason"], "seniority_too_high")
        self.assertEqual(payload["outcomes"][3]["reason"], "canonical_original_url")
        self.assertEqual(self.snapshot(), before)

    def test_invalid_line_reports_jsonl_line_and_prevents_partial_apply(self):
        batch = self.write_batch([self.record("valid"), "{not json}"], "invalid.jsonl")
        before = self.snapshot()

        result = self.invoke("ingest", str(batch), "--format", "json")

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"], "invalid_batch")
        self.assertEqual(payload["summary"], {
            "input": 2, "invalid": 1, "noise": 0, "skipped": 0, "duplicates": 0, "pending": 1,
        })
        invalid = payload["outcomes"][1]
        self.assertEqual((invalid["line"], invalid["outcome"]), (2, "invalid"))
        self.assertIn("line 2", invalid["errors"][0])
        self.assertEqual(self.snapshot(), before)

    def test_apply_is_idempotent_and_aggregator_records_stay_unverified(self):
        batch = self.write_batch([self.record("first"), self.record("second")], "apply.jsonl")

        first = self.invoke("ingest", str(batch), "--format", "json")
        self.assertEqual(first.returncode, 0, first.stderr)
        first_payload = json.loads(first.stdout)
        self.assertEqual(first_payload["applied"], {
            "jobs_created": 2, "source_references_created": 2, "application_cards_created": 0,
        })
        self.assertEqual(len(self.rows("jobs.csv")), 2)
        self.assertEqual(len(self.rows("job_sources.csv")), 2)
        self.assertFalse(list((self.root / "applications").glob("job-*.md")))
        for row in self.rows("jobs.csv"):
            self.assertEqual((row["first_party_verified"], row["apply_verified"]), ("unknown", "unknown"))
            self.assertEqual(row["original_url"], "")
            self.assertEqual(row["next_action"], "verify first-party")

        before_repeat = self.snapshot()
        repeated = self.invoke("ingest", str(batch), "--format", "json")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        repeated_payload = json.loads(repeated.stdout)
        self.assertEqual(repeated_payload["summary"], {
            "input": 2, "invalid": 0, "noise": 0, "skipped": 0, "duplicates": 2, "pending": 0,
        })
        self.assertEqual(repeated_payload["applied"], {
            "jobs_created": 0, "source_references_created": 0, "application_cards_created": 0,
        })
        self.assertEqual(self.snapshot(), before_repeat)

    def test_internship_is_not_auto_skipped_as_too_junior(self):
        batch = self.write_batch([
            self.record("intern", role="Frontend Developer Intern"),
        ], "intern.jsonl")

        result = self.invoke("ingest", str(batch), "--dry-run", "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"], {
            "input": 1, "invalid": 0, "noise": 0, "skipped": 0, "duplicates": 0, "pending": 1,
        })
        self.assertEqual(payload["outcomes"][0]["outcome"], "pending")

    def test_fuzzy_candidate_blocks_the_entire_batch_until_resolved(self):
        seeded = self.invoke(
            "add", "--company", "Acme Studio Inc.", "--role", "Frontend Engineer", "--source", "Manual", "--no-file",
        )
        self.assertEqual(seeded.returncode, 0, seeded.stderr)
        batch = self.write_batch([self.record("fuzzy", company="Acme Studio", role="Frontend Developer")])
        before = self.snapshot()

        result = self.invoke("ingest", str(batch), "--format", "json")

        self.assertEqual(result.returncode, 2)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"], "fuzzy_duplicate_requires_resolution")
        self.assertEqual(payload["outcomes"][0]["reason"], "fuzzy_duplicate_requires_resolution")
        self.assertEqual(payload["outcomes"][0]["candidates"][0]["id"], "job-0001")
        self.assertEqual(self.snapshot(), before)

    def test_fuzzy_resolution_can_keep_distinct_batch_records_separate(self):
        batch = self.write_batch([
            self.record("first", company="Acme Studio", role="Frontend Engineer"),
            self.record("second", company="Acme Studio", role="Frontend Developer"),
        ])
        resolutions = self.write_resolutions(batch, [{
            "line": 2,
            "candidate": {"line": 1},
            "decision": "separate",
        }])
        before = self.snapshot()

        dry_run = self.invoke(
            "ingest", str(batch), "--resolutions", str(resolutions), "--dry-run", "--format", "json",
        )
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        dry_payload = json.loads(dry_run.stdout)
        self.assertTrue(dry_payload["ok"])
        self.assertEqual(dry_payload["resolution"]["used"], 1)
        self.assertEqual(dry_payload["outcomes"][1]["resolution"], "separate")
        self.assertEqual(self.snapshot(), before)

        applied = self.invoke("ingest", str(batch), "--resolutions", str(resolutions), "--format", "json")
        self.assertEqual(applied.returncode, 0, applied.stderr)
        payload = json.loads(applied.stdout)
        self.assertEqual(payload["applied"], {
            "jobs_created": 2, "source_references_created": 2, "application_cards_created": 0,
        })
        self.assertEqual((len(self.rows("jobs.csv")), len(self.rows("job_sources.csv"))), (2, 2))

        repeated = self.invoke("ingest", str(batch), "--resolutions", str(resolutions), "--format", "json")
        self.assertEqual(repeated.returncode, 0, repeated.stderr)
        repeated_payload = json.loads(repeated.stdout)
        self.assertEqual(repeated_payload["resolution"]["used"], 1)
        self.assertEqual(repeated_payload["applied"], {
            "jobs_created": 0, "source_references_created": 0, "application_cards_created": 0,
        })

    def test_fuzzy_resolution_can_merge_with_a_canonical_job(self):
        seeded = self.invoke(
            "add", "--company", "Acme Studio Inc.", "--role", "Frontend Engineer", "--source", "Manual", "--no-file",
        )
        self.assertEqual(seeded.returncode, 0, seeded.stderr)
        batch = self.write_batch([self.record("fuzzy", company="Acme Studio", role="Frontend Developer")])
        resolutions = self.write_resolutions(batch, [{
            "line": 1,
            "candidate": {"job_id": "job-0001"},
            "decision": "duplicate",
        }])

        result = self.invoke("ingest", str(batch), "--resolutions", str(resolutions), "--format", "json")

        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["outcomes"][0], {
            "line": 1,
            "outcome": "duplicate",
            "reason": "fuzzy_resolution",
            "resolution": "duplicate",
            "job_id": "job-0001",
            "source_reference_created": True,
        })
        self.assertEqual(len(self.rows("jobs.csv")), 1)
        self.assertEqual(len(self.rows("job_sources.csv")), 1)

    def test_resolution_sidecar_must_match_the_exact_batch(self):
        batch = self.write_batch([self.record("pending")])
        resolutions = self.write_resolutions(batch, [], batch_id="sha256:not-the-batch")
        before = self.snapshot()

        result = self.invoke("ingest", str(batch), "--resolutions", str(resolutions), "--format", "json")

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"], "invalid_batch")
        self.assertIn("batch_id не совпадает", payload["errors"][0])
        self.assertEqual(self.snapshot(), before)

    def test_transaction_rolls_back_when_replacement_fails_between_csv_files(self):
        def atomic_record(number):
            code = hashlib.sha256(str(number).encode("ascii")).hexdigest()[:12]
            return self.record(
                f"atomic-{number}", company=f"Company {code}", role=f"Frontend {code}",
            )

        batch = self.write_batch([atomic_record(number) for number in range(50)], "atomic.jsonl")
        before = self.snapshot()
        environment = {**os.environ, "JOBS_INGEST_FAIL_AFTER_REPLACE": "1"}

        result = self.invoke("ingest", str(batch), "--format", "json", env=environment)

        self.assertEqual(result.returncode, 1)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["error"], "apply_failed")
        self.assertIn("injected ingest replacement failure", payload["errors"][-1])
        self.assertEqual(self.snapshot(), before)

        successful = self.invoke("ingest", str(batch), "--format", "json")
        self.assertEqual(successful.returncode, 0, successful.stderr)
        success_payload = json.loads(successful.stdout)
        self.assertEqual(success_payload["applied"], {
            "jobs_created": 50, "source_references_created": 50, "application_cards_created": 0,
        })
        self.assertEqual((len(self.rows("jobs.csv")), len(self.rows("job_sources.csv"))), (50, 50))


if __name__ == "__main__":
    unittest.main()
