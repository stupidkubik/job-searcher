import re
import unittest
from pathlib import Path


PROJECT = Path(__file__).resolve().parents[1]


class DocumentationMapTests(unittest.TestCase):
    def assert_local_links_exist(self, document):
        body = document.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^]]+\]\(([^)]+)\)", body):
            if "://" in target or target.startswith("#"):
                continue
            relative = target.split("#", 1)[0]
            resolved = (document.parent / relative).resolve()
            self.assertTrue(resolved.exists(), f"{document}: broken local link {target}")

    def test_general_docs_link_current_architecture_and_documentation_map(self):
        readme = (PROJECT / "README.md").read_text(encoding="utf-8")
        docs_index = (PROJECT / "docs" / "README.md").read_text(encoding="utf-8")
        architecture = (PROJECT / "docs" / "current-architecture.md").read_text(encoding="utf-8")

        self.assertIn("docs/current-architecture.md", readme)
        self.assertIn("docs/README.md", readme)
        for path in (
            "data/schema.md",
            "data/operations/README.md",
            "data/inbox/README.md",
            "agent-operations.md",
            "sources/README.md",
        ):
            self.assertIn(path, docs_index)
        self.assertIn("source-discovery.yml", architecture)
        self.assertIn("Europe/Belgrade", architecture)
        for document in (
            PROJECT / "README.md",
            PROJECT / "docs" / "README.md",
            PROJECT / "docs" / "current-architecture.md",
        ):
            self.assert_local_links_exist(document)

    def test_current_operation_overview_allows_atomic_add_children(self):
        overview = (PROJECT / "docs" / "agent-operations.md").read_text(encoding="utf-8")

        self.assertIn("batch child with stable `client_ref`", overview)
        self.assertNotIn("`add` cannot be a child", overview)
        self.assertNotIn("single-operation only", overview)

    def test_hirify_documents_link_rules_and_preserve_the_automation_boundary(self):
        source_index = PROJECT / "docs" / "sources" / "README.md"
        playbook = PROJECT / "docs" / "sources" / "hirify.md"
        rules = PROJECT / "docs" / "sources" / "hirify-discovery-rules.md"
        discovery = PROJECT / "docs" / "sources" / "hirify-technical-discovery.md"

        for document in (source_index, playbook, rules, discovery):
            self.assert_local_links_exist(document)

        self.assertIn("hirify-discovery-rules.md", playbook.read_text(encoding="utf-8"))
        rules_body = rules.read_text(encoding="utf-8")
        self.assertIn("implement a networked Hirify crawler without documented permission", rules_body)
        self.assertIn("do not write Hirify records into the current JSONL inbox contract", rules_body)
        self.assertIn("Controlled live validation", rules_body)

    def test_source_docs_keep_one_universal_lifecycle(self):
        source_dir = PROJECT / "docs" / "sources"
        lifecycle = (source_dir / "README.md").read_text(encoding="utf-8")

        for invariant in (
            "Narrow → broad discovery",
            "Exact identity и dedupe до анализа",
            "First-party verification",
            "Canonical employer status",
            "Immutable write path",
            "каждая exact vacancy, которую открыли и оценили",
        ):
            self.assertIn(invariant, lifecycle)

        playbooks = (
            "greenhouse.md",
            "himalayas.md",
            "helloworld-rs.md",
            "hirify.md",
            "hiringcafe.md",
            "hacker-news-who-is-hiring.md",
            "jaabz.md",
            "linkedin.md",
            "reactiflux-discord.md",
            "startit-jobs.md",
            "we-work-remotely.md",
            "welcome-to-the-jungle.md",
            "wellfound.md",
            "yc-work-at-a-startup.md",
        )
        required_sections = (
            "## Роль и доступ",
            "## Routes: narrow → broad",
            "## Exact identity",
            "## Source status",
            "## Trust и ловушки",
            "## Stop rule",
        )

        for filename in playbooks:
            document = source_dir / filename
            body = document.read_text(encoding="utf-8")
            self.assert_local_links_exist(document)
            self.assertIn("[`README.md`](README.md)", body)
            for section in required_sections:
                self.assertIn(section, body, f"{filename}: missing {section}")
            self.assertNotIn("## Connector checklist", body)
            self.assertLessEqual(
                len(body.splitlines()),
                120,
                f"{filename}: source playbook is duplicating the common lifecycle",
            )

    def test_profile_digest_carries_every_required_bootstrap_key(self):
        """docs/agent-write-path-plan-2026-09-07.md, Э6: profile-digest.md
        drift from config/profile.md is guarded by this required-key check,
        not by re-deriving the digest from the full profile."""
        digest = PROJECT / "config" / "profile-digest.md"
        self.assert_local_links_exist(digest)
        body = digest.read_text(encoding="utf-8")
        for key in ("Level", "Geo", "Work authorization", "Minimum compensation", "Stack", "Red flags"):
            self.assertIn(f"**{key}**", body, f"profile-digest.md: missing required key {key}")
        self.assertLess(len(body.encode("utf-8")), 4096, "profile-digest.md is no longer a compact digest")

    def test_message_sources_do_not_confuse_message_and_vacancy_identity(self):
        source_dir = PROJECT / "docs" / "sources"
        hn = (source_dir / "hacker-news-who-is-hiring.md").read_text(encoding="utf-8")
        discord = (source_dir / "reactiflux-discord.md").read_text(encoding="utf-8")
        startit = (source_dir / "startit-jobs.md").read_text(encoding="utf-8")

        self.assertIn("item ID идентифицирует message, не vacancy", hn)
        self.assertIn("один URL допустим у нескольких canonical jobs", hn)
        self.assertIn("<server_id>:<channel_id>:<message_id>", discord)
        self.assertIn("оставить unset до наблюдения", startit)


if __name__ == "__main__":
    unittest.main()
