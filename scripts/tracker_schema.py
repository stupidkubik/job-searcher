"""Canonical CSV schema, enums, and the exceptions the write path raises.

docs/agent-write-path-plan-2026-09-07.md, Э10. Self-contained: everything
here is a constant, an exception, or a pure function of its arguments, with
no filesystem access, so every other tracker_*.py module can depend on this
one without risk of a cycle.
"""

import re
import sys
import unicodedata
from dataclasses import dataclass
from urllib.parse import urlsplit


FIELDS = [
    "id",
    "application_status",
    "listing_status",
    "company",
    "role",
    "level",
    "original_url",
    "source_url",
    "source",
    "location",
    "remote_policy",
    "stack",
    "salary",
    "posted_at",
    "found_at",
    "match_score",
    "stage_reached",
    "decision_reason",
    "applied_at",
    "response_at",
    "next_action",
    "next_action_date",
    "cv_version",
    "cover_letter",
    "contact_name",
    "contact_url",
    "verified_at",
    "first_party_verified",
    "apply_verified",
    "last_update",
    "notes",
]

JOB_SOURCE_FIELDS = ["job_id", "source", "source_url", "source_job_id", "found_at"]

REQUIRED = [
    "id",
    "company",
    "role",
    "source",
    "found_at",
    "application_status",
    "listing_status",
    "stage_reached",
    "first_party_verified",
    "apply_verified",
    "last_update",
]

DATE_FIELDS = [
    "posted_at",
    "found_at",
    "applied_at",
    "response_at",
    "next_action_date",
    "verified_at",
    "last_update",
]

APPLICATION_STATUSES = [
    "not_started",
    "reviewing",
    "apply",
    "applied",
    "interviewing",
    "offer",
    "rejected",
    "ghosted",
    "withdrawn",
]

ADD_APPLICATION_STATUSES = ["not_started", "reviewing", "apply"]

ADD_INPUT_FIELDS = {
    "company",
    "role",
    "source",
    "application_status",
    "listing_status",
    "first_party_verified",
    "apply_verified",
    "level",
    "remote_policy",
    "original_url",
    "source_url",
    "location",
    "stack",
    "salary",
    "posted_at",
    "found_at",
    "match_score",
    "decision_reason",
    "notes",
    "source_job_id",
}

ADD_REQUIRED_INPUT_FIELDS = {"company", "role", "source"}

LISTING_STATUSES = ["open", "closed", "unknown"]

VERIFICATION = ["yes", "no", "unknown"]

STAGES = ["None", "Applied", "Recruiter screen", "Tech interview", "Test task", "Final interview", "Offer"]

LEVELS = [
    "Intern",
    "Graduate",
    "Junior",
    "Junior+",
    "Associate",
    "Junior/Middle",
    "Middle",
    "Senior",
    "Lead",
    "Unknown",
]

REMOTE = ["Global", "Europe", "EMEA", "Serbia", "Country-specific", "Hybrid", "On-site", "Unclear"]

SOURCES = [
    "Hirify",
    "Jaabz",
    "LinkedIn",
    "Welcome to the Jungle",
    "We Work Remotely",
    "HiringCafe",
    "Hacker News — Who is Hiring?",
    "Hacker News — Who Wants to Be Hired?",
    "YC Work at a Startup",
    "Wellfound",
    "HelloWorld.rs",
    "Reactiflux Discord",
    "Find My Remote / Telegram",
    "Telegram",
    "Himalayas",
    "Startit Jobs",
    "Hired Valley",
    "Relocate.me",
    "Remote OK",
    "Geekjob",
    "TalentMove",
    "Company Careers",
    "Referral",
    "Manual",
    "Other",
]

SOURCES_ALLOWING_SHARED_DISCOVERY_URLS = {"Telegram"}

REASONS = [
    "geo_restriction",
    "work_authorization",
    "seniority_too_high",
    "seniority_too_low",
    "stack_mismatch",
    "role_not_frontend",
    "salary_too_low",
    "company_not_interesting",
    "closed_before_application",
    "already_applied",
    "duplicate_listing",
    "no_response_timeout",
    "withdrawn_by_me",
    "other",
]

NEEDS_APPLIED_AT = {"applied", "interviewing", "offer", "rejected", "ghosted", "withdrawn"}

RESPONDED_APPLICATION_STATUSES = {"interviewing", "offer", "rejected"}

PRE_APPLICATION_REASONS = set(REASONS) - {"no_response_timeout", "withdrawn_by_me"}

SCREEN_REASONS = PRE_APPLICATION_REASONS - {"closed_before_application", "duplicate_listing"}

