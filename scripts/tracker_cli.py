"""argparse plumbing: type coercers, every `cmd_*` handler, and `main()`.

docs/agent-write-path-plan-2026-09-07.md, Э10. This is the only module that
talks to argparse or prints CLI-formatted output; everything it calls into
(validate/write/ingest/render) is usable without a CLI, which is exactly how
agent_operations.py and scripts/maintenance/*.py use it.
"""

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

try:  # Direct CLI execution places scripts/ on sys.path.
    from tracker_time import business_date
except ModuleNotFoundError:  # Unit tests may import this module as scripts.tracker_cli.
    from scripts.tracker_time import business_date

try:  # Direct CLI execution places scripts/ on sys.path.
    from tracker_paths import PATHS
    from tracker_schema import (
        ADD_APPLICATION_STATUSES,
        ADD_INPUT_FIELDS,
        ADD_REQUIRED_INPUT_FIELDS,
        APPLICATION_STATUSES,
        DEFAULT_STALE_DAYS,
        JobIdRange,
        LEVELS,
        LISTING_STATUSES,
        PRE_APPLICATION_REASONS,
        REASONS,
        REMOTE,
        SCREEN_REASONS,
        SOURCES,
        STAGES,
        SourceReferenceConflict,
        UnresolvedDuplicate,
        VERIFICATION,
        ValidationError,
        die,
    )
    from tracker_validate import (
        ensure_dataset_valid,
        find_fuzzy_duplicates,
        load,
        load_job_sources,
        print_duplicate_candidates,
        temporal_notices,
        validate_dataset,
    )
    from tracker_write import add_job, parse_field_assignments, screen_job, set_job, status_job, verify_job
    from tracker_ingest import apply_ingest_plan, ingest_payload, plan_ingest, print_ingest_text
    from tracker_render import (
        TODO_SECTION_ORDER,
        filter_todo_rows,
        render_active_index,
        render_keys_index,
        render_known_index,
        render_tracker_markdown,
        stale_entries,
        stats_payload,
        todo_sections,
        tracker_application_cards,
        tracker_payload,
        write_or_check_index_file,
        write_or_check_tracker,
    )
except ModuleNotFoundError:  # Unit tests may import this module as scripts.tracker_cli.
    from scripts.tracker_paths import PATHS
    from scripts.tracker_schema import (
        ADD_APPLICATION_STATUSES,
        ADD_INPUT_FIELDS,
        ADD_REQUIRED_INPUT_FIELDS,
        APPLICATION_STATUSES,
        DEFAULT_STALE_DAYS,
        JobIdRange,
        LEVELS,
        LISTING_STATUSES,
        PRE_APPLICATION_REASONS,
        REASONS,
        REMOTE,
        SCREEN_REASONS,
        SOURCES,
        STAGES,
        SourceReferenceConflict,
        UnresolvedDuplicate,
        VERIFICATION,
        ValidationError,
        die,
    )
    from scripts.tracker_validate import (
        ensure_dataset_valid,
        find_fuzzy_duplicates,
        load,
        load_job_sources,
        print_duplicate_candidates,
        temporal_notices,
        validate_dataset,
    )
    from scripts.tracker_write import (
        add_job,
        parse_field_assignments,
        screen_job,
        set_job,
        status_job,
        verify_job,
    )
    from scripts.tracker_ingest import apply_ingest_plan, ingest_payload, plan_ingest, print_ingest_text
    from scripts.tracker_render import (
        TODO_SECTION_ORDER,
        filter_todo_rows,
        render_active_index,
        render_keys_index,
        render_known_index,
        render_tracker_markdown,
        stale_entries,
        stats_payload,
        todo_sections,
        tracker_application_cards,
        tracker_payload,
        write_or_check_index_file,
        write_or_check_tracker,
    )


class JobsArgumentParser(argparse.ArgumentParser):
    """Argparse с едиными кодами завершения для CLI."""

    def error(self, message):
        self.print_usage(sys.stderr)
        die(message)


