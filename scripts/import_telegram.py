#!/usr/bin/env python3
"""Local, allowlist-only Telegram discovery adapter.

The adapter deliberately stops at a local lead spool.  It never writes to the
canonical job tracker and it never sends messages.  Telethon is imported only
inside commands which need it, so the rest of the repository has no runtime
dependency on Telegram.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import stat
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

try:  # Direct execution places scripts/ on sys.path.
    import telegram_leads
except ModuleNotFoundError:  # Tests import this file as scripts.import_telegram.
    from scripts import telegram_leads


API_ID_ENV = "TELEGRAM_API_ID"
API_HASH_ENV = "TELEGRAM_API_HASH"
SESSION_BASENAME = "telegram"
DEFAULT_MAX_AGE_DAYS = 7
DEFAULT_MAX_MESSAGES_PER_PEER = 500
ROOT = Path(__file__).resolve().parent.parent
DEFAULT_INBOX_DIR = ROOT / "data" / "inbox"
DEFAULT_KEYWORDS = (
    "frontend",
    "front-end",
    "react",
    "typescript",
    "javascript",
    "next.js",
    "web developer",
    "ui engineer",
)


class TelegramImportError(ValueError):
    """An operator-actionable adapter error safe to display."""


@dataclass(frozen=True)
class TelegramRuntime:
    client_class: Any
    get_peer_id: Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso_utc(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def load_telethon() -> TelegramRuntime:
    """Import optional Telegram code without making it a repository dependency."""
    try:
        telethon = importlib.import_module("telethon")
        utils = importlib.import_module("telethon.utils")
    except ModuleNotFoundError as error:
        if error.name == "telethon" or (error.name or "").startswith("telethon."):
            raise TelegramImportError(
                "Telethon is not installed; install requirements/telegram.txt"
            ) from None
        raise
    return TelegramRuntime(client_class=telethon.TelegramClient, get_peer_id=utils.get_peer_id)


def load_credentials(environ: Mapping[str, str] | None = None) -> tuple[int, str]:
    """Read credentials from the environment, returning no printable wrapper."""
    env = os.environ if environ is None else environ
    raw_api_id = env.get(API_ID_ENV, "").strip()
    api_hash = env.get(API_HASH_ENV, "").strip()
    try:
        api_id = int(raw_api_id)
    except ValueError:
        api_id = 0
    if api_id <= 0 or not api_hash:
        raise TelegramImportError(
            f"set a positive {API_ID_ENV} and a non-empty {API_HASH_ENV} in the environment"
        )
    return api_id, api_hash


def resolve_data_dir(explicit: str | Path | None = None) -> Path:
    """Small adapter boundary around the domain/storage implementation."""
    return telegram_leads.resolve_data_dir(explicit)


def require_external_data_dir(data_dir: Path) -> Path:
    """Reject Telegram credentials/raw storage anywhere inside this checkout."""
    resolved = Path(data_dir).expanduser().resolve()
    repository = ROOT.resolve()
    if resolved == repository or repository in resolved.parents:
        raise TelegramImportError(
            "Telegram data directory must be outside the repository checkout"
        )
    return resolved


def create_client(
    runtime: TelegramRuntime,
    data_dir: Path,
    *,
    environ: Mapping[str, str] | None = None,
):
    data_dir = require_external_data_dir(data_dir)
    api_id, api_hash = load_credentials(environ)
    telegram_leads.ensure_private_dir(data_dir)
    session_path = data_dir / SESSION_BASENAME
    return runtime.client_class(
        str(session_path),
        api_id,
        api_hash,
        # Never hide FLOOD_WAIT behind an automatic sleep/retry loop. The pull
        # summary reports it to the operator instead.
        flood_sleep_threshold=0,
        request_retries=1,
    )


def owner_only_permission_issues(data_dir: Path) -> list[str]:
    """Return paths whose group/world permission bits are set.

    Only local path names are reported. File contents and credential values are
    never inspected or printed.
    """
    if not data_dir.exists():
        return []
    candidates = [data_dir]
    candidates.extend(path for path in data_dir.iterdir() if path.is_file())
    issues = []
    for path in candidates:
        if stat.S_IMODE(path.stat().st_mode) & 0o077:
            issues.append(path.name if path != data_dir else ".")
    return sorted(issues)


def secure_session_files(data_dir: Path) -> None:
    """Tighten Telethon SQLite session and transient journal permissions."""
    for path in data_dir.glob(f"{SESSION_BASENAME}.session*"):
        if path.is_file():
            path.chmod(0o600)


def doctor(
    data_dir: Path,
    *,
    environ: Mapping[str, str] | None = None,
    runtime_loader=load_telethon,
) -> dict[str, Any]:
    checks: dict[str, dict[str, Any]] = {}
    try:
        load_credentials(environ)
        checks["credentials"] = {"ok": True}
    except TelegramImportError as error:
        checks["credentials"] = {"ok": False, "message": str(error)}

    try:
        runtime_loader()
        checks["dependency"] = {"ok": True}
    except TelegramImportError as error:
        checks["dependency"] = {"ok": False, "message": str(error)}

    issues = owner_only_permission_issues(data_dir)
    checks["permissions"] = {
        "ok": not issues,
        "message": "owner-only" if not issues else "group/world bits set",
        "paths": issues,
    }
    try:
        peers = telegram_leads.load_allowlist(data_dir)
        checks["allowlist"] = {
            "ok": bool(peers),
            "count": len(peers),
            "required_for": "pull",
        }
    except ValueError:
        checks["allowlist"] = {
            "ok": False,
            "count": 0,
            "required_for": "pull",
            "message": "missing or invalid",
        }
    prerequisites_ok = all(checks[name]["ok"] for name in ("credentials", "dependency", "permissions"))
    ready_for_pull = prerequisites_ok and checks["allowlist"]["ok"]
    result = {
        "status": "ok" if prerequisites_ok else "error",
        "ready_for_pull": ready_for_pull,
        "checks": checks,
    }
    if prerequisites_ok and not ready_for_pull:
        result["next_action"] = "configure allowlist"
    return result


async def _connect_authorized(client: Any) -> None:
    await client.connect()
    if not await client.is_user_authorized():
        raise TelegramImportError("Telegram session is not authorized; run the login command locally")


async def login(client: Any) -> dict[str, Any]:
    """Run Telethon's interactive login; secrets are never accepted as CLI args."""
    await client.start()
    return {"status": "ok", "authorized": bool(await client.is_user_authorized())}


