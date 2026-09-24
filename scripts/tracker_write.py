"""Mutating write-path operations: add/set/status/screen/verify and the
atomic multi-file dataset transaction they all go through.

docs/agent-write-path-plan-2026-09-07.md, Э10.
"""

import csv
import os
import re
import tempfile
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from io import StringIO
from pathlib import Path

try:  # Direct CLI execution places scripts/ on sys.path.
    from tracker_time import business_date
except ModuleNotFoundError:  # Unit tests may import this module as scripts.tracker_write.
    from scripts.tracker_time import business_date

try:
    from tracker_transaction import StaleRevision, digest, locked, publish, recover_locked
except ModuleNotFoundError:
    from scripts.tracker_transaction import StaleRevision, digest, locked, publish, recover_locked

try:  # Direct CLI execution places scripts/ on sys.path.
    from tracker_paths import PATHS
    from tracker_schema import (
        ADD_APPLICATION_STATUSES,
        APPLICATION_STATUSES,
        ENUMS,
        FIELDS,
        JOB_SOURCE_FIELDS,
        LEVELS,
        LISTING_STATUSES,
        NEEDS_APPLIED_AT,
        PRE_APPLICATION_STATUSES,
        REASONS,
        REMOTE,
        RESPONDED_APPLICATION_STATUSES,
        SCREEN_REASONS,
        SET_PROTECTED,
        SOURCES,
        SOURCES_ALLOWING_SHARED_DISCOVERY_URLS,
        SOURCES_WITHOUT_EXTERNAL_REFERENCE,
        STAGES,
        SourceReferenceConflict,
        TERMINAL_APPLICATION_STATUSES,
        UnresolvedDuplicate,
        VERIFICATION,
        VERIFY_ENRICHMENT_FIELDS,
        ValidationError,
        clean_value,
        die,
        find,
        next_id,
        slug,
    )
    from tracker_validate import (
        ensure_dataset_valid,
        find_duplicate_candidates,
        load,
        load_job_sources,
        norm_url,
        validate_dataset,
    )
    from tracker_render import (
        render_active_index,
        render_keys_index,
        render_known_index,
        render_tracker_markdown,
        tracker_application_cards,
        tracker_payload,
    )
except ModuleNotFoundError:  # Unit tests may import this module as scripts.tracker_write.
    from scripts.tracker_paths import PATHS
    from scripts.tracker_schema import (
        ADD_APPLICATION_STATUSES,
        APPLICATION_STATUSES,
        ENUMS,
        FIELDS,
        JOB_SOURCE_FIELDS,
        LEVELS,
        LISTING_STATUSES,
        NEEDS_APPLIED_AT,
        PRE_APPLICATION_STATUSES,
        REASONS,
        REMOTE,
        RESPONDED_APPLICATION_STATUSES,
        SCREEN_REASONS,
        SET_PROTECTED,
        SOURCES,
        SOURCES_ALLOWING_SHARED_DISCOVERY_URLS,
        SOURCES_WITHOUT_EXTERNAL_REFERENCE,
        STAGES,
        SourceReferenceConflict,
        TERMINAL_APPLICATION_STATUSES,
        UnresolvedDuplicate,
        VERIFICATION,
        VERIFY_ENRICHMENT_FIELDS,
        ValidationError,
        clean_value,
        die,
        find,
        next_id,
        slug,
    )
    from scripts.tracker_validate import (
        ensure_dataset_valid,
        find_duplicate_candidates,
        load,
        load_job_sources,
        norm_url,
        validate_dataset,
    )
    from scripts.tracker_render import (
        render_active_index,
        render_keys_index,
        render_known_index,
        render_tracker_markdown,
        tracker_application_cards,
        tracker_payload,
    )


@dataclass
class AddPlan:
    rows: list
    source_rows: list
    row: dict
    warnings: list
    app_path: Path | None
    app_body: str | None
    source_reference: dict | None
    source_reference_created: bool
    expected_revisions: dict
    app_revision: str | None


def today():
    return business_date().isoformat()


