"""Read-only computed views: the browser-first tracker Markdown, the
bootstrap indexes under data/index/, and the todo/stats/report payloads.

docs/agent-write-path-plan-2026-09-07.md, Э10. Nothing here writes to
data/jobs.csv or data/job_sources.csv.
"""

import csv
import os
import re
import tempfile
from datetime import datetime, timedelta
from io import StringIO
from pathlib import Path
from urllib.parse import quote

try:  # Direct CLI execution places scripts/ on sys.path.
    from tracker_paths import PATHS
    from tracker_schema import (
        APPLICATION_STATUSES,
        DEFAULT_STALE_DAYS,
        FIELDS,
        LISTING_STATUSES,
        PRE_APPLICATION_STATUSES,
        REASONS,
        SOURCES,
        STAGES,
        TERMINAL_APPLICATION_STATUSES,
        VERIFICATION,
        valid_http_url,
    )
    from tracker_validate import norm_url
except ModuleNotFoundError:  # Unit tests may import this module as scripts.tracker_render.
    from scripts.tracker_paths import PATHS
    from scripts.tracker_schema import (
        APPLICATION_STATUSES,
        DEFAULT_STALE_DAYS,
        FIELDS,
        LISTING_STATUSES,
        PRE_APPLICATION_STATUSES,
        REASONS,
        SOURCES,
        STAGES,
        TERMINAL_APPLICATION_STATUSES,
        VERIFICATION,
        valid_http_url,
    )
    from scripts.tracker_validate import norm_url


TODO_SECTION_ORDER = (
    ("overdue", "Просрочено"),
    ("today", "Сегодня"),
    ("follow_ups", "Follow-ups"),
    ("apply_not_submitted", "Apply not submitted"),
    ("stale_review", "Stale review"),
    ("verification_queue", "Verification queue"),
    ("upcoming_interview_test", "Upcoming interview / test"),
)

TRACKER_SECTION_ORDER = ("action_now", "applications", "to_verify", "archive")

TRACKER_SECTION_TITLES = {
    "action_now": "Action now",
    "applications": "Applications",
    "to_verify": "To verify",
    "archive": "Archive",
}

TRACKER_APPLICATION_STATUS_ORDER = {
    "offer": 0,
    "interviewing": 1,
    "applied": 2,
    "rejected": 3,
    "ghosted": 4,
    "withdrawn": 5,
}


def parsed_row_date(value):
    if not value:
        return None
    return datetime.strptime(value, "%Y-%m-%d").date()


def is_active_candidate(row):
    """Active means there is no terminal decision or completed listing closure."""
    return (
        row["listing_status"] != "closed"
        and not row["decision_reason"]
        and row["application_status"] not in TERMINAL_APPLICATION_STATUSES
    )


def derived_state(row):
    """Return the primary human-facing state while keeping listing state separate."""
    reason = row["decision_reason"]
    if reason == "duplicate_listing":
        return "Duplicate"
    if row["application_status"] == "not_started" and (
        reason == "closed_before_application" or row["listing_status"] == "closed"
    ):
        return "Closed"
    if row["application_status"] == "not_started" and reason:
        return f"Skipped: {reason}"
    return {
        "not_started": "Not started",
        "reviewing": "Reviewing",
        "apply": "Apply",
        "applied": "Applied",
        "interviewing": "Interviewing",
        "offer": "Offer",
        "rejected": "Rejected",
        "ghosted": "Ghosted",
        "withdrawn": "Withdrawn",
    }[row["application_status"]]