def dialog_type(entity: Any) -> str | None:
    if bool(getattr(entity, "broadcast", False)):
        return "broadcast"
    if bool(getattr(entity, "megagroup", False)):
        return "supergroup"
    return None


async def list_dialogs(client: Any, *, get_peer_id) -> list[dict[str, Any]]:
    """List eligible channels without changing the allowlist."""
    dialogs = []
    async for dialog in client.iter_dialogs():
        entity = getattr(dialog, "entity", dialog)
        kind = dialog_type(entity)
        if kind is None:
            continue
        dialogs.append({
            "peer_id": int(get_peer_id(entity)),
            "title": str(getattr(entity, "title", "") or ""),
            "username": getattr(entity, "username", None),
            "type": kind,
        })
    return sorted(dialogs, key=lambda item: item["peer_id"])


def _state_cursor(state: Mapping[str, Any], peer_id: int) -> int:
    peers = state.get("peers", {})
    peer = peers.get(str(peer_id), {}) if isinstance(peers, Mapping) else {}
    value = peer.get("last_message_id", 0) if isinstance(peer, Mapping) else 0
    try:
        return telegram_leads.normalize_message_id(value) if value else 0
    except (TypeError, ValueError):
        raise TelegramImportError(f"local cursor for peer {peer_id} is invalid") from None


def _message_text(message: Any) -> str:
    value = getattr(message, "message", None)
    if value is None:
        value = getattr(message, "raw_text", "")
    return value if isinstance(value, str) else ""