def build_add_row(rows: list, values: dict) -> dict:
    company = clean_value(values.get("company")).strip()
    role = clean_value(values.get("role")).strip()
    source = clean_value(values.get("source")).strip()
    if not company or not role or not source:
        raise ValidationError(
            "company, role and source are required to create a job",
            cli_hint_ru="company, role и source обязательны при создании вакансии",
        )
    if source not in SOURCES:
        raise ValidationError(
            f"source: {source!r} is not a recognized value",
            code="bad_enum_value",
            field="source",
            allowed=sorted(SOURCES),
            cli_hint_ru=f"source: недопустимое значение {source!r}",
        )
    application_status = clean_value(values.get("application_status") or "not_started")
    listing_status = clean_value(values.get("listing_status") or "unknown")
    first_party_verified = clean_value(values.get("first_party_verified") or "unknown")
    apply_verified = clean_value(values.get("apply_verified") or "unknown")
    level = clean_value(values.get("level") or "Unknown")
    remote_policy = clean_value(values.get("remote_policy") or "Unclear")
    decision_reason = clean_value(values.get("decision_reason"))
    if application_status not in ADD_APPLICATION_STATUSES:
        raise ValidationError(
            f"application_status: {application_status!r} is not valid for add",
            code="bad_enum_value",
            field="application_status",
            allowed=sorted(ADD_APPLICATION_STATUSES),
            cli_hint_ru=f"application_status: недопустимое значение {application_status!r} для add",
        )
    for key, value, allowed in (
        ("listing_status", listing_status, LISTING_STATUSES),
        ("first_party_verified", first_party_verified, VERIFICATION),
        ("apply_verified", apply_verified, VERIFICATION),
        ("level", level, LEVELS),
        ("remote_policy", remote_policy, REMOTE),
    ):
        if value not in allowed:
            raise ValidationError(
                f"{key}: {value!r} is not a recognized enum member",
                code="bad_enum_value",
                field=key,
                allowed=sorted(allowed),
                cli_hint_ru=f"{key}: недопустимое значение {value!r}",
            )
    if decision_reason and decision_reason not in REASONS:
        raise ValidationError(
            f"decision_reason: {decision_reason!r} is not a recognized value",
            code="bad_enum_value",
            field="decision_reason",
            allowed=sorted(REASONS),
            cli_hint_ru=f"decision_reason: недопустимое значение {decision_reason!r}",
        )
    notes = clean_value(values.get("notes"))
    identifier = next_id(rows)
    verification_touched = (
        listing_status != "unknown" or first_party_verified != "unknown" or apply_verified != "unknown"
    )
    row = {key: "" for key in FIELDS}
    row.update(
        {
            "id": identifier,
            "application_status": application_status,
            "listing_status": listing_status,
            "company": company,
            "role": role,
            "level": level,
            "original_url": clean_value(values.get("original_url")),
            "source_url": clean_value(values.get("source_url")),
            "source": source,
            "location": clean_value(values.get("location")),
            "remote_policy": remote_policy,
            "stack": clean_value(values.get("stack")),
            "salary": clean_value(values.get("salary")) or "Unknown",
            "posted_at": clean_value(values.get("posted_at")),
            "found_at": clean_value(values.get("found_at")) or today(),
            "match_score": clean_value(values.get("match_score")),
            "stage_reached": "None",
            "decision_reason": decision_reason,
            "first_party_verified": first_party_verified,
            "apply_verified": apply_verified,
            "verified_at": today() if verification_touched else "",
            "last_update": today(),
            "notes": notes,
        }
    )
    return row


def build_source_reference(job_id: str, values: dict, default_found_at: str) -> dict:
    source = clean_value(values.get("source")).strip()
    source_url = clean_value(values.get("source_url")).strip()
    source_job_id = clean_value(values.get("source_job_id")).strip()
    found_at = clean_value(values.get("found_at")).strip() or default_found_at
    if not source:
        raise ValidationError(
            "source is required for a source reference",
            cli_hint_ru="source обязателен для source reference",
        )
    if source not in SOURCES:
        raise ValidationError(
            f"source: {source!r} is not a recognized value",
            code="bad_enum_value",
            field="source",
            allowed=sorted(SOURCES),
            cli_hint_ru=f"source: недопустимое значение {source!r}",
        )
    if not source_url and not source_job_id:
        raise ValidationError(
            "an external source needs source_url or source_job_id",
            agent_hint="include source_url or source_job_id in args",
            cli_hint_ru="для внешнего источника нужен --source-url или --source-job-id",
        )
    return {
        "job_id": job_id,
        "source": source,
        "source_url": source_url,
        "source_job_id": source_job_id,
        "found_at": found_at,
    }


def prepare_source_reference(source_rows: list, reference: dict, force: bool = False) -> tuple[dict, bool]:
    source = reference["source"]
    source_url = reference["source_url"]
    source_job_id = reference["source_job_id"]
    if source_job_id:
        for existing in source_rows:
            if (existing["source"], existing["source_job_id"]) == (source, source_job_id):
                if existing["job_id"] == reference["job_id"]:
                    return existing, False
                raise SourceReferenceConflict(
                    f"source + source_job_id уже принадлежат {existing['job_id']}",
                    existing,
                    message_en=f"source + source_job_id already belong to {existing['job_id']}",
                )
    if source_url:
        normalized = norm_url(source_url)
        for existing in source_rows:
            if existing["source_url"] and norm_url(existing["source_url"]) == normalized:
                if existing["job_id"] == reference["job_id"] and existing["source"] == source:
                    return existing, False
                if (
                    source in SOURCES_ALLOWING_SHARED_DISCOVERY_URLS
                    and existing["source"] == source
                    and source_job_id
                    and existing["source_job_id"]
                    and existing["source_job_id"] != source_job_id
                ):
                    continue
                if not force:
                    raise SourceReferenceConflict(
                        f"source_url уже принадлежит {existing['job_id']}; используйте --force для shared discovery URL",
                        existing,
                        message_en=f"source_url already belongs to {existing['job_id']}; "
                        "retry with force=true if this is a separate shared discovery URL",
                    )
    return reference, True


def source_reference_payload(reference, created):
    return {"reference": reference, "created": created}


def should_create_application_card(row, no_file):
    return not no_file and not (row["application_status"] == "not_started" and row["decision_reason"])


APPLICATION_CARD_FRONT_MATTER_FIELDS = (
    "id",
    "company",
    "role",
    "original_url",
    "verified_at",
    "listing_status",
    "first_party_verified",
    "apply_verified",
)


