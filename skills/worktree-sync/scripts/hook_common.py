#!/usr/bin/env python3
"""Shared plumbing for the worktree-sync Claude Code hooks.

Imported by `hook_detect.py` (PostToolUse[Bash]) and `hook_flush.py`
(Stop / SessionStart). Both run on the hot path — the detector on EVERY Bash
tool call — so this module is deliberately tiny:

* stdlib only, and only modules the interpreter already loads cheaply;
* it never imports `worktree_sync.py` (that pulls in wt_common, subprocess,
  urllib, hashlib and a sys.path insert — tens of milliseconds for nothing);
* the only file it reads is `projects/index.json`, ~1 KB.

Everything here must be non-fatal. A hook that raises is a hook that breaks a
tool call, and no bookkeeping is worth that.

The repo root is resolved from this file's own path, never from $DOTFILES_DIR:
the hooks must act on the checkout they were installed from, whichever one that
turns out to be.

**Claude Code only.** Codex and Copilot have no equivalent hook surface, so for
those CLIs the SessionEnd/periodic sync remains the only guarantee.
"""
import json
import os
import sys
from pathlib import Path

# The flusher exports this before running worktree_sync.py, and every hook
# checks it first. Without it the detector would queue the flusher's own
# `worktree_sync.py task`-shaped commands and the loop would never settle.
INTERNAL_ENV = "WT_SYNC_INTERNAL"

# Test-only override for the repo root. Nothing in normal operation sets it;
# the offline tests point it at a throwaway directory so no real manifest,
# queue or lock is ever touched.
HOME_ENV = "WT_SYNC_HOME"

QUEUE_DIRNAME = ".queue"

# scripts/ -> worktree-sync/ -> skills/ -> the repo root.
SELF_HOME = Path(__file__).resolve().parents[3]


def dotfiles_dir() -> Path:
    """The dotfiles checkout these hooks belong to — the one they LIVE in.

    Deliberately self-located and NOT read from $DOTFILES_DIR. The machinery
    currently exists in two checkouts (klalter/dotfiles and
    kas-dotfiles) and which one is canonical is the owner's open decision; an
    environment variable would let a hook in one repo write the other's
    `projects/`, which is exactly the way to make two manifests diverge. Moving
    this skill to another repo is then a copy, not an edit.
    """
    return Path(os.environ.get(HOME_ENV) or SELF_HOME)


def projects_dir() -> Path:
    return dotfiles_dir() / "projects"


def queue_dir() -> Path:
    """Transient local state: hint queue, flush log, lock, pending conflicts.

    Git-ignored on purpose — it is per-machine scratch, not versioned data.
    """
    return projects_dir() / QUEUE_DIRNAME


def queue_path(project: str) -> Path:
    return queue_dir() / f"{project}.jsonl"


def conflict_path(project: str) -> Path:
    """Where a background flush parks an exit-3 block for the next SessionStart."""
    return queue_dir() / f"{project}.conflict"


def lock_path() -> Path:
    """One lock for the whole of projects/ — sessions in different worktrees
    commit into the same git checkout and genuinely interleave."""
    return queue_dir() / "flush.lock"


def log_path() -> Path:
    return queue_dir() / "flush.log"


def is_internal() -> bool:
    return os.environ.get(INTERNAL_ENV) == "1"


def read_payload() -> dict:
    """The hook JSON on stdin, or {} — never raises, never blocks on a tty."""
    try:
        if sys.stdin is None or sys.stdin.isatty():
            return {}
        raw = sys.stdin.read()
    except Exception:                                   # noqa: BLE001
        return {}
    try:
        data = json.loads(raw)
    except Exception:                                   # noqa: BLE001
        return {}
    return data if isinstance(data, dict) else {}


def payload_cwd(payload: dict) -> str:
    return payload.get("cwd") or os.getcwd()


def project_for_cwd(cwd) -> str:
    """Name of the tracked project whose worktree contains cwd, or "".

    The same gate the SessionStart/SessionEnd hooks use (`entry_for_cwd` in
    worktree_sync.py), reimplemented here so a hook never pays to import the
    whole tool just to find out it has nothing to do.
    """
    try:
        index = json.loads((projects_dir() / "index.json").read_text())
    except Exception:                                   # noqa: BLE001
        return ""
    try:
        cwd = str(Path(cwd).resolve())
    except Exception:                                   # noqa: BLE001
        return ""
    for entry in index.get("projects") or []:
        root = entry.get("worktree") or ""
        if not root:
            continue
        root = os.path.normpath(root)
        if cwd == root or cwd.startswith(root + os.sep):
            return entry.get("name") or ""
    return ""


def utc_now() -> str:
    from datetime import datetime, timezone
    return (datetime.now(timezone.utc).replace(microsecond=0)
            .isoformat().replace("+00:00", "Z"))


def log(line: str) -> None:
    """One auditable line per flush decision. Best-effort; never raises."""
    try:
        queue_dir().mkdir(parents=True, exist_ok=True)
        with open(log_path(), "a", encoding="utf-8") as fh:
            fh.write(f"{utc_now()} {line}\n")
    except Exception:                                   # noqa: BLE001
        pass
