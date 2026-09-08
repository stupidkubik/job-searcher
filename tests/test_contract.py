import subprocess
import sys
import unittest
from pathlib import Path

from scripts import agent_operations as ops
from scripts import jobs


PROJECT = Path(__file__).resolve().parents[1]
CONTRACT = PROJECT / "data" / "operations" / "contract.md"


class ContractGenerationTests(unittest.TestCase):
    """docs/agent-write-path-plan-2026-09-07.md, Э2: contract.md is generated
    from the same allowlists the runner enforces, so it cannot drift silently
    from the code."""

    def test_render_contract_check_is_clean(self):
        result = subprocess.run(
            [sys.executable, "scripts/agent_operations.py", "render-contract", "--check"],
            cwd=PROJECT,
            text=True,
            capture_output=True,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_every_allowlisted_field_appears_in_its_command_table(self):
        body = CONTRACT.read_text(encoding="utf-8")
        command_allowlists = {
            "add": ops.ADD_ALLOWED_ARGS,
            "verify": ops.VERIFY_ALLOWED_ARGS,
            "screen": ops.SCREEN_ALLOWED_ARGS,
            "set": ops.SET_ALLOWED_ARGS,
            "status": ops.STATUS_ALLOWED_ARGS,
        }
        sections = {
            name: section for name, section in self._sections(body).items() if name in command_allowlists
        }
        self.assertEqual(set(sections), set(command_allowlists))
        for name, allowed in command_allowlists.items():
            section = sections[name]
            for field in allowed:
                self.assertIn(f"`{field}`", section, f"{name}: missing field {field}")

    def test_every_enum_value_from_jobs_enums_is_present(self):
        body = CONTRACT.read_text(encoding="utf-8")
        for field, values in jobs.ENUMS.items():
            for value in values:
                self.assertIn(f"`{value}`", body, f"{field}: missing enum value {value}")

    def test_every_canonical_field_is_in_a_command_or_runner_computed(self):
        body = CONTRACT.read_text(encoding="utf-8")
        accepted = set().union(*ops.ALL_ARG_ALLOWLISTS)
        runner_computed = set(ops.fields_no_command_accepts())
        self.assertEqual(runner_computed, set(jobs.FIELDS) - accepted)
        no_command_section = self._sections(body)["Fields no command accepts"]
        for field in jobs.FIELDS:
            in_a_command_table = field in accepted
            in_runner_computed = field in runner_computed and f"`{field}`" in no_command_section
            self.assertTrue(
                in_a_command_table or in_runner_computed,
                f"{field} is neither accepted by a command nor listed as runner-computed",
            )

    def test_every_documented_invariant_is_mentioned(self):
        body = CONTRACT.read_text(encoding="utf-8")
        for invariant in ops.CONTRACT_INVARIANTS:
            self.assertIn(invariant, body)

    def _sections(self, body):
        sections = {}
        current = None
        buffer = []
        for line in body.splitlines():
            if line.startswith("## "):
                if current is not None:
                    sections[current] = "\n".join(buffer)
                current = line[3:].strip()
                # Normalize headings like "`add`" and "`add` with `duplicate_of`"
                # down to a bare command name where unambiguous.
                if current.startswith("`") and current.endswith("`") and current.count("`") == 2:
                    current = current.strip("`")
                buffer = []
            else:
                buffer.append(line)
        if current is not None:
            sections[current] = "\n".join(buffer)
        return sections


if __name__ == "__main__":
    unittest.main()
