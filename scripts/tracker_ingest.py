"""Raw-batch ingest: classify, dedupe against canonical data, and stage the
result as one atomic dataset transaction.

docs/agent-write-path-plan-2026-09-07.md, Э10.
"""

import json
import sys
from dataclasses import dataclass

try:  # Direct CLI execution places scripts/ on sys.path.
    from tracker_schema import (
        INGEST_RESOLUTION_DECISIONS,
        INGEST_RESOLUTION_VERSION,
        SOURCES,
        SOURCES_ALLOWING_SHARED_DISCOVERY_URLS,
        SourceReferenceConflict,
        norm,
    )
    from tracker_validate import (
        COMPANY_NOISE,
        ROLE_NOISE,
        norm_url,
        similarity,
        validate_dataset,
        without_noise,
    )
    from tracker_write import (
        apply_dataset_transaction,
        build_add_row,
        build_source_reference,
        load_for_write,
        prepare_source_reference,
    )
except ModuleNotFoundError:  # Unit tests may import this module as scripts.tracker_ingest.
    from scripts.tracker_schema import (
        INGEST_RESOLUTION_DECISIONS,
        INGEST_RESOLUTION_VERSION,
        SOURCES,
        SOURCES_ALLOWING_SHARED_DISCOVERY_URLS,
        SourceReferenceConflict,
        norm,
    )
    from scripts.tracker_validate import (
        COMPANY_NOISE,
        ROLE_NOISE,
        norm_url,
        similarity,
        validate_dataset,
        without_noise,
    )
    from scripts.tracker_write import (
        apply_dataset_transaction,
        build_add_row,
        build_source_reference,
        load_for_write,
        prepare_source_reference,
    )


@dataclass
class IngestPlan:
    batch_id: str | None
    resolution_path: str | None
    resolutions_used: int
    rows: list
    source_rows: list
    outcomes: list
    summary: dict
    errors: list
    warnings: list
    invalid: bool
    fuzzy: bool
    jobs_created: int
    source_references_created: int
    expected_revisions: dict


def ingest_job_values(rows, fields, decision_reason="", next_action=""):
    """Build an unverified canonical job from a normalized raw record."""
    row = build_add_row(
        rows,
        {
            **fields,
            "decision_reason": decision_reason,
        },
    )
    row["next_action"] = next_action
    row["next_action_date"] = ""
    return row


def add_ingest_reference(source_rows, job_id, fields):
    reference = build_source_reference(job_id, fields, fields["found_at"])
    reference, created = prepare_source_reference(source_rows, reference)
    if created:
        source_rows.append(reference)
    return reference, created


def ingest_summary(outcomes):
    summary = {"input": len(outcomes), "invalid": 0, "noise": 0, "skipped": 0, "duplicates": 0, "pending": 0}
    mapping = {
        "invalid": "invalid",
        "noise": "noise",
        "skipped": "skipped",
        "duplicate": "duplicates",
        "pending": "pending",
    }
    for outcome in outcomes:
        summary[mapping[outcome["outcome"]]] += 1
    return summary


def load_ingest_resolutions(path, batch_id):
    """Read explicit fuzzy decisions without ever changing the raw batch."""
    if path is None:
        return {}, []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        return {}, [f"resolution {path}: не удалось прочитать JSON: {error}"]

    errors = []
    if not isinstance(payload, dict):
        return {}, [f"resolution {path}: ожидается JSON object"]
    expected_fields = {"version", "batch_id", "resolutions"}
    if set(payload) != expected_fields:
        errors.append(f"resolution {path}: поля должны быть ровно {', '.join(sorted(expected_fields))}")
    if payload.get("version") != INGEST_RESOLUTION_VERSION:
        errors.append(f"resolution {path}: version должен быть {INGEST_RESOLUTION_VERSION}")
    if payload.get("batch_id") != batch_id:
        errors.append(f"resolution {path}: batch_id не совпадает с входным batch")
    entries = payload.get("resolutions")
    if not isinstance(entries, list):
        errors.append(f"resolution {path}: resolutions должен быть массивом")
        return {}, errors

    decisions = {}
    for index, entry in enumerate(entries, start=1):
        label = f"resolution {path} #{index}"
        if not isinstance(entry, dict) or set(entry) != {"line", "candidate", "decision"}:
            errors.append(f"{label}: поля должны быть ровно candidate, decision, line")
            continue
        line = entry["line"]
        if not isinstance(line, int) or isinstance(line, bool) or line <= 0:
            errors.append(f"{label}: line должен быть положительным целым числом")
            continue
        if line in decisions:
            errors.append(f"{label}: line {line} указан повторно")
            continue
        decision = entry["decision"]
        if decision not in INGEST_RESOLUTION_DECISIONS:
            errors.append(f"{label}: decision должен быть separate или duplicate")
            continue
        candidate = entry["candidate"]
        if not isinstance(candidate, dict):
            errors.append(f"{label}: candidate должен быть object")
            continue
        if set(candidate) == {"line"}:
            candidate_line = candidate["line"]
            if not isinstance(candidate_line, int) or isinstance(candidate_line, bool) or candidate_line <= 0:
                errors.append(f"{label}: candidate.line должен быть положительным целым числом")
                continue
            candidate_value = {"line": candidate_line}
        elif set(candidate) == {"job_id"}:
            job_id = candidate["job_id"]
            if not isinstance(job_id, str) or not job_id:
                errors.append(f"{label}: candidate.job_id должен быть непустой строкой")
                continue
            candidate_value = {"job_id": job_id}
        else:
            errors.append(f"{label}: candidate должен содержать ровно line или job_id")
            continue
        decisions[line] = {"decision": decision, "candidate": candidate_value}
    return (decisions if not errors else {}), errors