def tracker_section(row):
    """Classify one valid canonical row into exactly one browser tracker section."""
    application_status = row["application_status"]
    case_status = derived_state(row)
    if application_status in TRACKER_APPLICATION_STATUS_ORDER:
        return "applications"
    if case_status == "Closed" or case_status == "Duplicate" or case_status.startswith("Skipped: "):
        return "archive"
    if (
        application_status in PRE_APPLICATION_STATUSES
        and row["listing_status"] == "open"
        and not row["decision_reason"]
        and row["first_party_verified"] == "yes"
        and row["apply_verified"] == "yes"
    ):
        return "action_now"
    if (
        application_status in PRE_APPLICATION_STATUSES
        and row["listing_status"] != "closed"
        and not row["decision_reason"]
    ):
        return "to_verify"
    raise ValueError(
        f"{row['id']}: cannot classify application_status={application_status!r}, "
        f"listing_status={row['listing_status']!r}, decision_reason={row['decision_reason']!r}"
    )


def tracker_case_display(case_status):
    """Map an existing derived state to text intended for the Markdown view."""
    if case_status == "Apply":
        return "Ready to apply"
    if case_status.startswith("Skipped: "):
        return f"Skipped: {case_status.removeprefix('Skipped: ').replace('_', ' ')}"
    return case_status


def tracker_listing_display(listing_status):
    return {"unknown": "Not checked", "open": "Open", "closed": "Closed"}[listing_status]


def tracker_decision_display(decision_reason):
    return decision_reason.replace("_", " ") if decision_reason else "—"


def tracker_needs(row):
    """Return domain and display labels for the checks still required by a row."""
    needs = []
    if row["first_party_verified"] != "yes":
        needs.append(("first_party", "First party"))
    if row["apply_verified"] != "yes":
        needs.append(("apply", "Apply"))
    if row["listing_status"] == "unknown":
        needs.append(("listing", "Listing"))
    return needs


def tracker_application_cards(rows, planned_paths=()):
    """Resolve the one supported Markdown card for every canonical job, if present."""
    cards = {}
    planned = {Path(path) for path in planned_paths}
    for row in rows:
        job_id = row["id"]
        matches = sorted(
            set(PATHS.apps_dir.glob(f"{job_id}-*.md")) | set(PATHS.apps_dir.glob(f"{job_id}.md"))
            | {path for path in planned if path.name == f"{job_id}.md" or path.name.startswith(f"{job_id}-")}
        )
        if len(matches) > 1:
            names = ", ".join(path.name for path in matches)
            raise ValueError(f"{row['id']}: multiple application cards match: {names}")
        if matches:
            cards[row["id"]] = matches[0].relative_to(PATHS.root).as_posix()
    return cards


def tracker_vacancy_url(row, source_references):
    """Choose the first validated external URL according to the view contract."""
    for value in (row["original_url"], row["source_url"]):
        if valid_http_url(value):
            return value
    for reference in source_references:
        if reference["job_id"] == row["id"] and valid_http_url(reference["source_url"]):
            return reference["source_url"]
    return None


def tracker_action_display(next_action, next_action_date, fallback=None):
    if next_action and next_action_date:
        return f"{next_action} · {next_action_date}"
    if next_action:
        return next_action
    if fallback:
        return f"{fallback} · {next_action_date}" if next_action_date else fallback
    if next_action_date:
        return next_action_date
    return "—"


def tracker_item(row, source_references, application_cards):
    """Build display-ready values without rendering any Markdown."""
    case_status = derived_state(row)
    needs = tracker_needs(row)
    return {
        "id": row["id"],
        "company": row["company"],
        "role": row["role"],
        "vacancy_url": tracker_vacancy_url(row, source_references),
        "application_card": application_cards.get(row["id"]),
        "case_status": case_status,
        "case_status_display": tracker_case_display(case_status),
        "application_status": row["application_status"],
        "listing_status": row["listing_status"],
        "listing_display": tracker_listing_display(row["listing_status"]),
        "match_score": row["match_score"] or None,
        "stage_reached": row["stage_reached"] or None,
        "applied_at": row["applied_at"] or None,
        "next_action": row["next_action"] or None,
        "next_action_date": row["next_action_date"] or None,
        "next_action_display": tracker_action_display(row["next_action"], row["next_action_date"]),
        "found_at": row["found_at"],
        "verified_at": row["verified_at"] or None,
        "last_update": row["last_update"],
        "decision_reason": row["decision_reason"] or None,
        "decision_display": tracker_decision_display(row["decision_reason"]),
        "needs": [need for need, _label in needs],
        "need_display": " + ".join(label for _need, label in needs) or "—",
    }