def positive_int(value):
    try:
        parsed = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("ожидается положительное целое число") from error
    if parsed <= 0:
        raise argparse.ArgumentTypeError("ожидается положительное целое число")
    return parsed


def iso_date_argument(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as error:
        raise argparse.ArgumentTypeError("ожидается дата YYYY-MM-DD") from error


def job_id_range_argument(value):
    match = re.fullmatch(r"job-(\d{4,}):job-(\d{4,})", value or "")
    if not match:
        raise argparse.ArgumentTypeError("ожидается диапазон job-NNNN:job-NNNN")
    start, end = (int(part) for part in match.groups())
    if start > end:
        raise argparse.ArgumentTypeError("начало id-range не может быть больше конца")
    return JobIdRange(start, end)


def print_json(payload):
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))


def cmd_ingest(args):
    plan = plan_ingest(args.path, args.resolutions)
    mode = "dry_run" if args.dry_run else "apply"
    error, exit_code, applied = None, 0, None
    if plan.invalid:
        error, exit_code = "invalid_batch", 1
    elif plan.fuzzy:
        error, exit_code = "fuzzy_duplicate_requires_resolution", 2
    elif not args.dry_run:
        try:
            applied = apply_ingest_plan(plan)
        except OSError as apply_error:
            plan.errors.append(f"ingest transaction не применена: {apply_error}")
            error, exit_code = "apply_failed", 1
    payload = ingest_payload(plan, mode, applied=applied, error=error)
    if args.format == "json":
        print_json(payload)
    else:
        print_ingest_text(payload)
    if exit_code:
        raise SystemExit(exit_code)


def add_values_from_args(args):
    return {
        "company": args.company,
        "role": args.role,
        "source": args.source,
        "application_status": args.application_status,
        "listing_status": args.listing_status,
        "first_party_verified": args.first_party_verified,
        "apply_verified": args.apply_verified,
        "level": args.level,
        "remote_policy": args.remote_policy,
        "original_url": args.original_url,
        "source_url": args.source_url,
        "source_job_id": args.source_job_id,
        "location": args.location,
        "stack": args.stack,
        "salary": args.salary,
        "posted_at": args.posted_at,
        "found_at": args.found_at,
        "match_score": args.match_score,
        "decision_reason": args.decision_reason,
        "notes": args.notes,
    }


def parse_add_json(raw, source_name):
    try:
        values = json.loads(raw)
    except json.JSONDecodeError as error:
        die(f"{source_name}: некорректный JSON: {error.msg}")
    if not isinstance(values, dict):
        die(f"{source_name}: ожидается один JSON object")
    unknown = sorted(set(values) - ADD_INPUT_FIELDS)
    if unknown:
        die(f"{source_name}: неизвестные или управляемые поля JSON: {', '.join(unknown)}")
    missing = sorted(key for key in ADD_REQUIRED_INPUT_FIELDS if not values.get(key))
    if missing:
        die(f"{source_name}: обязательные JSON-поля: {', '.join(missing)}")
    for key, value in values.items():
        if key == "match_score":
            valid_number = isinstance(value, (int, float)) and not isinstance(value, bool)
            if not isinstance(value, str) and not valid_number:
                die(f"{source_name}: match_score должен быть строкой или числом")
        elif not isinstance(value, str):
            die(f"{source_name}: {key} должен быть строкой")
    return values


def load_add_values(args):
    cli_values = add_values_from_args(args)
    if args.json_path or args.stdin:
        supplied = sorted(key for key, value in cli_values.items() if value is not None)
        if supplied:
            die("--json/--stdin нельзя совмещать с полями вакансии из CLI: " + ", ".join(supplied))
        if args.json_path:
            path = Path(args.json_path)
            try:
                raw = path.read_text(encoding="utf-8")
            except (OSError, UnicodeError) as error:
                die(f"не удалось прочитать JSON {path}: {error}")
            return parse_add_json(raw, str(path))
        return parse_add_json(sys.stdin.read(), "stdin")
    missing = sorted(key for key in ADD_REQUIRED_INPUT_FIELDS if not cli_values.get(key))
    if missing:
        die("для add без --json/--stdin обязательны: " + ", ".join(missing))
    return cli_values