def resolution_candidate_id(resolution, candidates, job_lines):
    """Resolve a sidecar candidate identity against the current deterministic plan."""
    if "job_id" in resolution["candidate"]:
        target_id = resolution["candidate"]["job_id"]
    else:
        target_line = resolution["candidate"]["line"]
        target_id = next(
            (candidate["id"] for candidate in candidates if job_lines.get(candidate["id"]) == target_line),
            None,
        )
    if target_id not in {candidate["id"] for candidate in candidates}:
        return None
    return target_id


def plan_ingest(path, resolution_path=None):
    """Classify an immutable raw batch without changing canonical files."""
    try:  # Direct CLI execution places scripts/ on sys.path.
        from ingestion import (
            deterministic_duplicate,
            fuzzy_candidates,
            load_batch,
            normalize_record,
            relevance_or_hard_filter,
        )
    except ModuleNotFoundError:  # Unit tests may import this module as scripts.jobs.
        from scripts.ingestion import (
            deterministic_duplicate,
            fuzzy_candidates,
            load_batch,
            normalize_record,
            relevance_or_hard_filter,
        )

    batch = load_batch(path)
    resolutions, resolution_errors = load_ingest_resolutions(resolution_path, batch["batch_id"])
    rows, source_rows, expected_revisions = load_for_write()
    rows = [dict(row) for row in rows]
    source_rows = [dict(row) for row in source_rows]
    original_job_count = len(rows)
    original_reference_count = len(source_rows)
    outcomes = []
    errors = [*batch["errors"], *resolution_errors]
    source_references_created = 0
    fuzzy = False
    resolutions_used = set()
    job_lines = {}

    for entry in batch["entries"]:
        line_number = entry["line"]
        if entry["errors"]:
            outcomes.append(
                {
                    "line": line_number,
                    "outcome": "invalid",
                    "reason": "raw_validation",
                    "errors": entry["errors"],
                }
            )
            continue
        record = entry["record"]
        fields = normalize_record(record)
        if fields["source"] not in SOURCES:
            outcomes.append(
                {
                    "line": line_number,
                    "outcome": "invalid",
                    "reason": "canonical_source_unknown",
                    "errors": [
                        f"line {line_number}: source={fields['source']!r} не входит в canonical source enum"
                    ],
                }
            )
            continue

        relevance, filter_reason = relevance_or_hard_filter(record, norm(fields["role"]))
        if relevance == "noise":
            outcomes.append({"line": line_number, "outcome": "noise", "reason": filter_reason})
            continue

        duplicate = deterministic_duplicate(
            fields,
            rows,
            source_rows,
            norm,
            norm_url,
            shared_source_url_sources=SOURCES_ALLOWING_SHARED_DISCOVERY_URLS,
        )
        if duplicate:
            job_id, reason = duplicate
            if line_number in resolutions:
                resolutions_used.add(line_number)
            try:
                _reference, created = add_ingest_reference(source_rows, job_id, fields)
            except SourceReferenceConflict as error:
                outcomes.append(
                    {
                        "line": line_number,
                        "outcome": "invalid",
                        "reason": "source_reference_conflict",
                        "errors": [f"line {line_number}: {error.message}"],
                    }
                )
                continue
            source_references_created += int(created)
            outcomes.append(
                {
                    "line": line_number,
                    "outcome": "duplicate",
                    "reason": reason,
                    "job_id": job_id,
                    "source_reference_created": created,
                }
            )
            continue

        if relevance == "skipped":
            row = ingest_job_values(rows, fields, decision_reason=filter_reason)
            try:
                _reference, created = add_ingest_reference(source_rows, row["id"], fields)
            except SourceReferenceConflict as error:
                outcomes.append(
                    {
                        "line": line_number,
                        "outcome": "invalid",
                        "reason": "source_reference_conflict",
                        "errors": [f"line {line_number}: {error.message}"],
                    }
                )
                continue
            rows.append(row)
            job_lines[row["id"]] = line_number
            source_references_created += int(created)
            outcomes.append(
                {
                    "line": line_number,
                    "outcome": "skipped",
                    "reason": filter_reason,
                    "job_id": row["id"],
                }
            )
            continue

        candidates = fuzzy_candidates(
            fields,
            rows,
            without_noise,
            similarity,
            COMPANY_NOISE,
            ROLE_NOISE,
        )
        resolved_separate = False
        if candidates:
            resolution = resolutions.get(line_number)
            if resolution is None:
                fuzzy = True
                outcomes.append(
                    {
                        "line": line_number,
                        "outcome": "pending",
                        "reason": "fuzzy_duplicate_requires_resolution",
                        "candidates": candidates,
                    }
                )
                continue
            target_id = resolution_candidate_id(resolution, candidates, job_lines)
            if target_id is None:
                outcomes.append(
                    {
                        "line": line_number,
                        "outcome": "invalid",
                        "reason": "fuzzy_resolution_candidate_mismatch",
                        "errors": [
                            f"line {line_number}: resolution candidate не совпадает с fuzzy candidate"
                        ],
                    }
                )
                continue
            resolutions_used.add(line_number)
            if resolution["decision"] == "duplicate":
                try:
                    _reference, created = add_ingest_reference(source_rows, target_id, fields)
                except SourceReferenceConflict as error:
                    outcomes.append(
                        {
                            "line": line_number,
                            "outcome": "invalid",
                            "reason": "source_reference_conflict",
                            "errors": [f"line {line_number}: {error.message}"],
                        }
                    )
                    continue
                source_references_created += int(created)
                outcomes.append(
                    {
                        "line": line_number,
                        "outcome": "duplicate",
                        "reason": "fuzzy_resolution",
                        "resolution": "duplicate",
                        "job_id": target_id,
                        "source_reference_created": created,
                    }
                )
                continue
            resolved_separate = True

        row = ingest_job_values(rows, fields, next_action="verify first-party")
        try:
            _reference, created = add_ingest_reference(source_rows, row["id"], fields)
        except SourceReferenceConflict as error:
            outcomes.append(
                {
                    "line": line_number,
                    "outcome": "invalid",
                    "reason": "source_reference_conflict",
                    "errors": [f"line {line_number}: {error.message}"],
                }
            )
            continue
        rows.append(row)
        job_lines[row["id"]] = line_number
        source_references_created += int(created)
        outcome = {
            "line": line_number,
            "outcome": "pending",
            "reason": "verify_first_party",
            "job_id": row["id"],
        }
        if resolved_separate:
            outcome["resolution"] = "separate"
        outcomes.append(outcome)

    summary = ingest_summary(outcomes)
    for line_number in sorted(set(resolutions) - resolutions_used):
        errors.append(f"resolution line {line_number}: не применима к fuzzy candidate в этом batch")
    invalid = bool(errors) or bool(summary["invalid"])
    validation_errors, warnings = validate_dataset(rows, source_rows)
    if validation_errors:
        invalid = True
        errors.extend(validation_errors)
    return IngestPlan(
        batch_id=batch["batch_id"],
        resolution_path=str(resolution_path) if resolution_path else None,
        resolutions_used=len(resolutions_used),
        rows=rows,
        source_rows=source_rows,
        outcomes=outcomes,
        summary=summary,
        errors=errors,
        warnings=warnings,
        invalid=invalid,
        fuzzy=fuzzy,
        jobs_created=len(rows) - original_job_count,
        source_references_created=source_references_created or len(source_rows) - original_reference_count,
        expected_revisions=expected_revisions,
    )