def tracker_date_sort_value(value, *, descending=False):
    numeric = int(value.replace("-", "")) if value else 0
    return -numeric if descending else (numeric or 99999999)


def tracker_id_number(identifier):
    match = re.fullmatch(r"job-(\d{4,})", identifier)
    if not match:
        raise ValueError(f"invalid tracker job id: {identifier!r}")
    return int(match.group(1))


def sort_tracker_items(section, items):
    if section == "action_now":
        status_order = {"apply": 0, "reviewing": 1, "not_started": 2}
        return sorted(
            items,
            key=lambda item: (
                status_order[item["application_status"]],
                tracker_date_sort_value(item["next_action_date"]),
                -score_priority(item),
                tracker_id_number(item["id"]),
            ),
        )
    if section == "applications":
        return sorted(
            items,
            key=lambda item: (
                TRACKER_APPLICATION_STATUS_ORDER[item["application_status"]],
                tracker_date_sort_value(item["next_action_date"]),
                tracker_date_sort_value(item["last_update"], descending=True),
                tracker_id_number(item["id"]),
            ),
        )
    if section == "to_verify":
        status_order = {"apply": 0, "reviewing": 1, "not_started": 2}
        return sorted(
            items,
            key=lambda item: (
                status_order[item["application_status"]],
                -score_priority(item),
                tracker_date_sort_value(item["found_at"], descending=True),
                tracker_id_number(item["id"]),
            ),
        )
    if section == "archive":
        return sorted(
            items,
            key=lambda item: (
                tracker_date_sort_value(item["last_update"], descending=True),
                -tracker_id_number(item["id"]),
            ),
        )
    raise ValueError(f"unknown tracker section: {section}")


def tracker_payload(rows, source_references, application_cards):
    """Return a deterministic, exhaustive browser-tracker view model."""
    sections = {section: [] for section in TRACKER_SECTION_ORDER}
    for row in rows:
        section = tracker_section(row)
        sections[section].append(tracker_item(row, source_references, application_cards))
    sections = {section: sort_tracker_items(section, sections[section]) for section in TRACKER_SECTION_ORDER}
    counts = {section: len(sections[section]) for section in TRACKER_SECTION_ORDER}
    if sum(counts.values()) != len(rows):
        raise ValueError("tracker section counts do not cover every canonical job")
    return {
        "dataset_updated": max((row["last_update"] for row in rows if row["last_update"]), default=None),
        "jobs_total": len(rows),
        "section_order": list(TRACKER_SECTION_ORDER),
        "counts": counts,
        "sections": sections,
    }


def markdown_escape(value):
    """Treat canonical values as plain data, never as Markdown syntax."""
    value = re.sub(r"[\r\n]+", " ", str(value or ""))
    for character in ("\\", "|", "<", ">", "`", "[", "]", "*", "_"):
        value = value.replace(character, f"\\{character}")
    return value


def markdown_url(url):
    """Return a safe Markdown link destination for an already validated http(s) URL."""
    if not url or not valid_http_url(url):
        return None
    return quote(url, safe=":/?&=#%+,-._~!$'()*@;")


def tracker_vacancy_cell(item):
    label = f"{markdown_escape(item['company'])} — {markdown_escape(item['role'])}"
    url = markdown_url(item["vacancy_url"])
    vacancy = f"[{label}](<{url}>)" if url else label
    return f"{vacancy} · {markdown_escape(item['id'])}"