def duplicate_candidates_payload(candidates):
    return [
        {
            "id": row["id"],
            "company": row["company"],
            "role": row["role"],
            "application_status": row["application_status"],
            "listing_status": row["listing_status"],
            "reason": reason,
        }
        for row, reason, _reason_en in candidates.values()
    ]


def cmd_add(args):
    try:
        result = add_job(
            load_add_values(args),
            force=args.force,
            duplicate_of=args.duplicate_of,
            no_file=args.no_file,
        )
    except UnresolvedDuplicate as error:
        if args.format == "json":
            print_json(
                {
                    "ok": False,
                    "command": "add",
                    "error": "unresolved_duplicate",
                    "candidates": duplicate_candidates_payload(error.candidates),
                }
            )
        else:
            print_duplicate_candidates(error.candidates)
        raise SystemExit(2)
    except SourceReferenceConflict as error:
        if args.format == "json":
            print_json(
                {
                    "ok": False,
                    "command": "add",
                    "error": "source_reference_conflict",
                    "message": error.message,
                    "existing": error.existing,
                }
            )
        else:
            print(f"source reference conflict: {error.message}")
            print("это отдельная reference -> повторите с --force")
        raise SystemExit(2)
    if args.format == "json":
        print_json({"ok": True, "command": "add", **result})
        return
    for warning in result["warnings"]:
        print(f"warn:  {warning}")
    if result.get("duplicate_of"):
        reference = result["source_reference"]
        state = "добавлена" if reference["created"] else "уже существует"
        print(
            f"{result['duplicate_of']}  source reference {state}: {reference['reference']['source_url'] or reference['reference']['source_job_id']}"
        )
        return
    if result["application_path"]:
        print(f"создан {result['application_path']}")
    row = result["job"]
    print(
        f"{row['id']}  {row['company']} — {row['role']}  [{row['application_status']}; {row['listing_status']}]"
    )


def cmd_set(args):
    result = set_job(args.id, parse_field_assignments(args.field), stage=args.stage)
    if args.format == "json":
        print_json({"ok": True, "command": "set", **result})
        return
    for warning in result["warnings"]:
        print(f"warn:  {warning}")
    row = result["job"]
    print(
        f"{row['id']}  application_status={row['application_status']}  listing_status={row['listing_status']}  stage={row['stage_reached']}"
    )


def cmd_status(args):
    result = status_job(
        args.id,
        application_status=args.application_status,
        stage=args.stage,
        applied_at=args.applied_at,
        response_at=args.response_at,
        decision_reason=args.decision_reason,
        next_action=args.next_action,
        next_action_date=args.next_action_date,
        cv_version=args.cv_version,
        notes=args.notes,
    )
    if args.format == "json":
        print_json({"ok": True, "command": "status", **result})
        return
    row = result["job"]
    print(f"{row['id']}  application_status={row['application_status']}  stage={row['stage_reached']}")


def cmd_screen(args):
    result = screen_job(args.id, decision_reason=args.decision_reason, notes=args.notes)
    if args.format == "json":
        print_json({"ok": True, "command": "screen", **result})
        return
    for warning in result["warnings"]:
        print(f"warn:  {warning}")
    row = result["job"]
    print(f"{row['id']}  Skipped: {row['decision_reason']}  listing_status={row['listing_status']}")


