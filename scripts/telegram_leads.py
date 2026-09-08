#!/usr/bin/env python3
"""Pure Telegram lead domain and private local storage helpers.

The module deliberately has no Telethon dependency.  Telegram message text is
kept only in private lead batches; projections into ``data/inbox`` contain
only facts explicitly confirmed by a human and minimal provenance.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import secrets
import tempfile
import unicodedata
from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo


LEAD_SCHEMA_VERSION = 1
STATE_VERSION = 1
SOURCE_NAME = "Telegram"
DATA_DIR_ENV = "JOB_TRACKER_TELEGRAM_DIR"
BUSINESS_TIMEZONE = ZoneInfo("Europe/Belgrade")
URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)
LEAD_REQUIRED_FIELDS = frozenset(
    {
        "schema_version",
        "message_identity",
        "peer_id",
        "message_id",
        "channel_title",
        "channel_username",
        "posted_at",
        "edited_at",
        "found_at",
        "permalink",
        "text",
        "outbound_urls",
        "matched_terms",
        "forwarded_from",
    }
)


class TelegramLeadError(ValueError):
    """A Telegram lead or its private local storage violates the contract."""


class _ImmutableBatchCollision(TelegramLeadError):
    """The collision-safe filename allocator must try another final name."""


def _integer(value: Any, label: str, *, positive: bool) -> int:
    if isinstance(value, bool):
        raise TelegramLeadError(f"{label} must be an integer, not bool")
    if isinstance(value, int):
        result = value
    elif isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        result = int(value.strip())
    else:
        raise TelegramLeadError(f"{label} must be an integer")
    if (positive and result <= 0) or (not positive and result == 0):
        qualifier = "positive" if positive else "non-zero"
        raise TelegramLeadError(f"{label} must be a {qualifier} integer")
    return result


def normalize_peer_id(value: Any) -> int:
    """Return the authoritative non-zero numeric Telegram peer ID."""
    return _integer(value, "peer_id", positive=False)


def normalize_message_id(value: Any) -> int:
    """Return a positive Telegram message ID."""
    return _integer(value, "message_id", positive=True)


def message_identity(peer_id: Any, message_id: Any) -> str:
    return f"telegram:{normalize_peer_id(peer_id)}:{normalize_message_id(message_id)}"


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TelegramLeadError(f"{label} must be a non-empty string")
    return value.strip()


def _http_url(value: Any, label: str) -> str:
    value = _required_text(value, label)
    try:
        parsed = urlsplit(value)
    except ValueError as error:
        raise TelegramLeadError(f"{label} must be an absolute HTTP(S) URL") from error
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.netloc:
        raise TelegramLeadError(f"{label} must be an absolute HTTP(S) URL")
    return value


def _utc_timestamp(value: datetime | str | None, label: str, *, optional: bool = False) -> str | None:
    if value is None:
        if optional:
            return None
        raise TelegramLeadError(f"{label} is required")
    if isinstance(value, str):
        raw = value.strip()
        if not raw:
            raise TelegramLeadError(f"{label} must be a timestamp")
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError as error:
            raise TelegramLeadError(f"{label} must be an ISO-8601 timestamp") from error
    elif isinstance(value, datetime):
        parsed = value
    else:
        raise TelegramLeadError(f"{label} must be a datetime or ISO-8601 timestamp")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise TelegramLeadError(f"{label} must include a timezone")
    return parsed.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _calendar_date(value: date | datetime | str, label: str) -> str:
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise TelegramLeadError(f"{label} datetime must include a timezone")
        result = value.astimezone(BUSINESS_TIMEZONE).date()
    elif isinstance(value, date):
        result = value
    elif isinstance(value, str):
        try:
            result = date.fromisoformat(value.strip())
        except (AttributeError, ValueError) as error:
            raise TelegramLeadError(f"{label} must have YYYY-MM-DD format") from error
    else:
        raise TelegramLeadError(f"{label} must be a date")
    return result.isoformat()


def _entity_value(entity: Any, name: str, default: Any = None) -> Any:
    return entity.get(name, default) if isinstance(entity, Mapping) else getattr(entity, name, default)


def _utf16_slice(text: str, offset: int, length: int) -> str:
    """Slice by Telegram's UTF-16 code-unit entity offsets."""
    if offset < 0 or length <= 0:
        return ""
    encoded = text.encode("utf-16-le")
    start, end = offset * 2, (offset + length) * 2
    try:
        return encoded[start:end].decode("utf-16-le")
    except UnicodeDecodeError:
        return ""