def tracker_card_cell(item):
    path = item["application_card"]
    if not path:
        return "—"
    return f"[Open](../{quote(path, safe='/-._~')})"


def tracker_table(headers, rows):
    if not rows:
        return "No jobs.\n"
    separator = "| " + " | ".join("---" for _header in headers) + " |"
    lines = [
        "| " + " | ".join(headers) + " |",
        separator,
        *("| " + " | ".join(row) + " |" for row in rows),
    ]
    return "\n".join(lines) + "\n"


def render_tracker_markdown(payload):
    """Render the complete canonical browser view with a final newline."""
    counts = payload["counts"]
    updated = payload["dataset_updated"] or "—"
    navigation = " · ".join(
        f"[{TRACKER_SECTION_TITLES[section]} ({counts[section]})](#{TRACKER_SECTION_TITLES[section].lower().replace(' ', '-')})"
        for section in TRACKER_SECTION_ORDER
    )
    parts = [
        "# Job tracker\n",
        "> Generated from [`data/jobs.csv`](../data/jobs.csv). Do not edit manually.\n",
        f"Dataset updated: **{updated}** · Jobs: **{payload['jobs_total']}**\n",
        f"{navigation}\n",
        "## Action now\n",
        tracker_table(
            ("Status", "Vacancy", "Match", "Next action", "Listing", "Card"),
            [
                (
                    markdown_escape(item["case_status_display"]),
                    tracker_vacancy_cell(item),
                    markdown_escape(item["match_score"] or "—"),
                    markdown_escape(item["next_action_display"]),
                    markdown_escape(item["listing_display"]),
                    tracker_card_cell(item),
                )
                for item in payload["sections"]["action_now"]
            ],
        ),
        "## Applications\n",
        tracker_table(
            ("Status", "Vacancy", "Stage", "Applied", "Next action", "Card"),
            [
                (
                    markdown_escape(item["case_status_display"]),
                    tracker_vacancy_cell(item),
                    markdown_escape(item["stage_reached"] or "—"),
                    markdown_escape(item["applied_at"] or "—"),
                    markdown_escape(item["next_action_display"]),
                    tracker_card_cell(item),
                )
                for item in payload["sections"]["applications"]
            ],
        ),
        "## To verify\n",
        tracker_table(
            ("Status", "Vacancy", "Need", "Match", "Next action", "Last checked"),
            [
                (
                    markdown_escape(item["case_status_display"]),
                    tracker_vacancy_cell(item),
                    markdown_escape(item["need_display"]),
                    markdown_escape(item["match_score"] or "—"),
                    markdown_escape(
                        tracker_action_display(
                            item["next_action"],
                            item["next_action_date"],
                            fallback="verify first-party",
                        )
                    ),
                    markdown_escape(item["verified_at"] or "Never"),
                )
                for item in payload["sections"]["to_verify"]
            ],
        ),
        "## Archive\n",
        "<details>\n\n",
        f"<summary>Archive ({counts['archive']})</summary>\n\n",
        tracker_table(
            ("Status", "Vacancy", "Decision", "Listing", "Updated"),
            [
                (
                    markdown_escape(item["case_status_display"]),
                    tracker_vacancy_cell(item),
                    markdown_escape(item["decision_display"]),
                    markdown_escape(item["listing_display"]),
                    markdown_escape(item["last_update"]),
                )
                for item in payload["sections"]["archive"]
            ],
        ),
        "\n</details>\n",
    ]
    return "\n\n".join(part.rstrip("\n") for part in parts) + "\n"


def write_or_check_tracker(markdown, check):
    """Atomically write the generated artifact or compare it byte-for-byte."""
    expected = markdown.encode("utf-8")
    if check:
        return PATHS.tracker_path.exists() and PATHS.tracker_path.read_bytes() == expected
    PATHS.tracker_path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix="tracker-", suffix=".md", dir=PATHS.tracker_path.parent
    )
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(expected)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_name, PATHS.tracker_path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return True


