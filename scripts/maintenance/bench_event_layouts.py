"""Compare synthetic event layouts without reading or changing tracker data."""

import json
import statistics
import tempfile
import time
from pathlib import Path


SIZES = (1_000, 10_000)
JOB_COUNT = 100


def events(count):
    for index in range(count):
        yield {
            "event_id": f"event-{index:06d}",
            "job_id": f"job-{index % JOB_COUNT + 1:04d}",
            "event_type": "follow_up_sent",
            "occurred_at": "2026-09-23",
            "recorded_at": f"2026-09-23T12:{index % 60:02d}:00Z",
        }


def write_layout(root, layout, records):
    root.mkdir()
    if layout == "single_jsonl":
        (root / "events.jsonl").write_text(
            "".join(json.dumps(item, sort_keys=True) + "\n" for item in records),
            encoding="utf-8",
        )
    elif layout == "per_job_jsonl":
        grouped = {}
        for item in records:
            grouped.setdefault(item["job_id"], []).append(item)
        for job_id, group in grouped.items():
            (root / f"{job_id}.jsonl").write_text(
                "".join(json.dumps(item, sort_keys=True) + "\n" for item in group),
                encoding="utf-8",
            )
    else:
        for item in records:
            job_dir = root / item["job_id"]
            job_dir.mkdir(exist_ok=True)
            (job_dir / f"{item['event_id']}.json").write_text(
                json.dumps(item, sort_keys=True) + "\n", encoding="utf-8"
            )


def read_records(paths, job_id=None):
    found = 0
    for path in paths:
        for line in path.read_text(encoding="utf-8").splitlines():
            item = json.loads(line)
            if job_id is None or item["job_id"] == job_id:
                found += 1
    return found


def timed_read(paths, job_id=None):
    samples = []
    result = None
    for _ in range(3):
        start = time.perf_counter()
        result = read_records(paths, job_id)
        samples.append((time.perf_counter() - start) * 1_000)
    return result, round(statistics.median(samples), 2)


def measure(count):
    records = list(events(count))
    output = []
    with tempfile.TemporaryDirectory(prefix="tracker-v3-event-layout-") as tmp:
        for layout in ("single_jsonl", "per_job_jsonl", "per_event_json"):
            root = Path(tmp) / layout
            start = time.perf_counter()
            write_layout(root, layout, records)
            write_ms = round((time.perf_counter() - start) * 1_000, 2)
            paths = list(root.rglob("*.json")) if layout == "per_event_json" else list(root.iterdir())
            if layout == "per_job_jsonl":
                target_paths = [root / "job-0001.jsonl"]
            elif layout == "per_event_json":
                target_paths = list((root / "job-0001").iterdir())
            else:
                target_paths = paths
            total, scan_ms = timed_read(paths)
            selected, lookup_ms = timed_read(target_paths, "job-0001")
            assert total == count and selected == count // JOB_COUNT
            output.append(
                {
                    "events": count,
                    "layout": layout,
                    "files": len(paths),
                    "bytes": sum(path.stat().st_size for path in paths),
                    "write_ms": write_ms,
                    "scan_ms": scan_ms,
                    "lookup_ms": lookup_ms,
                }
            )
    return output


if __name__ == "__main__":
    for size in SIZES:
        for result in measure(size):
            print(json.dumps(result, sort_keys=True))