def cmd_verify(args):
    result = verify_job(
        args.id,
        listing_status=args.listing_status,
        first_party_verified=args.first_party_verified,
        apply_verified=args.apply_verified,
        original_url=args.original_url,
        decision_reason=args.decision_reason,
        notes=args.notes,
        level=args.level,
        remote_policy=args.remote_policy,
        stack=args.stack,
        salary=args.salary,
        match_score=args.match_score,
        application_status=args.application_status,
        next_action=args.next_action,
        next_action_date=args.next_action_date,
    )
    if args.format == "json":
        print_json({"ok": True, "command": "verify", **result})
        return
    for warning in result["warnings"]:
        print(f"warn:  {warning}")
    row = result["job"]
    print(
        f"{row['id']}  {result['outcome']}  "
        f"application_status={row['application_status']}  listing_status={row['listing_status']}"
    )


def cmd_validate(args):
    rows = load()
    source_rows = load_job_sources()
    errors, warnings = validate_dataset(rows, source_rows)
    notices = temporal_notices(rows)
    ok = not errors and not (warnings and args.strict)
    if args.format == "json":
        print_json(
            {
                "ok": ok,
                "command": "validate",
                "checked": len(rows),
                "source_references": len(source_rows),
                "errors": errors,
                "warnings": warnings,
                "notices": notices,
            }
        )
        if not ok:
            raise SystemExit(1)
        return
    for notice in notices:
        print(f"note:  {notice}")
    for warning in warnings:
        print(f"warn:  {warning}")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    print(
        f"\nпроверено записей: {len(rows)}; source references: {len(source_rows)}; "
        f"ошибок: {len(errors)}; предупреждений: {len(warnings)}; заметок: {len(notices)}"
    )
    if not ok:
        raise SystemExit(1)


def cmd_dupes(args):
    rows = [row for row in load() if row["decision_reason"] != "duplicate_listing"]
    candidates = find_fuzzy_duplicates(rows, args.threshold, args.role_threshold)
    if args.format == "json":
        print_json(
            {
                "ok": not (candidates and args.fail),
                "command": "dupes",
                "candidates": candidates,
            }
        )
    else:
        for candidate in candidates:
            first, second = candidate["first"], candidate["second"]
            print(
                f"company {candidate['company_similarity']:.2f} / role {candidate['role_similarity']:.2f}\n"
                f"  {first['id']}  {first['company']} — {first['role']}  [{first['application_status']}; {first['listing_status']}]\n"
                f"  {second['id']}  {second['company']} — {second['role']}  [{second['application_status']}; {second['listing_status']}]\n"
            )
        print(f"пар-кандидатов: {len(candidates)}")
    if candidates and args.fail:
        raise SystemExit(1)


def cmd_render_index(args):
    rows = load()
    source_rows = load_job_sources(allow_missing=True)
    ensure_dataset_valid(rows, source_rows, emit_warnings=False)
    artifacts = {
        "known": (PATHS.known_index_path, render_known_index(rows)),
        "keys": (PATHS.keys_index_path, render_keys_index(source_rows)),
        "active": (PATHS.active_index_path, render_active_index(rows)),
    }
    up_to_date = {
        name: write_or_check_index_file(path, data, args.check) for name, (path, data) in artifacts.items()
    }
    all_up_to_date = all(up_to_date.values())
    result = {
        "ok": all_up_to_date if args.check else True,
        "command": "render-index",
        "paths": {name: path.relative_to(PATHS.root).as_posix() for name, (path, _) in artifacts.items()},
        "up_to_date": up_to_date,
    }
    if args.format == "json":
        print_json(result)
    elif args.check:
        if all_up_to_date:
            print("data/index/* is up to date")
        else:
            stale = [name for name, ok in up_to_date.items() if not ok]
            print(
                "data/index/* is out of date for: "
                + ", ".join(stale)
                + "; run: python3 scripts/jobs.py render-index",
                file=sys.stderr,
            )
    else:
        print("data/index/* rendered")
    if args.check and not all_up_to_date:
        raise SystemExit(1)


