#!/usr/bin/env python3
"""Rehearse historical event migration, rollback and cutover on a temporary copy."""

import hashlib
import json
import shutil
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

try:
    from scripts.maintenance import backfill_application_events as migration
    from scripts import tracker_paths, tracker_transaction as transaction
except ModuleNotFoundError:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    import backfill_application_events as migration
    import tracker_paths
    import tracker_transaction as transaction


ROOT = Path(__file__).resolve().parents[2]


def copied_files(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for directory in ("data", "applications", "docs", "config")
        for path in (root / directory).rglob("*") if path.is_file()
        if path.name != ".v3-transaction.lock"
    }


def copy_current(destination):
    source = ROOT
    with transaction.locked(source):
        transaction.recover_locked(source)
        for relative in ("data/jobs.csv", "data/job_sources.csv", "docs/tracker.md"):
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, target)
        for relative in ("data/index", "applications", "data/application_events"):
            if (source / relative).exists():
                shutil.copytree(source / relative, destination / relative)
        marker = source / migration.CUTOVER_MARKER
        if marker.exists():
            target = destination / migration.CUTOVER_MARKER
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(marker, target)


def rehearse():
    with tempfile.TemporaryDirectory(prefix="tracker-cutover-") as directory:
        root = Path(directory)
        copy_current(root)
        baseline = copied_files(root)
        recorded_at = datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        summary, pending, revision = migration.plan(root, recorded_at)
        if summary["blocked"]:
            raise RuntimeError(f"cutover has blocked rows: {summary['blocked']}")
        original_publish = migration.publish

        def fail_after_first_replace(target_root, writes, expected, *, validate):
            def fault(stage, index):
                if stage == "after_replace" and index == 0:
                    raise RuntimeError("injected cutover interruption")
            return original_publish(target_root, writes, expected, validate=validate, fault=fault)

        migration.publish = fail_after_first_replace
        try:
            try:
                migration.apply(root, summary, pending, revision, cutover=True)
            except RuntimeError as error:
                if str(error) != "injected cutover interruption":
                    raise
            else:
                raise RuntimeError("cutover fault did not interrupt publication")
        finally:
            migration.publish = original_publish
        if copied_files(root) != baseline or tracker_paths.event_writes_enabled(root):
            raise RuntimeError("rollback did not restore the exact temporary baseline")

        outcome = migration.apply(root, summary, pending, revision, cutover=True)
        if outcome != "applied" or not tracker_paths.event_writes_enabled(root):
            raise RuntimeError("cutover did not atomically enable event writes")
        after = copied_files(root)
        if any(after.get(name) != digest for name, digest in baseline.items()):
            raise RuntimeError("migration changed an existing canonical or generated file")
        second, remaining, second_revision = migration.plan(root, recorded_at)
        if remaining or migration.apply(root, second, remaining, second_revision, cutover=True) != "already_complete":
            raise RuntimeError("migration is not idempotent")
        return {
            "rows": summary["rows"], "pending_jobs": summary["pending_jobs"],
            "pending_events": summary["pending_events"], "blocked": summary["blocked"],
            "rollback": "exact_baseline", "apply": outcome,
            "retry_pending_jobs": second["pending_jobs"],
            "existing_files_unchanged": True,
        }


if __name__ == "__main__":
    print(json.dumps(rehearse(), sort_keys=True))
