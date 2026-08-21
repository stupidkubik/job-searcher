import tempfile
import unittest
from pathlib import Path

from scripts.source_config import CONFIG_PATH, SourceConfigError, load_source_config


class SourceConfigTests(unittest.TestCase):
    def write_registry(self, content):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        path = Path(temporary.name) / "sources.toml"
        path.write_text(content, encoding="utf-8")
        return path

    def test_committed_registry_is_valid(self):
        sources = load_source_config(CONFIG_PATH)
        himalayas = sources["Himalayas"]
        self.assertEqual(himalayas["type"], "api")
        self.assertEqual(himalayas["cadence_hours"], 24)
        self.assertTrue(himalayas["verification"]["first_party_required"])
        self.assertTrue(himalayas["verification"]["apply_required"])

        telegram = sources["Telegram"]
        self.assertEqual(telegram["type"], "messaging")
        self.assertTrue(telegram["aggregator"])
        self.assertTrue(telegram["verification"]["first_party_required"])
        self.assertTrue(telegram["verification"]["apply_required"])

    def test_rejects_unknown_source_type_before_network_work(self):
        path = self.write_registry("""
[sources.Broken]
enabled = true
type = "rss"
cadence_hours = 24
max_age_days = 7
geo = ["worldwide"]
aggregator = true
verification = { first_party_required = true, apply_required = true }
caveats = ["Discovery only."]
""")
        with self.assertRaisesRegex(SourceConfigError, "неизвестный type"):
            load_source_config(path)

    def test_rejects_invalid_cadence_before_network_work(self):
        path = self.write_registry("""
[sources.Broken]
enabled = true
type = "api"
cadence_hours = 0
max_age_days = 7
geo = ["worldwide"]
aggregator = true
verification = { first_party_required = true, apply_required = true }
caveats = ["Discovery only."]
""")
        with self.assertRaisesRegex(SourceConfigError, "cadence_hours"):
            load_source_config(path)

    def test_rejects_missing_verification_policy_before_network_work(self):
        path = self.write_registry("""
[sources.Broken]
enabled = true
type = "api"
cadence_hours = 24
max_age_days = 7
geo = ["worldwide"]
aggregator = true
caveats = ["Discovery only."]
""")
        with self.assertRaisesRegex(SourceConfigError, "verification"):
            load_source_config(path)


if __name__ == "__main__":
    unittest.main()