def sync_application_card_front_matter(body, row, app_path):
    """Update current fields and add fields missing from a legacy card."""
    lines = body.splitlines(keepends=True)
    if not lines or lines[0].rstrip("\r\n") != "---":
        die(f"{app_path}: отсутствует начало front matter")
    closing_index = next(
        (index for index, line in enumerate(lines[1:], start=1) if line.rstrip("\r\n") == "---"),
        None,
    )
    if closing_index is None:
        die(f"{app_path}: отсутствует конец front matter")

    missing = []
    for key in APPLICATION_CARD_FRONT_MATTER_FIELDS:
        matches = [
            index for index in range(1, closing_index) if re.match(rf"^{re.escape(key)}\s*:", lines[index])
        ]
        if len(matches) > 1:
            die(f"{app_path}: front matter поле {key} указано несколько раз")
        replacement = f"{key}: {row[key]}\n"
        if matches:
            lines[matches[0]] = replacement
        else:
            missing.append(replacement)

    if missing:
        lines[closing_index:closing_index] = missing
    return "".join(lines)


def application_card_path(row):
    return PATHS.apps_dir / f"{row['id']}-{slug(row['company'])}-{slug(row['role'])}.md"


def render_application_card(row, update_existing=False, *, with_revision=False):
    def result(path, body, revision):
        return (path, body, revision) if with_revision else (path, body)

    app_path = application_card_path(row)
    if app_path.exists():
        original_bytes = app_path.read_bytes()
        revision = digest(original_bytes)
        if not update_existing:
            return result(app_path, None, revision)
        original_body = original_bytes.decode("utf-8")
        body = sync_application_card_front_matter(original_body, row, app_path)
        return result(app_path, body if body != original_body else None, revision)
    if not PATHS.template_path.exists():
        die(f"не найден шаблон {PATHS.template_path}")
    body = (
        PATHS.template_path.read_text(encoding="utf-8")
        .replace("{{company}}", row["company"])
        .replace("{{role}}", row["role"])
    )
    body = sync_application_card_front_matter(body, row, PATHS.template_path)
    return result(app_path, body, None)


def prepare_add(values: dict, force: bool = False, no_file: bool = False) -> AddPlan:
    rows, source_rows, expected_revisions = load_for_write()
    company = clean_value(values.get("company")).strip()
    role = clean_value(values.get("role")).strip()
    original_url = clean_value(values.get("original_url"))
    candidates = find_duplicate_candidates(rows, company, role, original_url)
    if candidates and not force:
        raise UnresolvedDuplicate(candidates)
    row = build_add_row(rows, values)
    new_rows = [*rows, row]
    new_source_rows = list(source_rows)
    source_reference, source_reference_created = None, False
    source_job_id = clean_value(values.get("source_job_id")).strip()
    if row["source_url"] or source_job_id:
        candidate_reference = build_source_reference(row["id"], values, row["found_at"])
        source_reference, source_reference_created = prepare_source_reference(
            source_rows,
            candidate_reference,
            force=force,
        )
        if source_reference_created:
            new_source_rows.append(source_reference)
    elif row["source"] not in SOURCES_WITHOUT_EXTERNAL_REFERENCE:
        raise ValidationError(
            f"source={row['source']} requires source_url or source_job_id",
            agent_hint="include source_url or source_job_id in args",
            cli_hint_ru=f"source={row['source']} требует source_url или source_job_id",
        )
    app_path, app_body, app_revision = (None, None, None)
    if should_create_application_card(row, no_file):
        app_path, app_body, app_revision = render_application_card(row, with_revision=True)
    return AddPlan(
        rows=new_rows,
        source_rows=new_source_rows,
        row=row,
        warnings=ensure_dataset_valid(new_rows, new_source_rows, emit_warnings=False),
        app_path=app_path,
        app_body=app_body,
        source_reference=source_reference,
        source_reference_created=source_reference_created,
        expected_revisions=expected_revisions,
        app_revision=app_revision,
    )


def persist_add(plan: AddPlan) -> Path | None:
    application_writes = ((plan.app_path, plan.app_body, plan.app_revision),) if plan.app_body is not None else ()
    apply_dataset_transaction(
        plan.rows, plan.source_rows, application_writes, expected_revisions=plan.expected_revisions
    )
    return plan.app_path if plan.app_body is not None else None


def add_duplicate_source_reference(values, duplicate_of, force=False):
    rows, source_rows, expected_revisions = load_for_write()
    canonical_job = find(rows, duplicate_of)
    reference = build_source_reference(canonical_job["id"], values, today())
    reference, created = prepare_source_reference(source_rows, reference, force=force)
    new_source_rows = [*source_rows, reference] if created else source_rows
    warnings = ensure_dataset_valid(rows, new_source_rows, emit_warnings=False)
    if created:
        apply_dataset_transaction(rows, new_source_rows, expected_revisions=expected_revisions)
    return {
        "job": canonical_job,
        "warnings": warnings,
        "application_path": None,
        "duplicate_of": canonical_job["id"],
        "source_reference": source_reference_payload(reference, created),
    }


