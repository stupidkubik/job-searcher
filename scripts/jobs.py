#!/usr/bin/env python3
"""CLI для data/jobs.csv. Использует только стандартную библиотеку Python."""

import argparse
import csv
import math
import os
import re
import sys
import tempfile
import unicodedata
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "jobs.csv"
APPS_DIR = ROOT / "applications"
TEMPLATE_PATH = APPS_DIR / "_TEMPLATE.md"

FIELDS = [
    "id", "status", "company", "role", "level", "original_url", "source_url", "source",
    "location", "remote_policy", "stack", "salary", "posted_at", "found_at",
    "match_score", "stage_reached", "decision_reason", "applied_at",
    "response_at", "next_action", "next_action_date", "cv_version",
    "cover_letter", "contact_name", "contact_url", "last_update", "notes",
]
LEGACY_FIELDS = [
    "id", "company", "role", "level", "original_url", "source_url", "source",
    "location", "remote_policy", "stack", "salary", "posted_at", "found_at",
    "match_score", "status", "stage_reached", "decision_reason", "applied_at",
    "response_at", "next_action", "next_action_date", "cv_version",
    "cover_letter", "contact_name", "contact_url", "last_update", "notes",
]
REQUIRED = ["id", "company", "role", "source", "found_at", "status", "stage_reached", "last_update"]
DATE_FIELDS = ["posted_at", "found_at", "applied_at", "response_at", "next_action_date", "last_update"]
STATUSES = ["New", "Reviewing", "Apply", "Applied", "Interviewing", "Offer", "Rejected", "Ghosted", "Skipped", "Closed", "Duplicate", "Withdrawn"]
STAGES = ["None", "Applied", "Recruiter screen", "Tech interview", "Test task", "Final interview", "Offer"]
LEVELS = ["Intern", "Graduate", "Junior", "Junior+", "Associate", "Junior/Middle", "Middle", "Senior", "Unknown"]
REMOTE = ["Global", "Europe", "EMEA", "Serbia", "Country-specific", "Hybrid", "On-site", "Unclear"]
SOURCES = [
    "Hirify", "Jaabz", "LinkedIn", "Welcome to the Jungle", "We Work Remotely",
    "HiringCafe", "Hacker News — Who is Hiring?", "Hacker News — Who Wants to Be Hired?",
    "YC Work at a Startup", "Wellfound", "HelloWorld.rs", "Reactiflux Discord",
    "Find My Remote / Telegram", "Himalayas", "Startit Jobs", "Company Careers",
    "Referral", "Manual", "Other",
]
REASONS = ["geo_restriction", "work_authorization", "seniority_too_high", "seniority_too_low", "stack_mismatch", "role_not_frontend", "salary_too_low", "company_not_interesting", "closed_before_application", "already_applied", "duplicate_listing", "no_response_timeout", "withdrawn_by_me", "other"]
NEEDS_REASON = {"Skipped", "Closed", "Duplicate", "Withdrawn"}
NEEDS_APPLIED_AT = {"Applied", "Interviewing", "Offer", "Rejected", "Ghosted", "Withdrawn"}
RESPONDED_STATUSES = {"Interviewing", "Offer", "Rejected"}
ADD_STATUSES = ["New", "Reviewing", "Apply", "Skipped", "Closed"]
SET_PROTECTED = {"id", "stage_reached", "last_update"}
ENUMS = {"status": STATUSES, "stage_reached": STAGES, "level": LEVELS, "remote_policy": REMOTE, "source": SOURCES, "decision_reason": REASONS}
GHOST_AFTER_DAYS = 30


def today():
    return date.today().isoformat()


def die(message):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def load(allow_legacy=False):
    if not CSV_PATH.exists():
        die(f"не найден {CSV_PATH}")
    with CSV_PATH.open(newline="", encoding="utf-8") as file:
        reader = csv.DictReader(file)
        if reader.fieldnames != FIELDS and not (allow_legacy and reader.fieldnames == LEGACY_FIELDS):
            die("заголовок jobs.csv не совпадает со схемой; см. data/schema.md")
        return list(reader)