def extract_http_urls(text: str | None, entities: Iterable[Any] = ()) -> list[str]:
    """Extract unique HTTP(S) URLs from Telegram entities, then regex text.

    Entity objects may be Telethon-like objects or plain fixture mappings.  A
    text-url entity supplies ``url``; a normal URL entity supplies UTF-16
    ``offset`` and ``length``.
    """
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise TelegramLeadError("text must be a string")
    candidates: list[str] = []
    for entity in entities or ():
        candidate = _entity_value(entity, "url")
        if not candidate:
            offset, length = _entity_value(entity, "offset"), _entity_value(entity, "length")
            if isinstance(offset, int) and isinstance(length, int):
                candidate = _utf16_slice(text, offset, length)
        if isinstance(candidate, str):
            candidates.append(candidate)
    candidates.extend(match.group(0).rstrip(".,;:!?)]}") for match in URL_PATTERN.finditer(text))

    urls: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        try:
            url = _http_url(candidate, "entity URL")
        except TelegramLeadError:
            continue
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


def match_keywords(text: str | None, terms: Iterable[str]) -> list[str]:
    """Return configured terms found case-insensitively, in configured order."""
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise TelegramLeadError("text must be a string")
    folded_text = unicodedata.normalize("NFKC", text).casefold()
    matches: list[str] = []
    seen: set[str] = set()
    for term in terms:
        normalized = _required_text(term, "keyword")
        key = unicodedata.normalize("NFKC", normalized).casefold()
        if key in folded_text and key not in seen:
            seen.add(key)
            matches.append(normalized)
    return matches


