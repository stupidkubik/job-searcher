"""Isolated v3 prototype for crash-recoverable multi-file replacement.

Nothing imports this module from the production tracker write path yet. Callers
must supply complete bytes and expected old hashes for every target. A pending
journal rolls back on recovery; a committed journal keeps the new files.
"""

import fcntl
import hashlib
import json
import os
import shutil
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path, PurePosixPath


JOURNAL_NAME = ".v3-transaction"
LOCK_NAME = ".v3-transaction.lock"


class TransactionError(RuntimeError):
    pass


class StaleRevision(TransactionError):
    pass


class RecoveryError(TransactionError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest() if data is not None else None


def fsync_dir(path):
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def write_durable(path, data):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


@contextmanager
def locked(root):
    root = Path(root)
    if not root.is_dir():
        raise TransactionError(f"transaction root does not exist: {root}")
    with (root / LOCK_NAME).open("a+b") as stream:
        fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
        try:
            yield root
        finally:
            fcntl.flock(stream.fileno(), fcntl.LOCK_UN)


def target_path(root, relative):
    if not isinstance(relative, str):
        raise TransactionError("target path must be a relative POSIX string")
    path = PurePosixPath(relative)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise TransactionError(f"unsafe target path: {relative!r}")
    if path.parts[0] in {JOURNAL_NAME, LOCK_NAME} or path.parts[0].startswith(".v3-finished-"):
        raise TransactionError("transaction metadata cannot be a target")
    target = root.joinpath(*path.parts)
    parent = target.parent.resolve(strict=True)
    if not parent.is_relative_to(root.resolve()) or target.is_symlink():
        raise TransactionError(f"target escapes transaction root: {relative}")
    return target


def read_old(target):
    return target.read_bytes() if target.exists() else None


def load_manifest(root):
    journal = root / JOURNAL_NAME
    path = journal / "manifest.json"
    if not path.exists():
        return None
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise RecoveryError(f"unreadable transaction manifest: {error}") from error
    if not isinstance(manifest, dict) or manifest.get("version") != 1:
        raise RecoveryError("unsupported transaction manifest")
    entries = manifest.get("targets")
    if not isinstance(entries, list) or not entries:
        raise RecoveryError("transaction manifest has no targets")
    names = set()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {"path", "existed", "old_sha256"}:
            raise RecoveryError("invalid transaction manifest entry")
        relative = entry["path"]
        try:
            target_path(root, relative)
        except (TransactionError, OSError) as error:
            raise RecoveryError(f"unsafe manifest target: {error}") from error
        if relative in names or type(entry["existed"]) is not bool:
            raise RecoveryError("duplicate target or invalid existed flag")
        names.add(relative)
        old_hash = entry["old_sha256"]
        if entry["existed"]:
            if not isinstance(old_hash, str) or len(old_hash) != 64:
                raise RecoveryError("missing backup hash")
        elif old_hash is not None:
            raise RecoveryError("absent target cannot have a backup hash")
    return manifest


def restore_target(target, data):
    descriptor, temporary = tempfile.mkstemp(prefix=".v3-restore-", dir=target.parent)
    temporary = Path(temporary)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
        fsync_dir(target.parent)
    finally:
        temporary.unlink(missing_ok=True)


def rollback_locked(root, manifest):
    journal = root / JOURNAL_NAME
    backups = {}
    for index, entry in enumerate(manifest["targets"]):
        if entry["existed"]:
            try:
                data = (journal / f"{index}.old").read_bytes()
            except OSError as error:
                raise RecoveryError(f"backup {index} is missing: {error}") from error
            if digest(data) != entry["old_sha256"]:
                raise RecoveryError(f"backup {index} failed its hash check")
            backups[index] = data
    for index in reversed(range(len(manifest["targets"]))):
        entry = manifest["targets"][index]
        target = target_path(root, entry["path"])
        if entry["existed"]:
            restore_target(target, backups[index])
        elif target.exists():
            target.unlink()
            fsync_dir(target.parent)


def retire_journal_locked(root):
    """Atomically remove the pending name before best-effort cleanup."""
    journal = root / JOURNAL_NAME
    finished = root / f".v3-finished-{uuid.uuid4().hex}"
    os.replace(journal, finished)
    fsync_dir(root)
    try:
        shutil.rmtree(finished)
        fsync_dir(root)
    except OSError:
        # No pending journal remains. An abandoned finished directory is safe
        # to remove later and cannot trigger recovery of a finished operation.
        pass


def reap_finished_locked(root):
    removed = False
    for path in root.glob(".v3-finished-*"):
        if path.is_dir() and not path.is_symlink():
            try:
                shutil.rmtree(path)
                removed = True
            except OSError:
                pass
    if removed:
        fsync_dir(root)


def recover_locked(root):
    reap_finished_locked(root)
    journal = root / JOURNAL_NAME
    if not journal.exists():
        return "clean"
    if not journal.is_dir() or journal.is_symlink():
        raise RecoveryError("transaction journal is not a directory")
    manifest = load_manifest(root)
    if manifest is None:
        # Replacement cannot start before the manifest has been fsynced.
        retire_journal_locked(root)
        return "discarded_prepare"
    committed = journal / "committed"
    if committed.exists():
        if committed.read_bytes() != b"ok\n":
            raise RecoveryError("invalid commit marker")
        retire_journal_locked(root)
        return "kept_commit"
    rollback_locked(root, manifest)
    retire_journal_locked(root)
    return "rolled_back"


def recover(root):
    """Resolve an interrupted transaction while holding the shared file lock."""
    with locked(root) as root:
        return recover_locked(root)


def read_consistent(root, relatives):
    """Read a file set after recovery and under the same lock as publishers."""
    with locked(root) as root:
        recover_locked(root)
        return {name: read_old(target_path(root, name)) for name in relatives}


def publish(root, writes, expected, *, validate=None, fault=None):
    """Replace a complete file set or recoverably restore its prior bytes.

    `fault(stage, index)` is a test hook; it may raise or terminate the process.
    Production callers must include their immutable operation result in `writes`
    when that result must be atomic with canonical state.
    """
    if not isinstance(writes, dict) or not writes or set(writes) != set(expected):
        raise TransactionError("writes and expected must name the same nonempty file set")
    if any(not isinstance(data, bytes) for data in writes.values()):
        raise TransactionError("every replacement must be complete bytes")
    with locked(root) as root:
        recover_locked(root)
        names = sorted(writes)
        targets = {name: target_path(root, name) for name in names}
        old = {name: read_old(targets[name]) for name in names}
        for name in names:
            if digest(old[name]) != expected[name]:
                raise StaleRevision(f"stale target revision: {name}")
        journal = root / JOURNAL_NAME
        journal.mkdir(mode=0o700)
        fsync_dir(root)
        manifest = {"version": 1, "targets": []}
        try:
            for index, name in enumerate(names):
                previous = old[name]
                if previous is not None:
                    write_durable(journal / f"{index}.old", previous)
                write_durable(journal / f"{index}.new", writes[name])
                manifest["targets"].append(
                    {"path": name, "existed": previous is not None, "old_sha256": digest(previous)}
                )
            write_durable(journal / "manifest.json", json.dumps(manifest, sort_keys=True).encode() + b"\n")
            fsync_dir(journal)
            if fault is not None:
                fault("after_prepare", None)
            for index, name in enumerate(names):
                os.replace(journal / f"{index}.new", targets[name])
                fsync_dir(targets[name].parent)
                if fault is not None:
                    fault("after_replace", index)
            if validate is not None:
                validate(root)
            write_durable(journal / "committed", b"ok\n")
            fsync_dir(journal)
            if fault is not None:
                fault("after_commit", None)
            retire_journal_locked(root)
        except BaseException:
            # A process kill bypasses this branch; the next recover() rolls back.
            if journal.exists() and not (journal / "committed").exists():
                recover_locked(root)
            raise