def add_job(
    values: dict, force: bool = False, duplicate_of: str | None = None, no_file: bool = False
) -> dict:
    if duplicate_of:
        return add_duplicate_source_reference(values, duplicate_of, force=force)
    plan = prepare_add(values, force=force, no_file=no_file)
    created_path = persist_add(plan)
    return {
        "job": plan.row,
        "warnings": plan.warnings,
        "application_path": created_path.relative_to(PATHS.root).as_posix() if created_path else None,
        "source_reference": source_reference_payload(plan.source_reference, plan.source_reference_created)
        if plan.source_reference
        else None,
    }


@contextmanager
def dataset_write_lock():
    """Share the v3 publisher lock and recover its interrupted transactions."""
    with locked(PATHS.root) as root:
        recover_locked(root)
        yield


def current_dataset_revisions():
    """Hash the two canonical inputs while the caller holds the dataset lock."""
    return {
        "jobs": digest(PATHS.csv_path.read_bytes()),
        "sources": digest(PATHS.job_sources_path.read_bytes()),
    }


def load_for_write():
    """Load one consistent base snapshot and its optimistic revisions."""
    with dataset_write_lock():
        revisions = current_dataset_revisions()
        return load(), load_job_sources(), revisions


def stage_csv(target, fields, rows):
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{target.stem}-ingest-", suffix=".csv", dir=target.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=fields, lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: row.get(key) or "" for key in fields} for row in rows)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def stage_text(target, body):
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{target.stem}-ingest-", suffix=target.suffix, dir=target.parent
    )
    temporary_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            file.write(body)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise
    return temporary_path


def backup_file(target):
    if not target.exists():
        return None
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f"{target.stem}-backup-", suffix=target.suffix, dir=target.parent
    )
    backup_path = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(target.read_bytes())
    except BaseException:
        backup_path.unlink(missing_ok=True)
        raise
    return backup_path


def csv_bytes(fields, rows):
    stream = StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: row.get(key) or "" for key in fields} for row in rows)
    return stream.getvalue().encode("utf-8")


def projected_artifacts(rows, source_rows, application_writes):
    """Build every generated view from the proposed canonical state."""
    card_paths = [path for path, _body, _revision in application_writes]
    cards = tracker_application_cards(rows, planned_paths=card_paths)
    markdown = render_tracker_markdown(tracker_payload(rows, source_rows, cards))
    return {
        PATHS.tracker_path: markdown.encode("utf-8"),
        PATHS.known_index_path: render_known_index(rows),
        PATHS.keys_index_path: render_keys_index(source_rows),
        PATHS.active_index_path: render_active_index(rows),
    }


def apply_dataset_transaction(
    rows: list, source_rows: list, application_writes: tuple = (), *, expected_revisions: dict
) -> None:
    """Replace an already validated dataset or restore every replaced file."""
    validation_errors, _warnings = validate_dataset(rows, source_rows)
    if validation_errors:
        raise ValidationError(
            "dataset transaction rejected by validation",
            cli_hint_ru="ingest transaction отклонена:\n  " + "\n  ".join(validation_errors),
        )
    writes = {
        "data/jobs.csv": csv_bytes(FIELDS, rows),
        "data/job_sources.csv": csv_bytes(JOB_SOURCE_FIELDS, source_rows),
    }
    expected = {
        "data/jobs.csv": expected_revisions["jobs"],
        "data/job_sources.csv": expected_revisions["sources"],
    }
    for path, body, revision in application_writes:
        relative = path.relative_to(PATHS.root).as_posix()
        writes[relative] = body.encode("utf-8")
        expected[relative] = revision
    for path, data in projected_artifacts(rows, source_rows, application_writes).items():
        relative = path.relative_to(PATHS.root).as_posix()
        writes[relative] = data
        expected[relative] = digest(path.read_bytes()) if path.exists() else None

    PATHS.index_dir.mkdir(parents=True, exist_ok=True)
    PATHS.tracker_path.parent.mkdir(parents=True, exist_ok=True)

    def validate_published(_root):
        post_errors, _post_warnings = validate_dataset(load(), load_job_sources())
        if post_errors:
            raise OSError("post-commit dataset validation failed: " + "; ".join(post_errors))

    failure_after = os.environ.get("JOBS_INGEST_FAIL_AFTER_REPLACE")
    kill_after = os.environ.get("JOBS_INGEST_KILL_AFTER_REPLACE")
    failure_after = int(failure_after) if failure_after and failure_after.isdecimal() else None
    kill_after = int(kill_after) if kill_after and kill_after.isdecimal() else None

    def fault(stage, index):
        count = index + 1 if index is not None else 0
        if failure_after is not None and count == failure_after and (
            (count == 0 and stage == "after_prepare") or stage == "after_replace"
        ):
            raise OSError("injected ingest replacement failure")
        if kill_after is not None and count == kill_after and (
            (count == 0 and stage == "after_prepare") or stage == "after_replace"
        ):
            os._exit(75)

    try:
        publish(PATHS.root, writes, expected, validate=validate_published, fault=fault)
    except StaleRevision as error:
        raise ValidationError(
            f"dataset or card changed after this operation was prepared: {error}",
            code="stale_operation",
            cli_hint_ru="данные или карточка изменились после подготовки операции; повторите её на свежем снимке",
        ) from error


def parse_field_assignments(pairs):
    assignments = []
    for pair in pairs:
        if "=" not in pair:
            die(f"ожидается field=value, получено: {pair}")
        key, value = pair.split("=", 1)
        assignments.append((key, value))
    return assignments


