#!/usr/bin/env python3
"""Rehearse a synthetic event on a temporary copy of the current tracker.

No canonical checkout file is modified. The child is killed after the first
replacement; recovery must restore the exact fixture baseline before retry.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
import event_ledger  # noqa: E402
import tracker_transaction as transaction  # noqa: E402
import tracker_write as write  # noqa: E402


CHILD = """
import json, sys
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import tracker_event_write, tracker_write
tracker_write.PATHS.root = Path(sys.argv[2])
tracker_event_write.append_application_event(json.loads(sys.argv[3]))
"""


def copy_current_dataset(destination):
    source = write.PATHS.root
    with write.dataset_write_lock():
        (destination / "data").mkdir()
        (destination / "docs").mkdir()
        for name in ("jobs.csv", "job_sources.csv"):
            shutil.copy2(source / "data" / name, destination / "data" / name)
        shutil.copytree(source / "data/index", destination / "data/index")
        shutil.copytree(source / "applications", destination / "applications")
        shutil.copy2(source / "docs/tracker.md", destination / "docs/tracker.md")
        if (source / "data/application_events").exists():
            shutil.copytree(source / "data/application_events", destination / "data/application_events")
        marker = source / "config/event-ledger-cutover.json"
        if marker.exists():
            (destination / "config").mkdir()
            shutil.copy2(marker, destination / "config/event-ledger-cutover.json")


def snapshot_files(root):
    names = ["data/jobs.csv", "data/job_sources.csv", "docs/tracker.md"]
    names += [path.relative_to(root).as_posix() for path in (root / "data/index").iterdir() if path.is_file()]
    names += [path.relative_to(root).as_posix() for path in (root / "applications").glob("job-*.md")]
    ledger = root / "data/application_events"
    if ledger.is_dir():
        names += [path.relative_to(root).as_posix() for path in ledger.glob("*.jsonl")]
    return {name: transaction.digest((root / name).read_bytes()) for name in sorted(names)}


def event_for(job_id):
    return {
        "schema_version": 1,
        "event_id": f"rehearsal:{job_id}",
        "job_id": job_id,
        "event_type": "application_submitted",
        "occurred_at": write.today(),
        "precision": "date",
        "recorded_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
        "source": "manual",
        "actor": "user",
        "confirmed_by_user": True,
        "evidence_ref": None,
        "payload": {},
        "supersedes": None,
    }


def rehearse():
    original_root = write.PATHS.root
    with tempfile.TemporaryDirectory(prefix="tracker-event-rehearsal-") as directory:
        root = Path(directory)
        copy_current_dataset(root)
        write.PATHS.root = root
        try:
            original_jobs = len(write.load())
            original_sources = len(write.load_job_sources())
            fixture = write.add_job(
                {
                    "company": "Synthetic Rehearsal Co",
                    "role": "Frontend Developer",
                    "source": "Manual",
                    "application_status": "reviewing",
                }
            )
            job_id = fixture["job"]["id"]
            before = snapshot_files(root)
            event = event_for(job_id)
            child = subprocess.run(
                [sys.executable, "-c", CHILD, str(ROOT / "scripts"), str(root), json.dumps(event)],
                cwd=ROOT,
                env={**os.environ, "JOBS_INGEST_KILL_AFTER_REPLACE": "1"},
                capture_output=True,
                text=True,
            )
            if child.returncode != 75:
                raise RuntimeError(f"fault child exited {child.returncode}: {child.stderr}")
            recovery = transaction.recover(root)
            if recovery != "rolled_back" or snapshot_files(root) != before:
                raise RuntimeError("recovery did not restore the exact fixture baseline")
            if (root / f"data/application_events/{job_id}.jsonl").exists():
                raise RuntimeError("rolled-back event file remains")

            from tracker_event_write import append_application_event

            recorded = append_application_event(event)
            retry = append_application_event(event)
            rows, sources = write.load(), write.load_job_sources()
            if len(rows) != original_jobs + 1 or len(sources) != original_sources:
                raise RuntimeError("job/source count changed beyond the synthetic fixture")
            if recorded["outcome"] != "recorded" or retry["outcome"] != "already_recorded":
                raise RuntimeError("event retry is not idempotent")
            ledger = root / "data/application_events"
            report = event_ledger.mismatch_report(ledger, {row["id"]: row for row in rows})
            if any(item["mismatches"] for item in report.values()):
                raise RuntimeError("event projection disagrees with snapshot")
            for path, expected in write.projected_artifacts(rows, sources, ()).items():
                if path.read_bytes() != expected:
                    raise RuntimeError(f"generated view is stale: {path.relative_to(root)}")
            return {
                "ok": True,
                "production_jobs": original_jobs,
                "production_source_references": original_sources,
                "fixture_job_id": job_id,
                "recovery": recovery,
                "retry": retry["outcome"],
                "event_files_in_copy": len(list(ledger.glob("*.jsonl"))),
                "production_files_modified": False,
            }
        finally:
            write.PATHS.root = original_root


if __name__ == "__main__":
    print(json.dumps(rehearse(), ensure_ascii=False, sort_keys=True))
