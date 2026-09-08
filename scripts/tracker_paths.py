"""Filesystem locations the tracker reads and writes.

docs/agent-write-path-plan-2026-09-07.md, Э10.
"""

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Paths:
    """Every filesystem location jobs.py reads or writes, derived from one
    mutable `root`.

    docs/agent-write-path-plan-2026-09-07.md, Э10: agent_operations.py's
    `temporary_tracker_workspace()` repoints the whole tracker at a scratch
    copy for the duration of one operation by reassigning a single field
    (`PATHS.root`) instead of patching several separate module globals. Every
    reader in this module goes through `PATHS.<name>` rather than a
    module-level constant captured at import time, so that reassignment is
    the only thing that has to work for the repoint to take effect.
    """

    root: Path

    @property
    def csv_path(self):
        return self.root / "data" / "jobs.csv"

    @property
    def job_sources_path(self):
        return self.root / "data" / "job_sources.csv"

    @property
    def apps_dir(self):
        return self.root / "applications"

    @property
    def template_path(self):
        return self.apps_dir / "_TEMPLATE.md"

    @property
    def tracker_path(self):
        return self.root / "docs" / "tracker.md"

    @property
    def index_dir(self):
        return self.root / "data" / "index"

    @property
    def known_index_path(self):
        return self.index_dir / "known.tsv"

    @property
    def keys_index_path(self):
        return self.index_dir / "keys.tsv"

    @property
    def active_index_path(self):
        return self.index_dir / "active.csv"


PATHS = Paths(root=Path(__file__).resolve().parent.parent)