def save(rows):
    """Атомарно заменяет CSV, чтобы ошибка не оставила обрезанный файл."""
    descriptor, temporary_name = tempfile.mkstemp(prefix="jobs-", suffix=".csv", dir=CSV_PATH.parent)
    try:
        with os.fdopen(descriptor, "w", newline="", encoding="utf-8") as file:
            writer = csv.DictWriter(file, fieldnames=FIELDS, lineterminator="\n")
            writer.writeheader()
            writer.writerows({key: row.get(key) or "" for key in FIELDS} for row in rows)
        os.replace(temporary_name, CSV_PATH)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise


def norm(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return re.sub(r"\s+", " ", "".join(char if char.isalnum() else " " for char in text)).strip()


def norm_url(value):
    if not value:
        return ""
    try:
        parts = urlsplit(value.strip())
    except ValueError:
        return value.strip()
    query = [(key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
             if not key.lower().startswith("utm_") and key.lower() not in {"ref", "referrer", "source"}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/") or "/", urlencode(query), ""))


COMPANY_NOISE = {"ltd", "limited", "inc", "incorporated", "llc", "llp", "plc", "gmbh", "ag", "bv", "nv", "ab", "oy", "oyj", "as", "sa", "sas", "srl", "spa", "doo", "ooo", "corp", "corporation", "co", "company", "group", "holding", "holdings", "the"}
ROLE_NOISE = {"developer", "engineer", "software", "web", "senior", "junior", "middle", "mid", "associate", "graduate", "intern", "internship", "remote", "m", "f", "d", "x", "the", "and"}


def without_noise(text, noise):
    normalized = norm(text)
    result = " ".join(word for word in normalized.split() if word not in noise)
    return result or normalized


def similarity(first, second):
    return SequenceMatcher(None, first, second).ratio()


def slug(value):
    return norm(value).replace(" ", "-")[:28].strip("-")


def next_id(rows):
    numbers = [int(match.group(1)) for row in rows if (match := re.fullmatch(r"job-(\d{4,})", row["id"] or ""))]
    return f"job-{max(numbers, default=0) + 1:04d}"


def find(rows, job_id):
    for row in rows:
        if row["id"] == job_id:
            return row
    die(f"запись {job_id} не найдена")


def validate_rows(rows):
    errors, warnings, ids, urls, duplicate_refs = [], [], {}, {}, []

    def error(line, message):
        errors.append(f"строка {line}: {message}")

    for line, row in enumerate(rows, start=2):
        identifier = row["id"] or "<пусто>"
        if None in row:
            error(line, f"{identifier}: лишние CSV-колонки: {row[None]}")
        for key in REQUIRED:
            if not (row[key] or "").strip():
                error(line, f"{identifier}: пустое обязательное поле {key}")
        if row["id"] and not re.fullmatch(r"job-\d{4,}", row["id"]):
            error(line, f"{identifier}: id должен быть вида job-NNNN")
        if row["id"] in ids:
            error(line, f"{identifier}: дубль id (уже в строке {ids[row['id']]})")
        ids[row["id"]] = line
        for key, allowed in ENUMS.items():
            value = (row[key] or "").strip()
            if value and value not in allowed:
                error(line, f"{identifier}: {key}={value!r} не входит в {allowed}")
        for key in DATE_FIELDS:
            value = (row[key] or "").strip()
            if not value:
                continue
            try:
                parsed = datetime.strptime(value, "%Y-%m-%d").date()
            except ValueError:
                error(line, f"{identifier}: {key}={value!r} — ожидается YYYY-MM-DD")
            else:
                if key != "next_action_date" and parsed > date.today():
                    warnings.append(f"строка {line}: {identifier}: {key}={value} в будущем — опечатка в годе?")
        score = (row["match_score"] or "").strip()
        if score:
            try:
                parsed_score = float(score)
                if not math.isfinite(parsed_score) or not 1 <= parsed_score <= 10:
                    error(line, f"{identifier}: match_score вне диапазона 1–10")
            except ValueError:
                error(line, f"{identifier}: match_score не число: {score!r}")
        original_url = (row["original_url"] or "").strip()
        if original_url:
            try:
                parts = urlsplit(original_url)
                if parts.scheme not in {"http", "https"} or not parts.netloc:
                    raise ValueError
                urls.setdefault(norm_url(original_url), []).append((line, row))
            except ValueError:
                error(line, f"{identifier}: original_url не является http(s) URL: {original_url!r}")
        status = row["status"]
        if status in NEEDS_REASON and not (row["decision_reason"] or "").strip():
            error(line, f"{identifier}: status={status} требует decision_reason")
        if status in NEEDS_APPLIED_AT and not (row["applied_at"] or "").strip():
            error(line, f"{identifier}: status={status} требует applied_at")
        if status in RESPONDED_STATUSES and not (row["response_at"] or "").strip():
            error(line, f"{identifier}: status={status} требует response_at")
        if row["decision_reason"] == "other" and not (row["notes"] or "").strip():
            error(line, f"{identifier}: decision_reason=other требует пояснения в notes")
        if status == "Duplicate":
            if row["decision_reason"] != "duplicate_listing":
                error(line, f"{identifier}: Duplicate требует decision_reason=duplicate_listing")
            match = re.search(r"\bjob-\d{4,}\b", row["notes"] or "")
            if not match:
                error(line, f"{identifier}: Duplicate требует id оригинала в notes")
            else:
                duplicate_refs.append((line, identifier, match.group(0)))
        if status in NEEDS_APPLIED_AT and (row["stage_reached"] or "None") == "None":
            error(line, f"{identifier}: status={status}, но stage_reached=None")
        if row["stage_reached"] == "Offer" and status not in {"Offer", "Rejected", "Withdrawn"}:
            warnings.append(f"строка {line}: {identifier}: stage=Offer при status={status}")
        try:
            if row["response_at"] and row["applied_at"] and datetime.strptime(row["response_at"], "%Y-%m-%d") < datetime.strptime(row["applied_at"], "%Y-%m-%d"):
                error(line, f"{identifier}: response_at раньше applied_at")
        except ValueError:
            pass
        if "\n" in (row["notes"] or ""):
            error(line, f"{identifier}: перевод строки в notes; длинный текст → applications/{identifier}.md")
        if status == "Applied" and row["applied_at"] and not row["response_at"]:
            try:
                days = (date.today() - datetime.strptime(row["applied_at"], "%Y-%m-%d").date()).days
                if days > GHOST_AFTER_DAYS:
                    warnings.append(f"строка {line}: {identifier}: {days} дней без ответа → status=Ghosted?")
            except ValueError:
                pass
    for canonical, entries in urls.items():
        if len(entries) > 1 and len([row for _, row in entries if row["status"] != "Duplicate"]) != 1:
            labels = ", ".join(f"{row['id']}@{line}" for line, row in entries)
            errors.append(f"canonical original_url={canonical!r}: ожидается ровно одна оригинальная запись, получено: {labels}")
    for line, identifier, original in duplicate_refs:
        if original == identifier:
            error(line, f"{identifier}: Duplicate ссылается сам на себя")
        elif original not in ids:
            error(line, f"{identifier}: оригинал {original} не найден")
    return errors, warnings


def ensure_valid(rows):
    errors, warnings = validate_rows(rows)
    if errors:
        die("изменение отклонено:\n  " + "\n  ".join(errors))
    for warning in warnings:
        print(f"warn:  {warning}")


def cmd_add(args):
    rows = load()
    company, role = args.company.strip(), args.role.strip()
    hits = {}
    if args.original_url:
        for row in rows:
            if row["original_url"] and norm_url(row["original_url"]) == norm_url(args.original_url):
                hits[row["id"]] = (row, "совпадение canonical original_url")
    company_norm, role_norm = without_noise(company, COMPANY_NOISE), without_noise(role, ROLE_NOISE)
    for row in rows:
        company_score = similarity(company_norm, without_noise(row["company"], COMPANY_NOISE))
        role_score = similarity(role_norm, without_noise(row["role"], ROLE_NOISE))
        if company_score >= .85 and role_score >= .75:
            hits.setdefault(row["id"], (row, f"похоже: company {company_score:.2f}, role {role_score:.2f}"))
    if args.duplicate_of:
        original = find(rows, args.duplicate_of)
        status, reason = "Duplicate", "duplicate_listing"
        notes = f"duplicate of {original['id']}" + (f"; {args.notes}" if args.notes else "")
    else:
        status, reason, notes = args.status, args.decision_reason or "", args.notes or ""
    if hits and not args.force and not args.duplicate_of:
        print("возможные дубли:")
        for row, reason_text in hits.values():
            print(f"  {row['id']}  {row['company']} — {row['role']}  [{row['status']}]  ({reason_text})")
        print("\nэто дубль -> повторите с --duplicate-of job-NNNN\nэто другая вакансия -> повторите с --force")
        raise SystemExit(2)
    identifier = next_id(rows)
    row = {key: "" for key in FIELDS}
    row.update({"id": identifier, "company": company, "role": role, "level": args.level, "original_url": args.original_url or "", "source_url": args.source_url or "", "source": args.source, "location": args.location or "", "remote_policy": args.remote_policy, "stack": args.stack or "", "salary": args.salary or "Unknown", "posted_at": args.posted_at or "", "found_at": args.found_at or today(), "match_score": args.match_score or "", "status": status, "stage_reached": "None", "decision_reason": reason, "last_update": today(), "notes": notes.replace("\n", " ")})
    rows.append(row)
    app_path = APPS_DIR / f"{identifier}-{slug(company)}-{slug(role)}.md"
    create_file = not args.no_file and status not in {"Duplicate", "Skipped", "Closed"}
    if create_file and not TEMPLATE_PATH.exists():
        die(f"не найден шаблон {TEMPLATE_PATH}")
    ensure_valid(rows)
    save(rows)
    if create_file and not app_path.exists():
        body = TEMPLATE_PATH.read_text(encoding="utf-8").replace("job-0000", identifier).replace("{{company}}", company).replace("{{role}}", role)
        body = body.replace("company:", f"company: {company}", 1).replace("role:", f"role: {role}", 1).replace("original_url:", f"original_url: {args.original_url or ''}", 1)
        app_path.write_text(body, encoding="utf-8")
        print(f"создан {app_path.relative_to(ROOT)}")
    print(f"{identifier}  {company} — {role}  [{status}]")


def cmd_set(args):
    if not args.field and not args.stage:
        die("нечего менять: укажите field=value и/или --stage")
    rows, row = load(), None
    row = find(rows, args.id)
    for pair in args.field:
        if "=" not in pair:
            die(f"ожидается field=value, получено: {pair}")
        key, value = pair.split("=", 1)
        if key not in FIELDS:
            die(f"неизвестное поле: {key}")
        if key in SET_PROTECTED:
            die(f"поле {key} управляется скриптом и не меняется через field=value")
        if key == "status" and value == "Duplicate" and row["status"] != "Duplicate":
            die("Duplicate создаётся только командой add --duplicate-of JOB_ID")
        if key in ENUMS and value and value not in ENUMS[key]:
            die(f"{key}: недопустимое значение {value!r}")
        row[key] = value.replace("\n", " ")
    if args.stage:
        if args.stage not in STAGES:
            die(f"недопустимая стадия: {args.stage}")
        current = row["stage_reached"] or "None"
        if STAGES.index(args.stage) < STAGES.index(current):
            die(f"stage_reached нельзя понижать: {current} -> {args.stage}")
        row["stage_reached"] = args.stage
        if STAGES.index("Recruiter screen") <= STAGES.index(args.stage) <= STAGES.index("Final interview") and row["status"] == "Applied":
            row["status"] = "Interviewing"
        if args.stage == "Offer" and row["status"] in {"Applied", "Interviewing"}:
            row["status"] = "Offer"
    if row["status"] in NEEDS_APPLIED_AT and not row["applied_at"]:
        row["applied_at"] = today()
    if row["status"] in NEEDS_APPLIED_AT and (row["stage_reached"] or "None") == "None":
        row["stage_reached"] = "Applied"
    if row["status"] == "Offer":
        row["stage_reached"] = "Offer"
    if row["status"] in RESPONDED_STATUSES and not row["response_at"]:
        row["response_at"] = today()
    row["last_update"] = today()
    ensure_valid(rows)
    save(rows)
    print(f"{row['id']}  status={row['status']}  stage={row['stage_reached']}")


def cmd_validate(args):
    errors, warnings = validate_rows(load())
    for warning in warnings:
        print(f"warn:  {warning}")
    for error in errors:
        print(f"error: {error}", file=sys.stderr)
    print(f"\nпроверено записей: {len(load())}; ошибок: {len(errors)}; предупреждений: {len(warnings)}")
    if errors or (warnings and args.strict):
        raise SystemExit(1)


def cmd_migrate_columns(args):
    rows = load(allow_legacy=True)
    ensure_valid(rows)
    save(rows)
    print("порядок колонок jobs.csv обновлён")


def cmd_dupes(args):
    rows, found = [row for row in load() if row["status"] != "Duplicate"], 0
    for index, first in enumerate(rows):
        for second in rows[index + 1:]:
            company_score = similarity(without_noise(first["company"], COMPANY_NOISE), without_noise(second["company"], COMPANY_NOISE))
            role_score = similarity(without_noise(first["role"], ROLE_NOISE), without_noise(second["role"], ROLE_NOISE))
            if company_score >= args.threshold and role_score >= args.role_threshold:
                found += 1
                print(f"company {company_score:.2f} / role {role_score:.2f}\n  {first['id']}  {first['company']} — {first['role']}  [{first['status']}]\n  {second['id']}  {second['company']} — {second['role']}  [{second['status']}]\n")
    print(f"пар-кандидатов: {found}")
    if found and args.fail:
        raise SystemExit(1)


def cmd_report(_args):
    rows = load()
    if not rows:
        print("jobs.csv пуст")
        return
    count = lambda predicate: sum(1 for row in rows if predicate(row))
    print(f"# Отчёт job-searcher — {today()}\n\nВсего записей: **{len(rows)}**\n\n## Статусы\n\n| Статус | Кол-во |\n|---|---:|")
    for status in STATUSES:
        if amount := count(lambda row, status=status: row["status"] == status):
            print(f"| {status} | {amount} |")
    print("\n## Воронка (по stage_reached)\n\n| Стадия | Достигли | % от откликов |\n|---|---:|---:|")
    applied = count(lambda row: (row["stage_reached"] or "None") != "None")
    for stage in STAGES[1:]:
        amount = count(lambda row, stage=stage: row["stage_reached"] and STAGES.index(row["stage_reached"]) >= STAGES.index(stage))
        print(f"| {stage} | {amount} | {amount / applied * 100:.0f}% |" if applied else f"| {stage} | {amount} | — |")
    print("\n## Источники\n\n| Источник | Найдено | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|---:|")
    for source in SOURCES:
        found = count(lambda row, source=source: row["source"] == source)
        if found:
            applied_count = count(lambda row, source=source: row["source"] == source and row["applied_at"])
            responses = count(lambda row, source=source: row["source"] == source and row["response_at"])
            rate = f"{responses / applied_count * 100:.0f}%" if applied_count else "—"
            print(f"| {source} | {found} | {applied_count} | {responses} | {rate} |")
    print("\n## Конверсия по match_score\n\n| match_score | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|")
    for label, low, high in [("9–10", 9, 10), ("7–8.99", 7, 9), ("5–6.99", 5, 7), ("<5", 0, 5)]:
        def in_bucket(row, low=low, high=high):
            try:
                score = float(row["match_score"])
                return low <= score < high or (high == 10 and score == 10)
            except (TypeError, ValueError):
                return False
        applied_count = count(lambda row: in_bucket(row) and row["applied_at"])
        if applied_count:
            responses = count(lambda row: in_bucket(row) and row["response_at"])
            print(f"| {label} | {applied_count} | {responses} | {responses / applied_count * 100:.0f}% |")
    print("\n## Версии CV\n\n| cv_version | Откликов | Ответов | Response rate |\n|---|---:|---:|---:|")
    for version in sorted({row["cv_version"] for row in rows if row["cv_version"]}):
        applied_count = count(lambda row, version=version: row["cv_version"] == version and row["applied_at"])
        if applied_count:
            responses = count(lambda row, version=version: row["cv_version"] == version and row["response_at"])
            print(f"| {version} | {applied_count} | {responses} | {responses / applied_count * 100:.0f}% |")
    unknown_cv_count = count(lambda row: row["applied_at"] and not (row["cv_version"] or "").strip())
    if unknown_cv_count:
        responses = count(lambda row: row["applied_at"] and not (row["cv_version"] or "").strip() and row["response_at"])
        print(f"| not recorded | {unknown_cv_count} | {responses} | {responses / unknown_cv_count * 100:.0f}% |")
    print("\n## Причины отсева\n\n| decision_reason | Кол-во |\n|---|---:|")
    for reason in REASONS:
        if amount := count(lambda row, reason=reason: row["decision_reason"] == reason):
            print(f"| {reason} | {amount} |")
    print("\n## Действия к исполнению\n")
    due = sorted((row for row in rows if row["next_action_date"] and row["next_action_date"] <= today()), key=lambda row: row["next_action_date"])
    if not due:
        print("Просроченных действий нет.")
    else:
        print("| Дата | id | Компания | Действие |\n|---|---|---|---|")
        for row in due:
            print(f"| {row['next_action_date']} | {row['id']} | {row['company']} | {row['next_action']} |")


def main():
    parser = argparse.ArgumentParser(prog="jobs.py", description="CLI для data/jobs.csv")
    subparsers = parser.add_subparsers(dest="command", required=True)
    add = subparsers.add_parser("add", help="добавить вакансию")
    add.add_argument("--company", required=True); add.add_argument("--role", required=True)
    add.add_argument("--source", required=True, choices=SOURCES); add.add_argument("--status", default="New", choices=ADD_STATUSES)
    add.add_argument("--level", default="Unknown", choices=LEVELS); add.add_argument("--remote-policy", dest="remote_policy", default="Unclear", choices=REMOTE)
    for flag, destination in [("--original-url", "original_url"), ("--source-url", "source_url"), ("--location", "location"), ("--stack", "stack"), ("--salary", "salary"), ("--posted-at", "posted_at"), ("--found-at", "found_at"), ("--match-score", "match_score"), ("--notes", "notes")]:
        add.add_argument(flag, dest=destination)
    add.add_argument("--decision-reason", dest="decision_reason", choices=REASONS); add.add_argument("--duplicate-of", dest="duplicate_of", metavar="JOB_ID")
    add.add_argument("--no-file", action="store_true"); add.add_argument("--force", action="store_true"); add.set_defaults(func=cmd_add)
    set_parser = subparsers.add_parser("set", help="изменить запись")
    set_parser.add_argument("id"); set_parser.add_argument("field", nargs="*"); set_parser.add_argument("--stage"); set_parser.set_defaults(func=cmd_set)
    validate = subparsers.add_parser("validate", help="проверить целостность")
    validate.add_argument("--strict", action="store_true"); validate.set_defaults(func=cmd_validate)
    migrate = subparsers.add_parser("migrate-columns", help="перестроить CSV в текущем порядке колонок")
    migrate.set_defaults(func=cmd_migrate_columns)
    dupes = subparsers.add_parser("dupes", help="fuzzy-поиск дублей")
    dupes.add_argument("--threshold", type=float, default=.85); dupes.add_argument("--role-threshold", dest="role_threshold", type=float, default=.75); dupes.add_argument("--fail", action="store_true"); dupes.set_defaults(func=cmd_dupes)
    report = subparsers.add_parser("report", help="markdown-отчёт в stdout"); report.set_defaults(func=cmd_report)
    args = parser.parse_args(); args.func(args)


if __name__ == "__main__":
    main()
