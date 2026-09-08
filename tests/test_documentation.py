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

    def test_agents_md_bootstraps_from_indexes_not_full_csv(self):
        """docs/agent-write-path-plan-2026-09-07.md, Э7: the agent-facing
        bootstrap order and the launch prompt draft must point at the
        generated indexes and the field contract, not at a full-CSV read."""
        agents = re.sub(r"\s+", " ", (PROJECT / "AGENTS.md").read_text(encoding="utf-8"))
        self.assert_local_links_exist(PROJECT / "AGENTS.md")

        for required in (
            "pull request",
            "считать операцию завершённой",
            "data/operations/contract.md",
            "data/index/known.tsv",
            "data/index/keys.tsv",
            "data/index/active.csv",
            "config/profile-digest.md",
            "docs/sources/README.md",
            # data/index/* is a CI-gated generated view exactly like
            # docs/tracker.md, so the write-path contract has to name it;
            # otherwise a local write leaves a stale index and reds validate.yml.
            "render-index",
        ):
            self.assertIn(required.lower(), agents.lower(), f"AGENTS.md: missing {required}")

        self.assertNotIn("Прочитать `data/jobs.csv` целиком", agents)
        self.assertNotIn("Прочитать `data/job_sources.csv` целиком", agents)

        prompt = (PROJECT / "docs" / "agent-operations.md").read_text(encoding="utf-8")
        self.assertIn("config/profile-digest.md", prompt)
        self.assertIn("data/operations/contract.md", prompt)
        self.assertIn("NEW operation_id", prompt)
        self.assertNotIn("read the full data/jobs.csv", prompt)

    def test_launch_prompt_matches_the_contract_it_launches(self):
        """The prompt is the only part of the contract an agent reads before
        it can read anything else, so a promise it makes that AGENTS.md
        contradicts is worse than a missing one."""
        prompt = (PROJECT / "docs" / "agent-operations.md").read_text(encoding="utf-8")
        launch = prompt.split("### Recommended ChatGPT launch prompt", 1)[1].split("```", 2)[1]

        # G-14: the tracker is human-only. An earlier draft listed it among the
        # files not to read "in full", which reads as conditional permission.
        self.assertIn("Never read docs/tracker.md at all", launch)
        # Э1: the result file, not the workflow colour, is the error channel.
        self.assertIn("data/operations/results/<operation_id>.json", launch)
        self.assertIn("error.code", launch)
        self.assertIn("NEW operation_id", launch)
        # Э4 batch limits and Э6 generated indexes the agent must not hand-edit.
        self.assertIn("data/index/*", launch)
        for status in ("completed", "partial", "conflict", "rejected"):
            self.assertIn(status, launch, f"launch prompt does not name result status {status}")

    def test_message_sources_do_not_confuse_message_and_vacancy_identity(self):
        source_dir = PROJECT / "docs" / "sources"
        hn = (source_dir / "hacker-news-who-is-hiring.md").read_text(encoding="utf-8")
        discord = (source_dir / "reactiflux-discord.md").read_text(encoding="utf-8")
        startit = (source_dir / "startit-jobs.md").read_text(encoding="utf-8")

        self.assertIn("item ID идентифицирует message, не vacancy", hn)
        self.assertIn("один URL допустим у нескольких canonical jobs", hn)
        self.assertIn("<server_id>:<channel_id>:<message_id>", discord)
        self.assertIn("оставить unset до наблюдения", startit)

    def test_no_contract_tells_the_agent_to_wait_for_a_green_workflow_run(self):
        """Э1 made a rejected operation end its run red on purpose, so "wait
        for a successful run" became an instruction that can never be
        satisfied by a rejection: the agent would hang on, or misreport, an
        operation that has in fact already answered it."""
        for relative in ("AGENTS.md", "docs/agent-operations.md", "data/operations/README.md"):
            body = (PROJECT / relative).read_text(encoding="utf-8")
            for phrase in ("successful workflow", "успешного прогона", "успешный прогон"):
                self.assertNotIn(
                    phrase,
                    body,
                    f"{relative}: a rejected result ends the run red, so waiting on {phrase!r} "
                    "would strand the agent on an operation that already has an answer",
                )

    def historical_documents(self):
        """The Historical records section of docs/README.md, as filenames.

        Derived from the index rather than hardcoded: a document archived by
        adding one line there must become guarded by the same commit, which a
        fixed list in this file would silently miss.
        """
        index = (PROJECT / "docs" / "README.md").read_text(encoding="utf-8")
        section = index.split("## Historical records", 1)[1].split("\n## ", 1)[0]
        # Only the link that opens a list item names an archived document; a
        # link later in the same sentence is a cross-reference to a living one.
        names = sorted(set(re.findall(r"(?m)^(?:- |  )\[`([a-z0-9][a-z0-9.-]*\.md)`\]", section)))
        self.assertTrue(names, "docs/README.md: Historical records section links no document")
        return names

    def test_historical_documents_carry_the_not_a_contract_banner(self):
        """docs/agent-write-path-plan-2026-09-07.md, Э9/G-13: a historical
        record read via grep (not the docs/README.md index) must still be
        recognizable as non-authoritative, so the banner lives in the file
        itself, not only in the index entry that links to it."""
        banner = "> Historical record. Not a contract."
        names = self.historical_documents()
        # Glob-only entries (tracker-*-feedback.md, tracker-*-audit-*.md) carry
        # no link to extract, so name them here to keep them covered.
        for name in (*names, "tracker-v2-feedback.md", "tracker-status-audit-2026-08-12.md"):
            body = (PROJECT / "docs" / name).read_text(encoding="utf-8")
            self.assertIn(banner, body, f"docs/{name}: missing historical-record banner")
            self.assertLess(
                body.index(banner),
                400,
                f"docs/{name}: banner is not near the top of the file",
            )

    def test_a_historical_document_is_not_also_advertised_as_a_living_contract(self):
        """A closed plan left in the living-documents table is worse than one
        with no entry at all: the agent reads the table top-down and would
        take it for a current instruction."""
        index = (PROJECT / "docs" / "README.md").read_text(encoding="utf-8")
        table = index.split("## Действующие документы", 1)[1].split("\n## ", 1)[0]
        living = set(re.findall(r"\]\(([^)]+)\)", table))
        for name in self.historical_documents():
            self.assertNotIn(name, living, f"docs/{name} is both historical and a living document")


if __name__ == "__main__":
    unittest.main()