def cmd_render_tracker(args):
    rows = load()
    source_references = load_job_sources()
    ensure_dataset_valid(rows, source_references, emit_warnings=False)
    try:
        application_cards = tracker_application_cards(rows)
        payload = tracker_payload(rows, source_references, application_cards)
        markdown = render_tracker_markdown(payload)
    except ValueError as error:
        die(f"render-tracker: {error}")
    up_to_date = write_or_check_tracker(markdown, args.check)
    result = {
        "ok": up_to_date if args.check else True,
        "command": "render-tracker",
        "path": PATHS.tracker_path.relative_to(PATHS.root).as_posix(),
        "up_to_date": up_to_date,
        "counts": payload["counts"],
    }
    if args.format == "json":
        print_json(result)
    elif args.check:
        if up_to_date:
            print("docs/tracker.md is up to date")
        else:
            print(
                "docs/tracker.md is out of date; run: python3 scripts/jobs.py render-tracker", file=sys.stderr
            )
    else:
        print("docs/tracker.md rendered")
    if args.check and not up_to_date:
        raise SystemExit(1)


def cmd_stale(args):
    rows = load()
    reference_date = args.date or business_date()
    stale = stale_entries(rows, args.days, reference_date)
    payload = {
        "ok": True,
        "command": "stale",
        "as_of": reference_date.isoformat(),
        "days": args.days,
        "count": len(stale),
        "jobs": [
            {
                "id": entry["job"]["id"],
                "company": entry["job"]["company"],
                "role": entry["job"]["role"],
                "verified_at": entry["job"]["verified_at"],
                "reason": entry["reason"],
                "age_days": entry["age_days"],
            }
            for entry in sorted(
                stale, key=lambda entry: (entry["job"]["verified_at"] or "0000-00-00", entry["job"]["id"])
            )
        ],
    }
    if args.format == "json":
        print_json(payload)
        return
    print(f"# Stale verification — {payload['as_of']} (>{args.days} days)")
    if not payload["jobs"]:
        print("\nНет просроченных active records.")
        return
    print("\n| id | Компания | Роль | Verified at | Причина | Возраст |\n|---|---|---|---|---|---:|")
    for job in payload["jobs"]:
        age = job["age_days"] if job["age_days"] is not None else "—"
        print(
            f"| {job['id']} | {job['company']} | {job['role']} | {job['verified_at'] or '—'} | {job['reason']} | {age} |"
        )


def cmd_todo(args):
    rows = filter_todo_rows(load(), source=args.source, id_range=args.id_range)
    reference_date = args.date or business_date()
    sections = todo_sections(rows, reference_date, stale_days=args.stale_days)
    payload = {
        "ok": True,
        "command": "todo",
        "date": reference_date.isoformat(),
        "stale_days": args.stale_days,
        "filters": {
            "source": args.source,
            "id_range": args.id_range.display() if args.id_range else None,
        },
        "section_order": [key for key, _title in TODO_SECTION_ORDER],
        "sections": sections,
    }
    if args.format == "json":
        print_json(payload)
        return
    print(f"# TODO — {payload['date']}")
    titles = dict(TODO_SECTION_ORDER)
    for key, _title in TODO_SECTION_ORDER:
        print(f"\n## {titles[key]}")
        items = sections[key]
        if not items:
            print("Нет задач.")
            continue
        print("\n| Дата | Приоритет | id | Компания | Роль | Действие |\n|---|---:|---|---|---|---|")
        for item in items:
            priority = f"{item['priority']:g}" if item["priority"] is not None else "—"
            action = item["next_action"] or item["reason"] or "—"
            print(
                f"| {item['date'] or '—'} | {priority} | {item['id']} | {item['company']} | {item['role']} | {action} |"
            )