def index_tsv_value(value):
    """A tab or newline in a cell would silently corrupt a naive TSV read;
    company/role text is single-line by contract, but this stays defensive."""
    return (value or "").replace("\t", " ").replace("\n", " ").replace("\r", " ")


def render_known_index(rows):
    """Compact company/role dedup hint (docs/agent-write-path-plan-2026-09-07.md,
    Э6): no URLs, so it is not the exact-match dedup key — that's keys.tsv."""
    lines = ["id\tcompany\trole\tapplication_status\tlisting_status\tdecision_reason"]
    for row in sorted(rows, key=lambda item: item["id"]):
        lines.append(
            "\t".join(
                index_tsv_value(row[field])
                for field in (
                    "id",
                    "company",
                    "role",
                    "application_status",
                    "listing_status",
                    "decision_reason",
                )
            )
        )
    return ("\n".join(lines) + "\n").encode("utf-8")


def index_reference_key(reference):
    source_job_id = (reference.get("source_job_id") or "").strip()
    return source_job_id if source_job_id else norm_url(reference.get("source_url") or "")


def index_common_prefix(values):
    """Longest shared prefix across a source's keys, cut back to the last `/`
    so a stripped suffix stays a readable path fragment rather than an
    arbitrary substring."""
    if len(values) < 2:
        return ""
    prefix = values[0]
    for value in values[1:]:
        while not value.startswith(prefix):
            prefix = prefix[:-1]
            if not prefix:
                return ""
    cut = prefix.rfind("/")
    return prefix[: cut + 1] if cut >= 0 else ""


def render_keys_index(source_rows):
    """Exact-match dedup key per source reference (docs/agent-write-path-plan-
    2026-09-07.md, Э6): source_job_id when known, else normalized source_url.
    Grouped by source with the group's common URL prefix stripped to keep the
    file small; every reference in job_sources.csv is included, not just the
    one recorded on jobs.csv, since a confirmed duplicate may add another."""
    by_source = {}
    for reference in source_rows:
        key = index_reference_key(reference)
        if not key:
            continue
        by_source.setdefault(reference["source"], []).append((reference["job_id"], key))
    blocks = []
    for source in sorted(by_source):
        entries = sorted(by_source[source])
        prefix = index_common_prefix([key for _, key in entries])
        blocks.append(f"# {index_tsv_value(source)}\tprefix={prefix}")
        for job_id, key in entries:
            blocks.append(f"{job_id}\t{key[len(prefix) :]}")
    return ("\n".join(blocks) + "\n").encode("utf-8") if blocks else b""


ACTIVE_INDEX_APPLICATION_STATUSES = {"reviewing", "apply", "applied", "interviewing", "offer"}


def is_active_index_row(row):
    """docs/agent-write-path-plan-2026-09-07.md, Э6: reviewing/apply/applied/
    interviewing/offer, plus not_started with no decision_reason yet. Unlike
    is_active_candidate(), this ignores listing_status: an already-applied or
    interviewing job still belongs in the bootstrap slice even after its
    listing closes, since the application itself is still in flight."""
    if row["application_status"] in ACTIVE_INDEX_APPLICATION_STATUSES:
        return True
    return row["application_status"] == "not_started" and not row["decision_reason"]


def render_active_index(rows):
    """All canonical fields for the active slice."""
    active_rows = sorted((row for row in rows if is_active_index_row(row)), key=lambda item: item["id"])
    buffer = StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows({key: row.get(key) or "" for key in FIELDS} for row in active_rows)
    return buffer.getvalue().encode("utf-8")


def write_or_check_index_file(path, data, check):
    """Atomically write a generated index artifact, or compare it byte-for-
    byte (same exact-freshness contract as write_or_check_tracker)."""
    if check:
        return path.exists() and path.read_bytes() == data
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(prefix=f"{path.stem}-", suffix=path.suffix, dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as file:
            file.write(data)
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_name, path)
    except BaseException:
        Path(temporary_name).unlink(missing_ok=True)
        raise
    return True