def _message_date(message: Any) -> datetime:
    value = getattr(message, "date", None)
    if not isinstance(value, datetime):
        raise TelegramImportError("Telegram returned a message without a valid date")
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _permalink(peer_id: int, message_id: int, username: str | None) -> str | None:
    if username:
        return f"https://t.me/{username}/{message_id}"
    raw = str(abs(peer_id))
    if peer_id < 0 and raw.startswith("100") and len(raw) > 3:
        return f"https://t.me/c/{raw[3:]}/{message_id}"
    return None


def _forwarded_from(message: Any) -> dict[str, str | int] | None:
    forward = getattr(message, "fwd_from", None)
    if forward is None:
        return None
    for name in ("from_name", "channel_id", "from_id"):
        value = getattr(forward, name, None)
        if isinstance(value, (str, int)) and not isinstance(value, bool):
            return {name: value}
    return None


def _safe_peer_error(peer_id: int, error: Exception) -> dict[str, Any]:
    kind = type(error).__name__
    item: dict[str, Any] = {"peer_id": peer_id, "kind": kind}
    if kind in {"FloodWait", "FloodWaitError"}:
        seconds = getattr(error, "seconds", None)
        if isinstance(seconds, int):
            item["retry_after_seconds"] = seconds
    return item


async def collect_pull(
    client: Any,
    data_dir: Path,
    *,
    peer_ids: Iterable[int],
    max_age_days: int = DEFAULT_MAX_AGE_DAYS,
    max_messages_per_peer: int = DEFAULT_MAX_MESSAGES_PER_PEER,
    keywords: Iterable[str] = DEFAULT_KEYWORDS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch bounded history for exactly the supplied numeric allowlist."""
    data_dir = require_external_data_dir(data_dir)
    peers = [telegram_leads.normalize_peer_id(value) for value in peer_ids]
    if not peers:
        raise TelegramImportError("allowlist is missing or empty; refusing to pull")
    if max_age_days <= 0 or max_messages_per_peer <= 0:
        raise TelegramImportError("pull bounds must be positive integers")
    terms = tuple(term.strip() for term in keywords if isinstance(term, str) and term.strip())
    if not terms:
        raise TelegramImportError("at least one non-empty keyword is required")

    run_at = now or utc_now()
    cutoff = run_at - timedelta(days=max_age_days)
    with telegram_leads.pull_lock(data_dir):
        state = telegram_leads.load_state(data_dir)
        seen = telegram_leads.load_seen_identities(data_dir)
        candidates: list[dict[str, Any]] = []
        cursor_updates: dict[int, int] = {}
        errors: list[dict[str, Any]] = []
        fetched = 0
        completed = 0
        backlog_peers: list[int] = []

        # There is deliberately no discovery/all-dialogs branch here. Reverse
        # order plus an N+1 sentinel lets a large backlog make bounded progress
        # without skipping the unprocessed tail.
        for peer_id in peers:
            cursor = _state_cursor(state, peer_id)
            peer_max_id = cursor
            peer_fetched = 0
            has_more = False
            try:
                entity = await client.get_entity(peer_id)
                if dialog_type(entity) is None:
                    raise TelegramImportError("allowlisted peer is not a broadcast channel or supergroup")
                title = str(getattr(entity, "title", "") or "")
                username = getattr(entity, "username", None)
                async for message in client.iter_messages(
                    peer_id,
                    limit=max_messages_per_peer + 1,
                    min_id=cursor,
                    # With reverse=True Telethon reverses offset_date semantics:
                    # on first contact this begins at the configured retention
                    # boundary instead of walking the channel's entire history.
                    offset_date=cutoff if cursor == 0 else None,
                    reverse=True,
                ):
                    if peer_fetched >= max_messages_per_peer:
                        has_more = True
                        break
                    message_id = telegram_leads.normalize_message_id(getattr(message, "id", None))
                    posted_at = _message_date(message)
                    fetched += 1
                    peer_fetched += 1
                    peer_max_id = max(peer_max_id, message_id)
                    # A stale gap after an established cursor is consumed so the
                    # cursor can advance safely, but those messages are not stored.
                    if posted_at < cutoff:
                        continue
                    text = _message_text(message)
                    entities = getattr(message, "entities", ()) or ()
                    matched_terms = telegram_leads.match_keywords(text, terms)
                    urls = telegram_leads.extract_http_urls(text, entities)
                    if not matched_terms and not urls:
                        continue
                    lead = telegram_leads.build_lead(
                        peer_id=peer_id,
                        message_id=message_id,
                        channel_title=title,
                        channel_username=username,
                        posted_at=posted_at,
                        found_at=run_at,
                        permalink=_permalink(peer_id, message_id, username),
                        text=text,
                        entities=entities,
                        matched_terms=matched_terms,
                        forwarded_from=_forwarded_from(message),
                        edited_at=getattr(message, "edit_date", None),
                    )
                    candidates.append(lead)
                if peer_max_id > 0:
                    cursor_updates[peer_id] = peer_max_id
                if has_more:
                    backlog_peers.append(peer_id)
                completed += 1
            except Exception as error:  # A failed peer must not block successful peers.
                errors.append(_safe_peer_error(peer_id, error))

        unique, duplicate_count = telegram_leads.deduplicate_leads(candidates, seen)
        batch_path = telegram_leads.commit_lead_batch(
            data_dir, unique, cursor_updates, run_at=run_at
        )
    return {
        "status": "partial" if errors else "ok",
        "run_at": iso_utc(run_at),
        "peers": {
            "requested": len(peers),
            "completed": completed,
            "failed": len(errors),
            "backlog": len(backlog_peers),
        },
        "fetched": fetched,
        "matched": len(candidates),
        "duplicates": duplicate_count,
        "written": len(unique),
        "batch": str(batch_path),
        "backlog_peers": backlog_peers,
        "errors": errors,
    }


def format_output(payload: Any, output_format: str) -> str:
    if output_format == "json":
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)
    if isinstance(payload, list):
        return "\n".join(
            "\t".join(f"{key}={value}" for key, value in item.items()) for item in payload
        )
    if isinstance(payload, dict):
        return "\n".join(f"{key}: {value}" for key, value in payload.items())
    return str(payload)


def _positive_int(value: str) -> int:
    try:
        result = int(value)
    except ValueError as error:
        raise argparse.ArgumentTypeError("expected a positive integer") from error
    if result <= 0:
        raise argparse.ArgumentTypeError("expected a positive integer")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Local allowlist-only Telegram discovery adapter")
    parser.add_argument("--data-dir", help="local application-data directory outside the checkout")
    parser.add_argument("--format", choices=("json", "text"), default="json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("doctor", help="check config, optional dependency, and local permissions")
    commands.add_parser("login", help="run interactive one-time Telegram login")
    commands.add_parser("list-dialogs", help="list available broadcast channels and supergroups")

    allowlist = commands.add_parser("allowlist", help="manage the numeric local peer allowlist")
    allowlist_commands = allowlist.add_subparsers(dest="allowlist_command", required=True)
    allowlist_commands.add_parser("show", help="show numeric peer IDs")
    allowlist_set = allowlist_commands.add_parser("set", help="replace allowlist with numeric peer IDs")
    allowlist_set.add_argument("peer_ids", nargs="+", type=int)

    leads = commands.add_parser("leads", help="inspect locally stored leads")
    lead_commands = leads.add_subparsers(dest="leads_command", required=True)
    lead_list = lead_commands.add_parser("list", help="list lead metadata without message text")
    lead_list.add_argument("--limit", type=_positive_int, default=100)
    lead_show = lead_commands.add_parser("show", help="show one exact lead")
    lead_show.add_argument("identity", help="exact telegram:<peer_id>:<message_id> lead identity")
    lead_show.add_argument(
        "--include-text",
        action="store_true",
        help="include private message text in local output",
    )

    pull = commands.add_parser("pull", help="pull bounded history from allowlisted peers only")
    pull.add_argument("--max-age-days", type=_positive_int, default=DEFAULT_MAX_AGE_DAYS)
    pull.add_argument(
        "--max-messages-per-peer", type=_positive_int, default=DEFAULT_MAX_MESSAGES_PER_PEER
    )
    pull.add_argument("--keyword", action="append", dest="keywords")

    normalize = commands.add_parser(
        "normalize", help="project one human-confirmed lead into a validated raw inbox batch"
    )
    normalize.add_argument("identity", help="exact telegram:<peer_id>:<message_id> lead identity")
    normalize.add_argument("--company", required=True)
    normalize.add_argument("--role", required=True)
    normalize.add_argument("--application-url", required=True)
    normalize.add_argument("--raw-location", required=True)
    normalize.add_argument("--inbox-dir", default=str(DEFAULT_INBOX_DIR))
    return parser


async def _run_network_command(args: argparse.Namespace, data_dir: Path) -> Any:
    runtime = load_telethon()
    client = create_client(runtime, data_dir)
    try:
        if args.command == "login":
            return await login(client)
        await _connect_authorized(client)
        if args.command == "list-dialogs":
            return await list_dialogs(client, get_peer_id=runtime.get_peer_id)
        if args.command == "pull":
            peer_ids = telegram_leads.load_allowlist(data_dir)
            return await collect_pull(
                client,
                data_dir,
                peer_ids=peer_ids,
                max_age_days=args.max_age_days,
                max_messages_per_peer=args.max_messages_per_peer,
                keywords=args.keywords or DEFAULT_KEYWORDS,
            )
        raise AssertionError(f"unsupported network command {args.command}")
    finally:
        await client.disconnect()
        secure_session_files(data_dir)


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        data_dir = require_external_data_dir(resolve_data_dir(args.data_dir))
        if args.command == "doctor":
            payload = doctor(data_dir)
            exit_code = 0 if payload["status"] == "ok" else 1
        elif args.command == "allowlist":
            if args.allowlist_command == "show":
                payload = {"peer_ids": telegram_leads.load_allowlist(data_dir)}
            else:
                path = telegram_leads.write_allowlist(data_dir, args.peer_ids)
                payload = {
                    "status": "ok",
                    "peer_ids": telegram_leads.load_allowlist(data_dir),
                    "path": str(path),
                }
            exit_code = 0
        elif args.command == "leads":
            if args.leads_command == "list":
                stored = list(telegram_leads.iter_stored_leads(data_dir))
                selected = stored[-args.limit:]
                payload = {
                    "status": "ok",
                    "count": len(stored),
                    "returned": len(selected),
                    "leads": [telegram_leads.lead_summary(lead) for lead in selected],
                }
            else:
                lead = telegram_leads.find_lead(data_dir, args.identity)
                payload = {
                    "status": "ok",
                    "lead": telegram_leads.lead_summary(
                        lead, include_text=args.include_text
                    ),
                }
            exit_code = 0
        elif args.command == "normalize":
            lead = telegram_leads.find_lead(data_dir, args.identity)
            record = telegram_leads.project_confirmed_lead(
                lead,
                company=args.company,
                role=args.role,
                application_url=args.application_url,
                raw_location=args.raw_location,
            )
            inbox_batch = telegram_leads.write_inbox_batch(
                Path(args.inbox_dir), [record], validate=True
            )
            payload = {
                "status": "ok",
                "identity": args.identity,
                "source_job_id": record["source_job_id"],
                "inbox_batch": str(inbox_batch),
            }
            exit_code = 0
        else:
            payload = asyncio.run(_run_network_command(args, data_dir))
            exit_code = 2 if isinstance(payload, dict) and payload.get("status") == "partial" else 0
        print(format_output(payload, args.format))
        return exit_code
    except (TelegramImportError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1
    except Exception as error:
        # Provider exception text is intentionally not rendered: it is outside
        # our contract and may contain account/session details.
        print(f"error: Telegram command failed ({type(error).__name__})", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