def apply_ingest_plan(plan):
    if not plan.jobs_created and not plan.source_references_created:
        return {"jobs_created": 0, "source_references_created": 0, "application_cards_created": 0}
    apply_dataset_transaction(plan.rows, plan.source_rows, expected_revisions=plan.expected_revisions)
    return {
        "jobs_created": plan.jobs_created,
        "source_references_created": plan.source_references_created,
        "application_cards_created": 0,
    }


def ingest_payload(plan, mode, applied=None, error=None):
    return {
        "ok": error is None,
        "command": "ingest",
        "mode": mode,
        "batch_id": plan.batch_id,
        "resolution": {
            "path": plan.resolution_path,
            "used": plan.resolutions_used,
        }
        if plan.resolution_path
        else None,
        "summary": plan.summary,
        "outcomes": plan.outcomes,
        "errors": plan.errors,
        "warnings": plan.warnings,
        "applied": applied,
        "error": error,
    }


def print_ingest_text(payload):
    print(f"batch_id: {payload['batch_id']}")
    for outcome in payload["outcomes"]:
        print(f"line {outcome['line']}: {outcome['outcome']} — {outcome['reason']}")
    summary = payload["summary"]
    print(
        "summary: "
        + ", ".join(
            f"{key}={summary[key]}"
            for key in ("input", "invalid", "noise", "skipped", "duplicates", "pending")
        )
    )
    for error in payload["errors"]:
        print(f"error: {error}", file=sys.stderr)