def build_lead(
    *,
    peer_id: Any,
    message_id: Any,
    channel_title: str,
    posted_at: datetime | str,
    found_at: date | datetime | str,
    permalink: str,
    text: str | None,
    channel_username: str | None = None,
    entities: Iterable[Any] = (),
    matched_terms: Iterable[str] = (),
    forwarded_from: Mapping[str, Any] | None = None,
    edited_at: datetime | str | None = None,
) -> dict[str, Any]:
    """Build and validate one network-independent private lead record."""
    normalized_peer = normalize_peer_id(peer_id)
    normalized_message = normalize_message_id(message_id)
    if text is None:
        text = ""
    if not isinstance(text, str):
        raise TelegramLeadError("text must be a string")
    if channel_username is not None:
        channel_username = _required_text(channel_username, "channel_username").lstrip("@")
    if forwarded_from is not None and not isinstance(forwarded_from, Mapping):
        raise TelegramLeadError("forwarded_from must be a JSON object or null")
    forwarded = dict(forwarded_from) if forwarded_from is not None else None
    try:
        json.dumps(forwarded, ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise TelegramLeadError("forwarded_from must be JSON serializable") from error
    terms = [_required_text(term, "matched term") for term in matched_terms]
    terms = list(dict.fromkeys(terms))
    lead = {
        "schema_version": LEAD_SCHEMA_VERSION,
        "message_identity": message_identity(normalized_peer, normalized_message),
        "peer_id": normalized_peer,
        "message_id": normalized_message,
        "channel_title": _required_text(channel_title, "channel_title"),
        "channel_username": channel_username,
        "posted_at": _utc_timestamp(posted_at, "posted_at"),
        "edited_at": _utc_timestamp(edited_at, "edited_at", optional=True),
        "found_at": _calendar_date(found_at, "found_at"),
        "permalink": _http_url(permalink, "permalink"),
        "text": text,
        "outbound_urls": extract_http_urls(text, entities),
        "matched_terms": terms,
        "forwarded_from": forwarded,
    }
    return validate_lead(lead)


def validate_lead(lead: Mapping[str, Any]) -> dict[str, Any]:
    """Strictly validate and return a shallow copy of a lead record."""
    if not isinstance(lead, Mapping):
        raise TelegramLeadError("lead must be a JSON object")
    unknown = set(lead) - LEAD_REQUIRED_FIELDS
    missing = LEAD_REQUIRED_FIELDS - set(lead)
    if missing:
        raise TelegramLeadError(f"lead is missing fields: {', '.join(sorted(missing))}")
    if unknown:
        raise TelegramLeadError(f"lead has unknown fields: {', '.join(sorted(unknown))}")
    if lead["schema_version"] != LEAD_SCHEMA_VERSION:
        raise TelegramLeadError(f"unsupported lead schema_version: {lead['schema_version']!r}")
    peer_id = normalize_peer_id(lead["peer_id"])
    message_id = normalize_message_id(lead["message_id"])
    expected_identity = message_identity(peer_id, message_id)
    if lead["message_identity"] != expected_identity:
        raise TelegramLeadError(f"message_identity must be {expected_identity!r}")
    _required_text(lead["channel_title"], "channel_title")
    username = lead["channel_username"]
    if username is not None:
        _required_text(username, "channel_username")
    _utc_timestamp(lead["posted_at"], "posted_at")
    _utc_timestamp(lead["edited_at"], "edited_at", optional=True)
    _calendar_date(lead["found_at"], "found_at")
    _http_url(lead["permalink"], "permalink")
    if not isinstance(lead["text"], str):
        raise TelegramLeadError("text must be a string")
    if not isinstance(lead["outbound_urls"], list):
        raise TelegramLeadError("outbound_urls must be an array")
    urls = [_http_url(url, "outbound URL") for url in lead["outbound_urls"]]
    if len(urls) != len(set(urls)):
        raise TelegramLeadError("outbound_urls must not contain duplicates")
    if not isinstance(lead["matched_terms"], list):
        raise TelegramLeadError("matched_terms must be an array")
    for term in lead["matched_terms"]:
        _required_text(term, "matched term")
    forwarded = lead["forwarded_from"]
    if forwarded is not None and not isinstance(forwarded, dict):
        raise TelegramLeadError("forwarded_from must be a JSON object or null")
    try:
        json.dumps(dict(lead), ensure_ascii=False)
    except (TypeError, ValueError) as error:
        raise TelegramLeadError("lead must be JSON serializable") from error
    return dict(lead)


def _normalized_identity_text(value: str, label: str) -> str:
    value = _required_text(value, label)
    return " ".join(unicodedata.normalize("NFKC", value).casefold().split())


def vacancy_candidate_identity(
    peer_id: Any,
    message_id: Any,
    *,
    application_url: str | None = None,
    company: str | None = None,
    role: str | None = None,
) -> str:
    """Create a stable per-message vacancy identity from URL or company/role."""
    peer = normalize_peer_id(peer_id)
    message = normalize_message_id(message_id)
    if application_url is not None:
        material = _http_url(application_url, "application_url").encode("utf-8")
    else:
        if company is None or role is None:
            raise TelegramLeadError("company and role are required when application_url is absent")
        material = (
            _normalized_identity_text(company, "company") + "\0" + _normalized_identity_text(role, "role")
        ).encode("utf-8")
    digest = hashlib.sha256(material).hexdigest()
    return f"{peer}:{message}:sha256:{digest}"


def deduplicate_leads(
    leads: Iterable[Mapping[str, Any]],
    seen_identities: Iterable[str] = (),
) -> tuple[list[dict[str, Any]], int]:
    """Keep the first occurrence in deterministic input order."""
    seen = set(seen_identities)
    unique: list[dict[str, Any]] = []
    duplicates = 0
    for value in leads:
        lead = validate_lead(value)
        identity = lead["message_identity"]
        if identity in seen:
            duplicates += 1
            continue
        seen.add(identity)
        unique.append(lead)
    return unique, duplicates


def resolve_data_dir(
    explicit: str | os.PathLike[str] | None = None,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve private application data outside the checkout by default."""
    environment = os.environ if environ is None else environ
    configured = explicit if explicit is not None else environment.get(DATA_DIR_ENV)
    if configured is not None:
        path = Path(configured).expanduser()
    elif os.name == "nt" and environment.get("LOCALAPPDATA"):
        path = Path(environment["LOCALAPPDATA"]) / "job-tracker" / "telegram"
    elif environment.get("XDG_DATA_HOME"):
        path = Path(environment["XDG_DATA_HOME"]) / "job-tracker" / "telegram"
    else:
        path = Path.home() / ".local" / "share" / "job-tracker" / "telegram"
    return path.resolve()


def ensure_private_dir(path: str | os.PathLike[str]) -> Path:
    """Create or re-harden an owner-only directory for local Telegram data.

    Directories which already exist above the target are left untouched: they
    may be shared user directories this module has no mandate to change.
    """
    path = Path(path)
    if path.is_symlink():
        raise TelegramLeadError(f"private data directory must not be a symlink: {path}")
    missing: list[Path] = []
    probe = path
    while not probe.exists():
        missing.append(probe)
        if probe.parent == probe:
            break
        probe = probe.parent
    try:
        # ``mkdir(parents=True, mode=…)`` applies the mode to the final
        # component only, so every ancestor this call has to create is hardened
        # explicitly.  Otherwise credentials and raw message text end up under
        # world-traversable parents.
        for directory in list(reversed(missing)) or [path]:
            directory.mkdir(mode=0o700, exist_ok=True)
            os.chmod(directory, 0o700)
    except OSError as error:
        raise TelegramLeadError(f"cannot create private directory {path}: {error}") from error
    if not path.is_dir():
        raise TelegramLeadError(f"private data path is not a directory: {path}")
    return path


def _ensure_output_dir(path: Path, *, private: bool) -> Path:
    """Ensure a batch destination directory exists.

    ``private`` hardens the created path to owner-only and is for local
    Telegram storage.  ``data/inbox`` is a shared repository directory holding
    only human-confirmed facts, so publishing a batch there must not silently
    change permissions other adapters and the operator rely on.
    """
    if private:
        return ensure_private_dir(path)
    path = Path(path)
    if path.is_symlink():
        raise TelegramLeadError(f"output directory must not be a symlink: {path}")
    try:
        path.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise TelegramLeadError(f"cannot create directory {path}: {error}") from error
    if not path.is_dir():
        raise TelegramLeadError(f"output path is not a directory: {path}")
    return path


def _fsync_directory(path: Path) -> None:
    """Durably persist directory-entry changes where the OS supports it."""
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_write_json(path: Path, payload: Mapping[str, Any]) -> Path:
    parent = ensure_private_dir(path.parent)
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=parent)
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            json.dump(payload, file, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.replace(temporary_path, path)
        temporary_path = None
        try:
            _fsync_directory(parent)
        except OSError:
            pass
    except (OSError, TypeError, ValueError) as error:
        raise TelegramLeadError(f"cannot atomically write {path}: {error}") from error
    finally:
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return path


def _validate_allowlist(peer_ids: Iterable[Any]) -> list[int]:
    if isinstance(peer_ids, (str, bytes)):
        raise TelegramLeadError("allowlist must be an array of numeric peer IDs")
    normalized: list[int] = []
    for value in peer_ids:
        peer_id = normalize_peer_id(value)
        if peer_id not in normalized:
            normalized.append(peer_id)
    if not normalized:
        raise TelegramLeadError("allowlist must contain at least one numeric peer ID")
    return normalized


def write_allowlist(data_dir: str | os.PathLike[str], peer_ids: Iterable[Any]) -> Path:
    peers = _validate_allowlist(peer_ids)
    return _atomic_write_json(Path(data_dir) / "allowlist.json", {"version": 1, "peer_ids": peers})


def load_allowlist(data_dir: str | os.PathLike[str]) -> list[int]:
    path = Path(data_dir) / "allowlist.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise TelegramLeadError(f"allowlist is missing: {path}") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TelegramLeadError(f"cannot read allowlist {path}: {error}") from error
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 1
        or set(payload) != {"version", "peer_ids"}
    ):
        raise TelegramLeadError("allowlist must be an object with version=1 and peer_ids")
    return _validate_allowlist(payload["peer_ids"])


def load_state(data_dir: str | os.PathLike[str]) -> dict[str, Any]:
    path = Path(data_dir) / "state.json"
    if not path.exists():
        return {"version": STATE_VERSION, "peers": {}}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise TelegramLeadError(f"cannot read state {path}: {error}") from error
    if not isinstance(payload, dict) or set(payload) != {"version", "peers"}:
        raise TelegramLeadError("state must contain exactly version and peers")
    if payload["version"] != STATE_VERSION or not isinstance(payload["peers"], dict):
        raise TelegramLeadError(f"unsupported state version: {payload.get('version')!r}")
    for raw_peer, value in payload["peers"].items():
        peer = normalize_peer_id(raw_peer)
        if str(peer) != raw_peer or not isinstance(value, dict) or set(value) != {"last_message_id"}:
            raise TelegramLeadError(f"invalid cursor state for peer {raw_peer!r}")
        normalize_message_id(value["last_message_id"])
    return payload


@contextmanager
def pull_lock(data_dir: str | os.PathLike[str]) -> Iterator[Path]:
    """Hold the single nonblocking process-level pull lock for ``data_dir``.

    The lockfile intentionally remains in place after release.  Removing it
    would introduce an inode-replacement race where two processes could both
    believe they held the pull lock.
    """
    directory = ensure_private_dir(data_dir)
    path = directory / "pull.lock"
    flags = os.O_RDWR | os.O_CREAT
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
        os.fchmod(descriptor, 0o600)
    except OSError as error:
        raise TelegramLeadError(f"cannot open pull lock {path}: {error}") from error

    acquired = False
    try:
        if os.name == "nt":  # pragma: no cover - exercised on Windows runners.
            import msvcrt

            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b"\0")
                os.fsync(descriptor)
            os.lseek(descriptor, 0, os.SEEK_SET)
            try:
                msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
            except OSError as error:
                raise TelegramLeadError("another Telegram pull is already running") from error
        else:
            import fcntl

            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise TelegramLeadError("another Telegram pull is already running") from error
        acquired = True
        yield path
    finally:
        if acquired:
            if os.name == "nt":  # pragma: no cover - exercised on Windows runners.
                import msvcrt

                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _run_stamp(run_at: datetime | None) -> str:
    value = run_at or datetime.now(timezone.utc)
    if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
        raise TelegramLeadError("run_at must be a timezone-aware datetime")
    return value.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")


def _write_jsonl_exclusive(
    path: Path,
    records: Iterable[Mapping[str, Any]],
    *,
    private: bool = True,
) -> Path:
    """Durably publish a complete immutable JSONL file without overwrite.

    Bytes are first serialized into an owner-only hidden file in the same
    directory.  A hard link publishes the complete inode atomically and, unlike
    ``replace``, fails if the final name already exists.

    ``private`` selects whether the destination directory is owner-only local
    storage or a shared repository directory; it never affects publication.
    """
    parent = _ensure_output_dir(path.parent, private=private)
    temporary_path: Path | None = None
    descriptor: int | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{path.name}.",
            suffix=".tmp",
            dir=parent,
        )
        temporary_path = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as file:
            descriptor = None
            for record in records:
                file.write(json.dumps(record, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
                file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        # link(2) is an atomic no-overwrite publication of the fully fsynced
        # inode.  The final path is never visible with partial JSONL bytes.
        os.link(temporary_path, path)
        temporary_path.unlink()
        temporary_path = None
        _fsync_directory(parent)
    except FileExistsError as error:
        raise _ImmutableBatchCollision(f"immutable batch already exists: {path}") from error
    except (OSError, TypeError, ValueError) as error:
        raise TelegramLeadError(f"cannot write immutable batch {path}: {error}") from error
    finally:
        if descriptor is not None:
            os.close(descriptor)
        if temporary_path is not None:
            try:
                temporary_path.unlink()
            except FileNotFoundError:
                pass
    return path


def write_lead_batch(
    data_dir: str | os.PathLike[str],
    leads: Iterable[Mapping[str, Any]],
    *,
    run_at: datetime | None = None,
) -> Path:
    records = [validate_lead(lead) for lead in leads]
    leads_dir = ensure_private_dir(Path(data_dir) / "leads")
    for _attempt in range(10):
        path = leads_dir / f"telegram-leads-{_run_stamp(run_at)}-{secrets.token_hex(4)}.jsonl"
        try:
            return _write_jsonl_exclusive(path, records)
        except _ImmutableBatchCollision:
            continue
    raise TelegramLeadError("could not allocate a collision-safe immutable lead batch name")


def _read_lead_batch(path: Path) -> list[dict[str, Any]]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeDecodeError) as error:
        raise TelegramLeadError(f"cannot read lead batch {path}: {error}") from error
    leads: list[dict[str, Any]] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise TelegramLeadError(f"{path}:{line_number}: empty JSONL line")
        try:
            value = json.loads(line)
            leads.append(validate_lead(value))
        except (json.JSONDecodeError, TelegramLeadError) as error:
            raise TelegramLeadError(f"{path}:{line_number}: invalid lead: {error}") from error
    return leads


def iter_stored_leads(data_dir: str | os.PathLike[str]):
    leads_dir = Path(data_dir) / "leads"
    if not leads_dir.exists():
        return
    for path in sorted(leads_dir.glob("telegram-leads-*.jsonl")):
        yield from _read_lead_batch(path)


def load_seen_identities(data_dir: str | os.PathLike[str]) -> set[str]:
    return {lead["message_identity"] for lead in iter_stored_leads(data_dir)}


def commit_lead_batch(
    data_dir: str | os.PathLike[str],
    leads: Iterable[Mapping[str, Any]],
    cursor_updates: Mapping[Any, Any],
    *,
    run_at: datetime | None = None,
    before_state_write: Callable[[Path], None] | None = None,
) -> Path:
    """Write an immutable batch, then atomically advance per-peer cursors.

    ``before_state_write`` is a fault-injection/test hook invoked after the
    durable batch write.  If it raises, state remains unchanged and a retry is
    safe because message identities deduplicate against the stored batch.
    """
    if not isinstance(cursor_updates, Mapping):
        raise TelegramLeadError("cursor_updates must map peer IDs to message IDs")
    state = load_state(data_dir)
    updated_state = json.loads(json.dumps(state))
    for raw_peer, raw_message in cursor_updates.items():
        peer, message = normalize_peer_id(raw_peer), normalize_message_id(raw_message)
        current = updated_state["peers"].get(str(peer), {}).get("last_message_id", 0)
        updated_state["peers"][str(peer)] = {"last_message_id": max(current, message)}
    batch_path = write_lead_batch(data_dir, leads, run_at=run_at)
    if before_state_write is not None:
        before_state_write(batch_path)
    _atomic_write_json(Path(data_dir) / "state.json", updated_state)
    return batch_path


def find_lead(data_dir: str | os.PathLike[str], identity: str) -> dict[str, Any]:
    identity = _required_text(identity, "identity")
    matches = [lead for lead in iter_stored_leads(data_dir) if lead["message_identity"] == identity]
    if len(matches) != 1:
        raise TelegramLeadError(f"expected exactly one lead for {identity!r}, found {len(matches)}")
    return matches[0]


def lead_summary(lead: Mapping[str, Any], *, include_text: bool = False) -> dict[str, Any]:
    value = validate_lead(lead)
    summary = {key: item for key, item in value.items() if key != "text"}
    if include_text:
        summary["text"] = value["text"]
    return summary


def project_confirmed_lead(
    lead: Mapping[str, Any],
    *,
    company: str,
    role: str,
    application_url: str,
    raw_location: str,
    found_at: date | datetime | str | None = None,
) -> dict[str, Any]:
    """Project human-confirmed facts without copying private message text."""
    value = validate_lead(lead)
    application_url = _http_url(application_url, "application_url")
    confirmed_company = _required_text(company, "company")
    confirmed_role = _required_text(role, "role")
    # The URL branch is reserved for an exact outbound URL captured in the
    # Telegram message.  A human-supplied Apply URL cannot retroactively change
    # the discovered vacancy identity; messages without that outbound evidence
    # use the documented normalized company\0role fallback.
    identity_url = application_url if application_url in value["outbound_urls"] else None
    source_job_id = vacancy_candidate_identity(
        value["peer_id"],
        value["message_id"],
        application_url=identity_url,
        company=confirmed_company,
        role=confirmed_role,
    )
    record = {
        "source": SOURCE_NAME,
        "source_job_id": source_job_id,
        "company": confirmed_company,
        "role": confirmed_role,
        "source_url": value["permalink"],
        "application_url": application_url,
        "posted_at": value["posted_at"][:10],
        "raw_location": _required_text(raw_location, "raw_location"),
        "found_at": _calendar_date(found_at if found_at is not None else value["found_at"], "found_at"),
        "payload": {
            "telegram": {
                "message_identity": value["message_identity"],
                "peer_id": value["peer_id"],
                "message_id": value["message_id"],
                "channel_title": value["channel_title"],
                "channel_username": value["channel_username"],
            },
        },
    }
    return record


def write_inbox_batch(
    inbox_dir: str | os.PathLike[str],
    records: Iterable[Mapping[str, Any]],
    *,
    run_at: datetime | None = None,
    validate: bool = True,
) -> Path:
    """Write a new immutable Telegram raw inbox batch and validate it."""
    values = [dict(record) for record in records]
    if not values:
        raise TelegramLeadError("inbox batch must contain at least one confirmed record")
    directory = Path(inbox_dir)
    for _attempt in range(10):
        path = directory / f"telegram-{_run_stamp(run_at)}-{secrets.token_hex(4)}.jsonl"
        try:
            _write_jsonl_exclusive(path, values, private=False)
            break
        except _ImmutableBatchCollision:
            continue
    else:
        raise TelegramLeadError("could not allocate a collision-safe immutable inbox batch name")
    if validate:
        try:
            from inbox import validate_batch
        except ModuleNotFoundError:
            from scripts.inbox import validate_batch
        result = validate_batch(path)
        if not result["ok"]:
            raise TelegramLeadError("inbox validation failed: " + "; ".join(result["errors"]))
    return path