def apply_job_changes(row, assignments, stage=None, *, enforce_protected=True):
    """enforce_protected=False is only for internal callers (status_job) that have
    already run the human-confirmed lifecycle gate in apply_status_change."""
    if not assignments and not stage:
        raise ValidationError(
            "nothing to change: provide field=value and/or a stage",
            cli_hint_ru="нечего менять: укажите field=value и/или --stage",
        )
    verification_touched = False
    for key, raw_value in assignments:
        value = clean_value(raw_value)
        if key not in FIELDS:
            raise ValidationError(
                f"unknown field: {key}",
                code="unknown_args",
                field=key,
                cli_hint_ru=f"неизвестное поле: {key}",
            )
        if enforce_protected and key in SET_PROTECTED:
            raise ValidationError(
                f"field {key} is computed by the runner and cannot be set via field=value",
                field=key,
                cli_hint_ru=f"поле {key} управляется скриптом и не меняется через field=value",
            )
        if (
            key == "decision_reason"
            and value == "duplicate_listing"
            and row["decision_reason"] != "duplicate_listing"
        ):
            raise ValidationError(
                "duplicate_listing is created only by an add operation with duplicate_of set",
                field="decision_reason",
                cli_hint_ru="duplicate_listing создаётся только командой add --duplicate-of JOB_ID",
            )
        if key in ENUMS and value and value not in ENUMS[key]:
            raise ValidationError(
                f"{key}: {value!r} is not a recognized enum member",
                code="bad_enum_value",
                field=key,
                allowed=sorted(ENUMS[key]),
                cli_hint_ru=f"{key}: недопустимое значение {value!r}",
            )
        row[key] = value.replace("\n", " ")
        verification_touched = verification_touched or key in {
            "listing_status",
            "first_party_verified",
            "apply_verified",
        }
    if stage:
        if stage not in STAGES:
            raise ValidationError(
                f"{stage!r} is not a recognized stage",
                code="bad_enum_value",
                field="stage",
                allowed=list(STAGES),
                cli_hint_ru=f"недопустимая стадия: {stage}",
            )
        current = row["stage_reached"] or "None"
        if STAGES.index(stage) < STAGES.index(current):
            raise ValidationError(
                f"stage_reached cannot move backward: {current} -> {stage}",
                field="stage",
                cli_hint_ru=f"stage_reached нельзя понижать: {current} -> {stage}",
            )
        row["stage_reached"] = stage
        if (
            STAGES.index("Recruiter screen") <= STAGES.index(stage) <= STAGES.index("Final interview")
            and row["application_status"] == "applied"
        ):
            row["application_status"] = "interviewing"
        if stage == "Offer" and row["application_status"] in {"applied", "interviewing"}:
            row["application_status"] = "offer"
    if row["application_status"] in NEEDS_APPLIED_AT and not row["applied_at"]:
        row["applied_at"] = today()
    if row["application_status"] in NEEDS_APPLIED_AT and (row["stage_reached"] or "None") == "None":
        row["stage_reached"] = "Applied"
    if row["application_status"] == "offer":
        row["stage_reached"] = "Offer"
    if row["application_status"] in RESPONDED_APPLICATION_STATUSES and not row["response_at"]:
        row["response_at"] = today()
    if verification_touched:
        row["verified_at"] = today()
    row["last_update"] = today()
    return verification_touched


def set_job(job_id: str, assignments: list, stage: str | None = None) -> dict:
    rows, source_rows, expected_revisions = load_for_write()
    row = find(rows, job_id)
    apply_job_changes(row, assignments, stage=stage)
    warnings = ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    apply_dataset_transaction(rows, source_rows, expected_revisions=expected_revisions)
    return {"job": row, "warnings": warnings}


def validate_status_date(value, field):
    if value is None:
        return None
    value = clean_value(value).strip()
    if not value:
        raise ValidationError(
            f"status: {field} cannot be an empty date",
            code="bad_format",
            field=field,
            cli_hint_ru=f"status: {field} не может быть пустой датой",
        )
    try:
        parsed = datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        raise ValidationError(
            f"status: {field} must be YYYY-MM-DD",
            code="bad_format",
            field=field,
            cli_hint_ru=f"status: {field} должна быть YYYY-MM-DD",
        )
    if parsed > business_date():
        raise ValidationError(
            f"status: {field} cannot be in the future",
            code="bad_format",
            field=field,
            cli_hint_ru=f"status: {field} не может быть в будущем",
        )
    return value


