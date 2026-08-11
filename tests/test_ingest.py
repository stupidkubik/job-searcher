import json
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
            ]
            path.write_text("\n".join(invalid_lines), encoding="utf-8")
            before = path.read_bytes()
            invalid = self.invoke(path)

            self.assertEqual(invalid.returncode, 1)
            self.assertEqual(len(invalid.stdout.splitlines()), 1)
            summary = json.loads(invalid.stdout)
            messages = "\n".join(summary["errors"])
            self.assertFalse(summary["ok"])
            self.assertEqual(summary["records"], 5)
            self.assertIn("ожидается JSON object", messages)
            self.assertIn("role должен быть непустой строкой", messages)
            self.assertIn("posted_at должен иметь формат YYYY-MM-DD", messages)
            self.assertIn("source_url должен быть абсолютным http(s) URL", messages)
            self.assertIn("неизвестные поля: unexpected", messages)
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


if __name__ == "__main__":
    unittest.main()