def cmd_stats(args):
    payload = stats_payload(load(), args.date or business_date(), stale_days=args.stale_days)
    if args.format == "json":
        print_json(payload)
        return
    verification = payload["verification"]
    stale = payload["stale"]
    funnel = payload["funnel"]
    coverage = (
        f"{verification['coverage_percent']:g}%" if verification["coverage_percent"] is not None else "—"
    )
    response_rate = f"{funnel['response_rate']:g}%" if funnel["response_rate"] is not None else "—"
    print(
        f"jobs={payload['jobs_total']}; active_candidates={payload['derived']['active_candidates']}; "
        f"verification_coverage={coverage}; stale={stale['count']}; "
        f"applications={funnel['applications']}; response_rate={response_rate}"
    )


def cmd_report(args):
    payload = stats_payload(load(), args.date or business_date(), stale_days=args.stale_days)
    if args.format == "json":
        print_json(payload)
        return
    print(f"# Отчёт job-searcher — {payload['as_of']}\n\nВсего записей: **{payload['jobs_total']}**")
    print("\n## Основной статус\n\n| Derived state | Кол-во |\n|---|---:|")
    for state, amount in payload["derived_state"].items():
        print(f"| {state} | {amount} |")
    verification = payload["verification"]
    coverage = (
        f"{verification['coverage_percent']:g}%" if verification["coverage_percent"] is not None else "—"
    )
    print(
        "\n## Verification coverage\n\n"
        f"Active candidates: **{verification['eligible_records']}**; fully verified: "
        f"**{verification['fully_verified']}** ({coverage})."
    )
    stale = payload["stale"]
    print(f"\n## Stale verification\n\nOlder than {stale['days']} days: **{stale['count']}**.")
    print("\n## Воронка (по stage_reached)\n\n| Стадия | Достигли | % от откликов |\n|---|---:|---:|")
    for stage in payload["funnel"]["stages"]:
        rate = (
            f"{stage['percent_of_applications']:g}%" if stage["percent_of_applications"] is not None else "—"
        )
        print(f"| {stage['stage']} | {stage['reached']} | {rate} |")
    response_rate = payload["funnel"]["response_rate"]
    rate = f"{response_rate:g}%" if response_rate is not None else "—"
    print(
        f"\nОтветов: **{payload['funnel']['responses']}** из **{payload['funnel']['applications']}** ({rate})."
    )
    print(
        "\n## Источники\n\n| Источник | Найдено | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|---:|"
    )
    for source in payload["sources"]:
        rate = f"{source['response_rate']:g}%" if source["response_rate"] is not None else "—"
        print(
            f"| {source['source']} | {source['found']} | {source['applied']} | {source['responses']} | {rate} |"
        )
    print("\n## Версии CV\n\n| cv_version | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|")
    for version in payload["cv_versions"]:
        rate = f"{version['response_rate']:g}%" if version["response_rate"] is not None else "—"
        print(f"| {version['cv_version']} | {version['applied']} | {version['responses']} | {rate} |")
    print(
        "\n## Свойства объявлений\n\n`listing_status` описывает объявление отдельно от основного статуса.\n"
    )
    print("| Listing status | Кол-во |\n|---|---:|")
    for status, amount in payload["listing_status"].items():
        if amount:
            print(f"| {status} | {amount} |")
    print("\n## Причины отсева\n\n| decision_reason | Кол-во |\n|---|---:|")
    for reason, amount in payload["decision_reasons"].items():
        if amount:
            print(f"| {reason} | {amount} |")