def apply_status_change(
    row,
    *,
    application_status,
    stage=None,
    applied_at=None,
    response_at=None,
    decision_reason=None,
    next_action=None,
    next_action_date=None,
    cv_version=None,
    notes=None,
):
    """Record a user-confirmed lifecycle event without opening arbitrary set fields."""
    target = clean_value(application_status).strip()
    if target not in APPLICATION_STATUSES:
        raise ValidationError(
            f"status: {target!r} is not a recognized application_status",
            code="bad_enum_value",
            field="application_status",
            allowed=sorted(APPLICATION_STATUSES),
            cli_hint_ru=f"status: недопустимый application_status {target!r}",
        )
    if row["applied_at"] and target in PRE_APPLICATION_STATUSES:
        raise ValidationError(
            "status: an already-submitted application cannot move back to a pre-application state",
            field="application_status",
            cli_hint_ru="status: нельзя вернуть отправленную заявку в pre-application состояние",
        )
    if stage is not None:
        stage = clean_value(stage).strip()
        if stage not in STAGES:
            raise ValidationError(
                f"status: {stage!r} is not a recognized stage",
                code="bad_enum_value",
                field="stage",
                allowed=list(STAGES),
                cli_hint_ru=f"status: недопустимая стадия {stage!r}",
            )
    if target in PRE_APPLICATION_STATUSES and stage not in {None, "None"}:
        raise ValidationError(
            f"status: application_status={target} does not accept a post-application stage",
            field="stage",
            cli_hint_ru=f"status: application_status={target} не принимает post-application stage",
        )
    if target == "applied" and stage not in {None, "Applied"}:
        raise ValidationError(
            "status: application_status=applied accepts only stage=Applied",
            field="stage",
            cli_hint_ru="status: application_status=applied допускает только stage=Applied",
        )
    if target == "interviewing" and stage in {"None", "Applied", "Offer"}:
        raise ValidationError(
            "status: interviewing requires an interview stage",
            field="stage",
            cli_hint_ru="status: interviewing требует interview stage",
        )
    if target == "offer" and stage not in {None, "Offer"}:
        raise ValidationError(
            "status: application_status=offer requires stage=Offer",
            field="stage",
            cli_hint_ru="status: application_status=offer требует stage=Offer",
        )

    applied_at = validate_status_date(applied_at, "applied_at")
    response_at = validate_status_date(response_at, "response_at")
    if target in PRE_APPLICATION_STATUSES and (applied_at is not None or response_at is not None):
        raise ValidationError(
            "status: a pre-application state does not accept applied_at/response_at",
            cli_hint_ru="status: pre-application состояние не принимает applied_at/response_at",
        )
    if target == "applied" and response_at is not None:
        raise ValidationError(
            "status: application_status=applied does not accept response_at",
            field="response_at",
            cli_hint_ru="status: application_status=applied не принимает response_at",
        )
    if next_action_date is not None:
        next_action_date = clean_value(next_action_date).strip()
        if next_action_date:
            try:
                datetime.strptime(next_action_date, "%Y-%m-%d")
            except ValueError:
                raise ValidationError(
                    "status: next_action_date must be YYYY-MM-DD",
                    code="bad_format",
                    field="next_action_date",
                    cli_hint_ru="status: next_action_date должна быть YYYY-MM-DD",
                )

    effective_applied_at = applied_at or row["applied_at"]
    if target in NEEDS_APPLIED_AT and not effective_applied_at and target != "applied":
        raise ValidationError(
            f"status: moving to {target} without an existing application requires applied_at",
            field="applied_at",
            agent_hint="include an applied_at date in args",
            cli_hint_ru=f"status: переход в {target} без существующей заявки требует --applied-at",
        )
    effective_next_action = row["next_action"] if next_action is None else clean_value(next_action).strip()
    if target == "apply" and not effective_next_action:
        raise ValidationError(
            "status: application_status=apply requires next_action",
            field="next_action",
            agent_hint="include a non-empty next_action in args",
            cli_hint_ru="status: application_status=apply требует --next-action",
        )
    if target in TERMINAL_APPLICATION_STATUSES and (
        (next_action is not None and clean_value(next_action).strip())
        or (next_action_date is not None and next_action_date)
    ):
        raise ValidationError(
            f"status: application_status={target} does not accept a next step",
            field="next_action",
            cli_hint_ru=f"status: application_status={target} не принимает следующий шаг",
        )
    if next_action_date and (next_action is None or not clean_value(next_action).strip()):
        raise ValidationError(
            "status: next_action_date requires an explicit next_action",
            field="next_action_date",
            agent_hint="include a non-empty next_action in args",
            cli_hint_ru="status: next_action_date требует явный --next-action",
        )

    supplied_reason = None if decision_reason is None else clean_value(decision_reason).strip()
    if target == "ghosted":
        if supplied_reason not in {None, "no_response_timeout"}:
            raise ValidationError(
                "status: ghosted accepts only decision_reason=no_response_timeout",
                code="bad_enum_value",
                field="decision_reason",
                allowed=["no_response_timeout"],
                cli_hint_ru="status: ghosted допускает только decision_reason=no_response_timeout",
            )
        final_reason = "no_response_timeout"
    elif target == "withdrawn":
        if supplied_reason not in {None, "withdrawn_by_me"}:
            raise ValidationError(
                "status: withdrawn accepts only decision_reason=withdrawn_by_me",
                code="bad_enum_value",
                field="decision_reason",
                allowed=["withdrawn_by_me"],
                cli_hint_ru="status: withdrawn допускает только decision_reason=withdrawn_by_me",
            )
        final_reason = "withdrawn_by_me"
    else:
        if supplied_reason:
            raise ValidationError(
                f"status: decision_reason is not used for application_status={target}",
                field="decision_reason",
                cli_hint_ru=f"status: decision_reason не используется для application_status={target}",
            )
        final_reason = ""

    if target == "interviewing" and stage is None:
        current_stage = row["stage_reached"] or "None"
        if STAGES.index(current_stage) < STAGES.index("Recruiter screen"):
            stage = "Recruiter screen"
    elif target == "offer":
        stage = "Offer"

    assignments = [
        ("application_status", target),
        ("decision_reason", final_reason),
    ]
    if applied_at is not None:
        assignments.append(("applied_at", applied_at))
    if response_at is not None:
        assignments.append(("response_at", response_at))
    if cv_version is not None:
        assignments.append(("cv_version", clean_value(cv_version).strip()))
    if notes is not None:
        assignments.append(("notes", clean_value(notes).strip()))

    if target in TERMINAL_APPLICATION_STATUSES or (target == "applied" and next_action is None):
        assignments.extend((("next_action", ""), ("next_action_date", "")))
    else:
        if next_action is not None:
            assignments.append(("next_action", clean_value(next_action).strip()))
        if next_action_date is not None:
            assignments.append(("next_action_date", next_action_date))

    apply_job_changes(row, assignments, stage=stage, enforce_protected=False)
    return "status_changed"