def stale_entries(rows, days, reference_date):
    cutoff = reference_date - timedelta(days=days)
    entries = []
    for row in rows:
        if not is_active_candidate(row):
            continue
        verified_at = parsed_row_date(row["verified_at"])
        if verified_at is None:
            entries.append({"job": row, "reason": "never_verified", "age_days": None})
        elif verified_at < cutoff:
            entries.append(
                {
                    "job": row,
                    "reason": "verification_expired",
                    "age_days": (reference_date - verified_at).days,
                }
            )
    return entries


def score_priority(row):
    try:
        return float(row["match_score"])
    except (TypeError, ValueError):
        return 0.0


def todo_item(row, item_date="", reason=None):
    return {
        "id": row["id"],
        "company": row["company"],
        "role": row["role"],
        "date": item_date,
        "priority": score_priority(row) or None,
        "application_status": row["application_status"],
        "listing_status": row["listing_status"],
        "stage_reached": row["stage_reached"],
        "next_action": row["next_action"],
        "reason": reason,
    }


def sorted_todo_items(items):
    return sorted(
        items,
        key=lambda item: (item["date"] or "9999-12-31", -float(item["priority"] or 0), item["id"]),
    )


def todo_sections(rows, reference_date, stale_days=DEFAULT_STALE_DAYS):
    reference = reference_date.isoformat()
    sections = {key: [] for key, _title in TODO_SECTION_ORDER}
    stale_by_id = {entry["job"]["id"]: entry for entry in stale_entries(rows, stale_days, reference_date)}
    interview_stages = {"Recruiter screen", "Tech interview", "Test task", "Final interview"}
    for row in rows:
        action_date = row["next_action_date"]
        if action_date and action_date < reference:
            sections["overdue"].append(todo_item(row, action_date))
        elif action_date == reference:
            sections["today"].append(todo_item(row, action_date))
        if "follow-up" in (row["next_action"] or "").casefold() and (
            not action_date or action_date > reference
        ):
            sections["follow_ups"].append(todo_item(row, action_date))
        if row["application_status"] == "apply":
            sections["apply_not_submitted"].append(todo_item(row, action_date))
        if row["application_status"] == "reviewing" and row["id"] in stale_by_id:
            stale = stale_by_id[row["id"]]
            stale_date = row["verified_at"] or row["last_update"]
            sections["stale_review"].append(todo_item(row, stale_date, stale["reason"]))
        if is_active_candidate(row) and (
            row["first_party_verified"] != "yes" or row["apply_verified"] != "yes"
        ):
            sections["verification_queue"].append(todo_item(row, action_date or row["last_update"]))
        if is_active_candidate(row) and row["stage_reached"] in interview_stages:
            sections["upcoming_interview_test"].append(todo_item(row, action_date or row["response_at"]))
    return {key: sorted_todo_items(items) for key, items in sections.items()}


def filter_todo_rows(rows, *, source=None, id_range=None):
    """Restrict the read-only queue without changing its classification rules."""
    return [
        row
        for row in rows
        if (source is None or row["source"] == source) and (id_range is None or id_range.contains(row["id"]))
    ]


def percent(numerator, denominator):
    return round(numerator / denominator * 100, 1) if denominator else None