def main():
    parser = JobsArgumentParser(prog="jobs.py", description="CLI для data/jobs.csv")
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=JobsArgumentParser)
    add = subparsers.add_parser("add", help="добавить вакансию")
    add.add_argument("--company")
    add.add_argument("--role")
    add.add_argument("--source", choices=SOURCES)
    add.add_argument("--application-status", choices=ADD_APPLICATION_STATUSES)
    add.add_argument("--listing-status", choices=LISTING_STATUSES)
    add.add_argument("--first-party-verified", choices=VERIFICATION)
    add.add_argument("--apply-verified", choices=VERIFICATION)
    add.add_argument("--level", choices=LEVELS)
    add.add_argument("--remote-policy", dest="remote_policy", choices=REMOTE)
    for flag, destination in [
        ("--original-url", "original_url"),
        ("--source-url", "source_url"),
        ("--source-job-id", "source_job_id"),
        ("--location", "location"),
        ("--stack", "stack"),
        ("--salary", "salary"),
        ("--posted-at", "posted_at"),
        ("--found-at", "found_at"),
        ("--match-score", "match_score"),
        ("--notes", "notes"),
    ]:
        add.add_argument(flag, dest=destination)
    add.add_argument("--decision-reason", dest="decision_reason", choices=REASONS)
    input_source = add.add_mutually_exclusive_group()
    input_source.add_argument("--json", dest="json_path", metavar="PATH")
    input_source.add_argument("--stdin", action="store_true")
    add.add_argument("--duplicate-of", dest="duplicate_of", metavar="JOB_ID")
    add.add_argument("--no-file", action="store_true")
    add.add_argument("--force", action="store_true")
    add.add_argument("--format", choices=("text", "json"), default="text")
    add.set_defaults(func=cmd_add)
    set_parser = subparsers.add_parser("set", help="изменить запись")
    set_parser.add_argument("id")
    set_parser.add_argument("field", nargs="*")
    set_parser.add_argument("--stage")
    set_parser.add_argument("--format", choices=("text", "json"), default="text")
    set_parser.set_defaults(func=cmd_set)
    status = subparsers.add_parser("status", help="зафиксировать подтверждённое человеком lifecycle-событие")
    status.add_argument("id")
    status.add_argument("--application-status", required=True, choices=APPLICATION_STATUSES)
    status.add_argument("--stage", choices=STAGES)
    status.add_argument("--applied-at")
    status.add_argument("--response-at")
    status.add_argument("--decision-reason", choices=("no_response_timeout", "withdrawn_by_me"))
    status.add_argument("--next-action")
    status.add_argument("--next-action-date")
    status.add_argument("--cv-version")
    status.add_argument("--notes")
    status.add_argument("--format", choices=("text", "json"), default="text")
    status.set_defaults(func=cmd_status)
    screen = subparsers.add_parser("screen", help="зафиксировать pre-application screening decision")
    screen.add_argument("id")
    screen.add_argument("--decision-reason", required=True, choices=sorted(SCREEN_REASONS))
    screen.add_argument("--notes")
    screen.add_argument("--format", choices=("text", "json"), default="text")
    screen.set_defaults(func=cmd_screen)
    verify = subparsers.add_parser("verify", help="зафиксировать completed first-party verification")
    verify.add_argument("id")
    verify.add_argument("--listing-status", required=True, choices=("open", "closed"))
    verify.add_argument("--first-party-verified", required=True, choices=("yes", "no"))
    verify.add_argument("--apply-verified", required=True, choices=("yes", "no"))
    verify.add_argument("--original-url")
    verify.add_argument("--decision-reason", choices=sorted(PRE_APPLICATION_REASONS - {"duplicate_listing"}))
    verify.add_argument("--notes")
    verify.add_argument("--level", choices=LEVELS, help="уровень, подтверждённый при проверке")
    verify.add_argument("--remote-policy", choices=REMOTE, help="remote policy, подтверждённая при проверке")
    verify.add_argument("--stack", help="стек через '; '")
    verify.add_argument("--salary", help="компенсация из первоисточника или Unknown")
    verify.add_argument("--match-score", help="оценка 1–10")
    verify.add_argument(
        "--application-status", choices=("apply",), help="зафиксировать начатый, но не отправленный процесс"
    )
    verify.add_argument("--next-action", help="следующий шаг для application_status=apply")
    verify.add_argument("--next-action-date", help="дата следующего шага YYYY-MM-DD")
    verify.add_argument("--format", choices=("text", "json"), default="text")
    verify.set_defaults(func=cmd_verify)
    validate = subparsers.add_parser("validate", help="проверить целостность")
    validate.add_argument("--strict", action="store_true")
    validate.add_argument("--format", choices=("text", "json"), default="text")
    validate.set_defaults(func=cmd_validate)
    render_tracker = subparsers.add_parser(
        "render-tracker",
        help="собрать browser-first Markdown view из canonical dataset",
    )
    render_tracker.add_argument("--check", action="store_true", help="проверить freshness без записи")
    render_tracker.add_argument("--format", choices=("text", "json"), default="text")
    render_tracker.set_defaults(func=cmd_render_tracker)
    render_index = subparsers.add_parser(
        "render-index",
        help="собрать компактные bootstrap-индексы data/index/*",
    )
    render_index.add_argument("--check", action="store_true", help="проверить freshness без записи")
    render_index.add_argument("--format", choices=("text", "json"), default="text")
    render_index.set_defaults(func=cmd_render_index)
    ingest = subparsers.add_parser("ingest", help="классифицировать raw JSONL batch")
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--dry-run", action="store_true", help="не изменять canonical dataset")
    ingest.add_argument("--resolutions", type=Path, help="JSON sidecar с явными решениями fuzzy matches")
    ingest.add_argument("--format", choices=("text", "json"), default="text")
    ingest.set_defaults(func=cmd_ingest)
    dupes = subparsers.add_parser("dupes", help="fuzzy-поиск дублей")
    dupes.add_argument("--threshold", type=float, default=0.85)
    dupes.add_argument("--role-threshold", dest="role_threshold", type=float, default=0.75)
    dupes.add_argument("--fail", action="store_true")
    dupes.add_argument("--format", choices=("text", "json"), default="text")
    dupes.set_defaults(func=cmd_dupes)
    stale = subparsers.add_parser("stale", help="показать active records с просроченной verification")
    stale.add_argument("--days", required=True, type=positive_int, help="verification старше N дней")
    stale.add_argument("--date", type=iso_date_argument, help="дата среза YYYY-MM-DD (по умолчанию сегодня)")
    stale.add_argument("--format", choices=("text", "json"), default="text")
    stale.set_defaults(func=cmd_stale)
    todo = subparsers.add_parser("todo", help="ежедневная структурированная очередь действий")
    todo.add_argument("--date", type=iso_date_argument, help="дата среза YYYY-MM-DD (по умолчанию сегодня)")
    todo.add_argument("--stale-days", type=positive_int, default=DEFAULT_STALE_DAYS)
    todo.add_argument("--source", choices=SOURCES, help="только вакансии с этим primary source")
    todo.add_argument("--id-range", type=job_id_range_argument, help="inclusive range: job-0099:job-0126")
    todo.add_argument("--format", choices=("text", "json"), default="text")
    todo.set_defaults(func=cmd_todo)
    stats = subparsers.add_parser("stats", help="структурированный daily/weekly snapshot")
    stats.add_argument("--date", type=iso_date_argument, help="дата среза YYYY-MM-DD (по умолчанию сегодня)")
    stats.add_argument("--stale-days", type=positive_int, default=DEFAULT_STALE_DAYS)
    stats.add_argument("--format", choices=("text", "json"), default="text")
    stats.set_defaults(func=cmd_stats)
    report = subparsers.add_parser("report", help="markdown-отчёт в stdout")
    report.add_argument("--date", type=iso_date_argument, help="дата среза YYYY-MM-DD (по умолчанию сегодня)")
    report.add_argument("--stale-days", type=positive_int, default=DEFAULT_STALE_DAYS)
    report.add_argument("--format", choices=("text", "json"), default="text")
    report.set_defaults(func=cmd_report)
    args = parser.parse_args()
    try:
        args.func(args)
    except ValidationError as error:
        die(str(error))