def status_job(job_id: str, **values) -> dict:
    rows, source_rows, expected_revisions = load_for_write()
    row = find(rows, job_id)
    outcome = apply_status_change(row, **values)
    warnings = ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    application_path, application_body, application_revision = (None, None, None)
    if row["application_status"] in {"reviewing", "apply"} or row["applied_at"]:
        application_path, application_body, application_revision = render_application_card(
            row, update_existing=True, with_revision=True
        )
    application_writes = (
        ((application_path, application_body, application_revision),) if application_body is not None else ()
    )
    apply_dataset_transaction(rows, source_rows, application_writes, expected_revisions=expected_revisions)
    return {
        "job": row,
        "warnings": warnings,
        "outcome": outcome,
        "application_path": application_path.relative_to(PATHS.root).as_posix() if application_path else None,
    }


def apply_screen_decision(row, *, decision_reason, notes=None):
    """Record a pre-application screening decision without claiming verification."""
    decision_reason = clean_value(decision_reason).strip()
    if decision_reason not in SCREEN_REASONS:
        raise ValidationError(
            f"screen: {decision_reason!r} is not a recognized decision_reason",
            code="bad_enum_value",
            field="decision_reason",
            allowed=sorted(SCREEN_REASONS),
            cli_hint_ru=f"screen: недопустимая decision_reason {decision_reason!r}",
        )
    if row["application_status"] not in {"not_started", "reviewing", "apply"} or row["applied_at"]:
        raise ValidationError(
            "screen is allowed only before an application is actually submitted",
            cli_hint_ru="screen допустим только до фактической отправки заявки",
        )
    if notes is not None:
        row["notes"] = clean_value(notes).strip()
    if decision_reason == "other" and not row["notes"]:
        raise ValidationError(
            "screen decision_reason=other requires notes",
            field="notes",
            agent_hint="include non-empty notes in args",
            cli_hint_ru="screen decision_reason=other требует --notes",
        )
    row["application_status"] = "not_started"
    row["decision_reason"] = decision_reason
    row["next_action"] = ""
    row["next_action_date"] = ""
    row["last_update"] = today()
    return "screened_out"


def screen_job(job_id: str, *, decision_reason: str, notes: str | None = None) -> dict:
    rows, source_rows, expected_revisions = load_for_write()
    row = find(rows, job_id)
    outcome = apply_screen_decision(row, decision_reason=decision_reason, notes=notes)
    warnings = ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    apply_dataset_transaction(rows, source_rows, expected_revisions=expected_revisions)
    return {"job": row, "warnings": warnings, "outcome": outcome}


def apply_verify_enrichment(row, **values):
    """Set non-lifecycle facts gathered alongside a completed verification."""
    for key, raw_value in values.items():
        if key not in VERIFY_ENRICHMENT_FIELDS:
            raise ValueError(f"verify enrichment field is not allowed: {key}")
        if raw_value is None:
            continue
        value = clean_value(raw_value).strip()
        if key in ENUMS and value and value not in ENUMS[key]:
            raise ValidationError(
                f"{key}: {value!r} is not a recognized enum member",
                code="bad_enum_value",
                field=key,
                allowed=sorted(ENUMS[key]),
                cli_hint_ru=f"{key}: недопустимое значение {value!r}",
            )
        row[key] = value