def stats_payload(rows, reference_date, stale_days=DEFAULT_STALE_DAYS):
    """Return the complete structured source for daily and weekly reporting."""
    active = [row for row in rows if is_active_candidate(row)]
    stale = stale_entries(rows, stale_days, reference_date)
    applied = [row for row in rows if row["applied_at"]]
    responses = [row for row in rows if row["response_at"]]
    fully_verified = [
        row for row in active if row["first_party_verified"] == "yes" and row["apply_verified"] == "yes"
    ]
    funnel = []
    for stage in STAGES[1:]:
        reached = sum(STAGES.index(row["stage_reached"] or "None") >= STAGES.index(stage) for row in rows)
        funnel.append(
            {"stage": stage, "reached": reached, "percent_of_applications": percent(reached, len(applied))}
        )
    sources = []
    for source in SOURCES:
        source_rows = [row for row in rows if row["source"] == source]
        if source_rows:
            source_applied = sum(bool(row["applied_at"]) for row in source_rows)
            source_responses = sum(bool(row["response_at"]) for row in source_rows)
            sources.append(
                {
                    "source": source,
                    "found": len(source_rows),
                    "applied": source_applied,
                    "responses": source_responses,
                    "response_rate": percent(source_responses, source_applied),
                }
            )
    cv_versions = []
    for version in sorted({row["cv_version"] for row in rows if row["cv_version"]} | {"not recorded"}):
        version_rows = [row for row in applied if (row["cv_version"] or "not recorded") == version]
        if version_rows:
            version_responses = sum(bool(row["response_at"]) for row in version_rows)
            cv_versions.append(
                {
                    "cv_version": version,
                    "applied": len(version_rows),
                    "responses": version_responses,
                    "response_rate": percent(version_responses, len(version_rows)),
                }
            )
    stale_items = [
        {
            "id": entry["job"]["id"],
            "verified_at": entry["job"]["verified_at"],
            "reason": entry["reason"],
            "age_days": entry["age_days"],
        }
        for entry in sorted(
            stale, key=lambda entry: (entry["job"]["verified_at"] or "0000-00-00", entry["job"]["id"])
        )
    ]
    state_order = [
        "Not started",
        "Reviewing",
        "Apply",
        "Applied",
        "Interviewing",
        "Offer",
        "Rejected",
        "Ghosted",
        "Withdrawn",
        "Closed",
        "Duplicate",
        *(f"Skipped: {reason}" for reason in REASONS),
    ]
    derived_state_counts = {state: sum(derived_state(row) == state for row in rows) for state in state_order}
    return {
        "ok": True,
        "command": "stats",
        "as_of": reference_date.isoformat(),
        "jobs_total": len(rows),
        "application_status": {
            status: sum(row["application_status"] == status for row in rows)
            for status in APPLICATION_STATUSES
        },
        "listing_status": {
            status: sum(row["listing_status"] == status for row in rows) for status in LISTING_STATUSES
        },
        "derived_state": {state: amount for state, amount in derived_state_counts.items() if amount},
        "derived": {
            "active_candidates": len(active),
            "skipped": sum(
                row["application_status"] == "not_started"
                and bool(row["decision_reason"])
                and row["decision_reason"] not in {"duplicate_listing", "closed_before_application"}
                for row in rows
            ),
            "closed_before_application": sum(
                row["application_status"] == "not_started" and row["listing_status"] == "closed"
                for row in rows
            ),
            "legacy_duplicates": sum(row["decision_reason"] == "duplicate_listing" for row in rows),
        },
        "verification": {
            "eligible_records": len(active),
            "first_party_verified": {
                value: sum(row["first_party_verified"] == value for row in active) for value in VERIFICATION
            },
            "apply_verified": {
                value: sum(row["apply_verified"] == value for row in active) for value in VERIFICATION
            },
            "fully_verified": len(fully_verified),
            "coverage_percent": percent(len(fully_verified), len(active)),
        },
        "stale": {"days": stale_days, "count": len(stale_items), "jobs": stale_items},
        "funnel": {
            "applications": len(applied),
            "responses": len(responses),
            "response_rate": percent(len(responses), len(applied)),
            "stages": funnel,
        },
        "sources": sources,
        "cv_versions": cv_versions,
        "decision_reasons": {
            reason: sum(row["decision_reason"] == reason for row in rows) for reason in REASONS
        },
    }