SET_PROTECTED = {
    "id",
    "stage_reached",
    "verified_at",
    "last_update",
    "application_status",
    "applied_at",
    "response_at",
    "decision_reason",
}

VERIFY_ENRICHMENT_FIELDS = {"level", "remote_policy", "stack", "salary", "match_score"}

ENUMS = {
    "application_status": APPLICATION_STATUSES,
    "listing_status": LISTING_STATUSES,
    "first_party_verified": VERIFICATION,
    "apply_verified": VERIFICATION,
    "stage_reached": STAGES,
    "level": LEVELS,
    "remote_policy": REMOTE,
    "source": SOURCES,
    "decision_reason": REASONS,
}

GHOST_AFTER_DAYS = 30

SOURCES_WITHOUT_EXTERNAL_REFERENCE = {"Manual", "Referral"}

TERMINAL_APPLICATION_STATUSES = {"rejected", "ghosted", "withdrawn"}

PRE_APPLICATION_STATUSES = {"not_started", "reviewing", "apply"}

IN_PROGRESS_APPLICATION_STATUSES = {"reviewing", "apply"}

DEFAULT_STALE_DAYS = 7

INGEST_RESOLUTION_VERSION = 1

INGEST_RESOLUTION_DECISIONS = {"separate", "duplicate"}


class UnresolvedDuplicate(Exception):
    """Нужна явная команда пользователя: duplicate или force."""

    def __init__(self, candidates):
        self.candidates = candidates


class SourceReferenceConflict(Exception):
    """Source reference already belongs to another canonical job.

    `message` is Russian and may name a CLI flag (`jobs.py`'s own ingest/add
    commands print it as-is); `message_en` is the flag-free English text
    agent_operations.add_conflict_details() puts in a connector-facing
    conflict result (docs/agent-write-path-plan-2026-09-07.md, Э8).
    """

    def __init__(self, message, existing, *, message_en=None):
        self.message = message
        self.existing = existing
        self.message_en = message if message_en is None else message_en


class ValidationError(Exception):
    """A rejected write reachable from the connector path.

    Raised instead of calling die() so agent_operations.execute() can catch it
    and record a machine-readable rejected result. Two addressees, one
    exception (docs/agent-write-path-plan-2026-09-07.md, Э8): the connector
    only ever sees `message_en`/`agent_hint` (English, no CLI flags — it has
    no CLI); the human CLI user sees `cli_hint_ru`, which may name flags. The
    CLI still catches this at the top of main() and prints it via die(); since
    __str__ returns cli_hint_ru, that call site needs no change.
    """

    def __init__(
        self,
        message_en,
        *,
        code="invariant_violation",
        field=None,
        allowed=None,
        agent_hint=None,
        cli_hint_ru=None,
    ):
        self.message_en = message_en
        self.code = code
        self.field = field
        self.allowed = allowed
        self.agent_hint = agent_hint
        self.cli_hint_ru = message_en if cli_hint_ru is None else cli_hint_ru
        super().__init__(self.cli_hint_ru)

    def __str__(self):
        return self.cli_hint_ru

    def to_payload(self):
        payload = {"code": self.code, "layer": "jobs", "message": self.message_en}
        if self.field is not None:
            payload["field"] = self.field
        if self.allowed is not None:
            payload["allowed"] = self.allowed
        if self.agent_hint is not None:
            payload["hint"] = self.agent_hint
        return payload


@dataclass(frozen=True)
class JobIdRange:
    start: int
    end: int

    def contains(self, job_id):
        match = re.fullmatch(r"job-(\d{4,})", job_id or "")
        return bool(match and self.start <= int(match.group(1)) <= self.end)

    def display(self):
        return f"job-{self.start:04d}:job-{self.end:04d}"


def die(message):
    print(f"error: {message}", file=sys.stderr)
    raise SystemExit(1)


def norm(text):
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(char for char in text if not unicodedata.combining(char)).lower()
    return re.sub(r"\s+", " ", "".join(char if char.isalnum() else " " for char in text)).strip()


def slug(value):
    return norm(value).replace(" ", "-")[:28].strip("-")


def next_id(rows):
    numbers = [
        int(match.group(1)) for row in rows if (match := re.fullmatch(r"job-(\d{4,})", row["id"] or ""))
    ]
    return f"job-{max(numbers, default=0) + 1:04d}"


def find(rows, job_id):
    for row in rows:
        if row["id"] == job_id:
            return row
    die(f"запись {job_id} не найдена")


def valid_http_url(value):
    try:
        parts = urlsplit(value)
        return parts.scheme in {"http", "https"} and bool(parts.netloc)
    except ValueError:
        return False


def clean_value(value):
    return str(value or "").replace("\n", " ")