def apply_verify_changes(
    row,
    *,
    listing_status,
    first_party_verified,
    apply_verified,
    original_url=None,
    decision_reason=None,
    notes=None,
    level=None,
    remote_policy=None,
    stack=None,
    salary=None,
    match_score=None,
    application_status=None,
    next_action=None,
    next_action_date=None,
):
    """Apply verification fields to an in-memory row and return its outcome."""
    if decision_reason == "duplicate_listing":
        raise ValidationError(
            "duplicate_listing is created only by an add operation with duplicate_of set",
            field="decision_reason",
            cli_hint_ru="duplicate_listing создаётся только командой add --duplicate-of JOB_ID",
        )
    if application_status is not None:
        application_status = clean_value(application_status).strip()
        if application_status != "apply":
            raise ValidationError(
                "verify may set application_status only to apply",
                code="bad_enum_value",
                field="application_status",
                allowed=["apply"],
                cli_hint_ru="verify может установить application_status только в apply",
            )
        next_action = clean_value(next_action or "").strip()
        if not next_action:
            raise ValidationError(
                "application_status=apply requires next_action",
                field="next_action",
                agent_hint="include a non-empty next_action in args",
                cli_hint_ru="application_status=apply требует --next-action",
            )
        if next_action_date is not None:
            next_action_date = clean_value(next_action_date).strip()
            try:
                datetime.strptime(next_action_date, "%Y-%m-%d")
            except ValueError:
                raise ValidationError(
                    "next_action_date must be YYYY-MM-DD",
                    code="bad_format",
                    field="next_action_date",
                    cli_hint_ru="--next-action-date должна иметь формат YYYY-MM-DD",
                )
    elif next_action is not None or next_action_date is not None:
        raise ValidationError(
            "next_action and next_action_date are allowed only with application_status=apply",
            cli_hint_ru="--next-action и --next-action-date допустимы только с --application-status apply",
        )
    if decision_reason and application_status is not None:
        raise ValidationError(
            "decision_reason cannot be combined with application_status=apply",
            field="decision_reason",
            cli_hint_ru="--decision-reason нельзя сочетать с --application-status apply",
        )
    if original_url is not None:
        row["original_url"] = clean_value(original_url).strip()
    if notes is not None:
        row["notes"] = clean_value(notes).strip()
    apply_verify_enrichment(
        row,
        level=level,
        remote_policy=remote_policy,
        stack=stack,
        salary=salary,
        match_score=match_score,
    )
    row["listing_status"] = listing_status
    row["first_party_verified"] = first_party_verified
    row["apply_verified"] = apply_verified
    row["verified_at"] = today()
    passed = listing_status == "open" and first_party_verified == "yes" and apply_verified == "yes"
    pre_application = row["application_status"] in {"not_started", "reviewing", "apply"}
    if decision_reason:
        if not pre_application:
            raise ValidationError(
                "decision_reason is allowed only before an application response",
                field="decision_reason",
                cli_hint_ru="--decision-reason допустим только до отклика",
            )
        row["application_status"] = "not_started"
        row["decision_reason"] = decision_reason
        row["next_action"] = ""
        row["next_action_date"] = ""
        outcome = "blocked"
    elif passed:
        if application_status == "apply":
            if not pre_application:
                raise ValidationError(
                    "application_status=apply is allowed only before an application is actually submitted",
                    field="application_status",
                    cli_hint_ru="application_status=apply допустим только до фактической отправки заявки",
                )
            row["application_status"] = "apply"
            row["next_action"] = next_action
            row["next_action_date"] = next_action_date or ""
            outcome = "ready_to_continue_application"
        else:
            if row["application_status"] == "not_started":
                row["application_status"] = "reviewing"
            if row["next_action"] == "verify first-party":
                row["next_action"] = ""
                row["next_action_date"] = ""
            outcome = "ready_for_review" if pre_application else "verified_after_application"
    elif pre_application:
        raise ValidationError(
            "a verification that did not pass requires decision_reason before an application response",
            field="decision_reason",
            agent_hint="include decision_reason in args",
            cli_hint_ru="для непрошедшей verification до отклика нужен --decision-reason",
        )
    else:
        outcome = "verified_after_application"
    row["last_update"] = today()
    return {"outcome": outcome, "passed": passed}


def prepare_verified_application_write(row, passed):
    """Sync an existing card's front matter on every verify, pass or fail.
    A new card is still only created once verification actually passes."""
    card_exists = application_card_path(row).exists()
    if not card_exists and not (passed and row["application_status"] in {"reviewing", "apply"}):
        return None, None, False, None
    application_path, application_body, application_revision = render_application_card(
        row, update_existing=True, with_revision=True
    )
    application_card_created = application_body is not None and not card_exists
    return application_path, application_body, application_card_created, application_revision


def verify_job(
    job_id: str,
    *,
    listing_status: str,
    first_party_verified: str,
    apply_verified: str,
    original_url: str | None = None,
    decision_reason: str | None = None,
    notes: str | None = None,
    level: str | None = None,
    remote_policy: str | None = None,
    stack: str | None = None,
    salary: str | None = None,
    match_score: str | None = None,
    application_status: str | None = None,
    next_action: str | None = None,
    next_action_date: str | None = None,
) -> dict:
    """Apply a completed first-party verification as one atomic dataset update."""
    rows, source_rows, expected_revisions = load_for_write()
    row = find(rows, job_id)
    change = apply_verify_changes(
        row,
        listing_status=listing_status,
        first_party_verified=first_party_verified,
        apply_verified=apply_verified,
        original_url=original_url,
        decision_reason=decision_reason,
        notes=notes,
        level=level,
        remote_policy=remote_policy,
        stack=stack,
        salary=salary,
        match_score=match_score,
        application_status=application_status,
        next_action=next_action,
        next_action_date=next_action_date,
    )
    warnings = ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    application_path, application_body, application_card_created, application_revision = prepare_verified_application_write(
        row,
        change["passed"],
    )
    application_writes = (
        ((application_path, application_body, application_revision),) if application_body is not None else ()
    )
    apply_dataset_transaction(rows, source_rows, application_writes, expected_revisions=expected_revisions)
    return {
        "job": row,
        "warnings": warnings,
        "outcome": change["outcome"],
        "application_path": application_path.relative_to(PATHS.root).as_posix() if application_path else None,
        "application_card_created": application_card_created,
    }
