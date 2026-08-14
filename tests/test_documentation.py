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


if __name__ == "__main__":
    unittest.main()
