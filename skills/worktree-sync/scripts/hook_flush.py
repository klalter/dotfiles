#!/usr/bin/env python3
"""Stop / SessionStart hook — flush the queue to the board, in the background.

Three modes:

    hook_flush.py                     # Stop hook: decide, detach, return
    hook_flush.py --session-start     # + surface a parked conflict, drain a
                                      #   queue a killed session left behind
    hook_flush.py --run <project>     # the detached worker itself

**The hook half must return in milliseconds.** A board push is 2 s on a no-op
and has run past two minutes on a real one; a turn that waits for that is a
turn the owner feels, every time. So the hook decides whether a flush is due
and, if it is, starts a fully detached process (`start_new_session=True`, the
`setsid` of the standard library) with its output going to
`projects/.queue/flush.log` — then returns. Nothing in the turn ever waits on
GitHub. The next turn (or the next SessionStart) reports what happened.

The worker:

* takes a non-blocking `flock`; if another session holds it, it exits without
  queueing more work — the holder is about to do the same job. Sessions in
  different worktrees commit into the same dotfiles checkout and genuinely
  interleave here;
* exports `WT_SYNC_INTERNAL=1` so the PostToolUse detector ignores it;
* runs `sync <project> --commit`, then `project push <project>` — pull first,
  push second, because a bare push can revert a fresh board edit;
* truncates only the queue prefix it consumed, and only after a clean run, so a
  failure retries next turn and a hint queued mid-flush is not lost;
* on exit 3 stops immediately and parks the conflict block in
  `projects/.queue/<project>.conflict`, which the next SessionStart prints
  verbatim. It never passes --ack-human, never guesses, never reverts;
* writes one line per run to the log, so latency is auditable.

Claude Code only: Codex and Copilot expose no equivalent hook, so there the
SessionEnd autosync remains the only guarantee.
"""
import argparse
import fcntl
import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_common import (  # noqa: E402
    INTERNAL_ENV, conflict_path, dotfiles_dir, is_internal, log, log_path,
    lock_path, payload_cwd, project_for_cwd, queue_dir, queue_path, read_payload,
)

# How stale the project may get with an empty queue before a flush runs anyway.
# The queue only sees what a Bash command reveals; this floor is what catches
# everything else (a PR opened in the web UI, a teammate's review).
FLOOR_MINUTES = 20

# Deliberately NOT the manifest's generated_at: a sync that changes nothing
# leaves generated_at alone on purpose (that is the "nothing moved" signal), so
# keying staleness off it would re-flush every single turn forever. This stamp
# records when a flush last ran, which is the question actually being asked.
STAMP_SUFFIX = ".last-flush"

SYNC_TIMEOUT = 600      # a hung run must not hold the lock for the whole day
PUSH_TIMEOUT = 900

# The one writer. WT_SYNC_TOOL exists so the offline tests can drive a real
# detached worker against a stub instead of a live board; nothing else sets it.
TOOL = (os.environ.get("WT_SYNC_TOOL")
        or str(Path(__file__).resolve().parent / "worktree_sync.py"))


# ------------------------------------------------------------------ deciding

def stamp_path(project: str) -> Path:
    return queue_dir() / f"{project}{STAMP_SUFFIX}"


def queue_size(project: str) -> int:
    try:
        return queue_path(project).stat().st_size
    except OSError:
        return 0


def minutes_since_flush(project: str) -> float:
    """Minutes since the last flush attempt, or a large number if never."""
    try:
        return (time.time() - stamp_path(project).stat().st_mtime) / 60.0
    except OSError:
        return float("inf")


def flush_reason(project: str) -> str:
    """Why a flush is due, or "" when it is not."""
    if queue_size(project):
        return "queued"
    if minutes_since_flush(project) >= FLOOR_MINUTES:
        return "stale"
    return ""


# ----------------------------------------------------------------- detaching

def detach(project: str, reason: str) -> None:
    """Start the worker and return. Nothing here waits on it."""
    queue_dir().mkdir(parents=True, exist_ok=True)
    # Stamp BEFORE the work, not after: two turns in a row must not both decide
    # the project is stale and race for the lock.
    stamp_path(project).touch()
    env = child_env()
    with open(log_path(), "a", encoding="utf-8") as out:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "--run", project,
             "--reason", reason],
            stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
            start_new_session=True, close_fds=True, cwd=str(dotfiles_dir()),
            env=env)


# -------------------------------------------------------------------- worker

def drain(project: str, upto: int) -> None:
    """Drop the first `upto` bytes — the hints this run actually covered.

    Anything appended while the flush was running stays, so a PR opened
    mid-flush still triggers the next one.
    """
    path = queue_path(project)
    try:
        with open(path, "r+b") as fh:
            rest = fh.read()[upto:]
            fh.seek(0)
            fh.write(rest)
            fh.truncate()
    except OSError:
        pass


def park_conflict(project: str, step: str, output: str) -> None:
    """Write the exit-3 block where the next SessionStart will surface it."""
    queue_dir().mkdir(parents=True, exist_ok=True)
    conflict_path(project).write_text(
        f"[worktree-sync] A background flush of '{project}' stopped at "
        f"`{step}`: a human edited a field on the board and the tool will not "
        f"overwrite it.\nRelay the block below verbatim and ask the owner. Do "
        f"not pass --ack-human on your own judgement.\n\n{output.strip()}\n",
        encoding="utf-8")


def child_env() -> dict:
    """Environment for anything this hook starts.

    WT_SYNC_INTERNAL stops the detector queueing our own commands. DOTFILES_DIR
    is pinned to the checkout these hooks live in, because worktree_sync.py
    still resolves projects/ from that variable — and with the machinery
    present in two checkouts, inheriting a stale value is how one repo's hook
    ends up writing the other repo's manifests.
    """
    return {**os.environ, INTERNAL_ENV: "1", "DOTFILES_DIR": str(dotfiles_dir())}


def run_step(project: str, argv, timeout):
    return subprocess.run([sys.executable, TOOL, *argv], capture_output=True,
                          text=True, timeout=timeout, env=child_env(),
                          cwd=str(dotfiles_dir()))


def worker(project: str, reason: str) -> int:
    started = time.time()
    queue_dir().mkdir(parents=True, exist_ok=True)
    lock = open(lock_path(), "a+")                      # noqa: SIM115 — held to exit
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        # Someone else is doing this job right now. Do not queue more work and
        # do not wait: the holder's run will cover whatever we would have done.
        # Roll the stamp back, though — losing a race must not also buy the
        # loser another full FLOOR_MINUTES of silence.
        stamp_path(project).unlink(missing_ok=True)
        log(f"{project} skip=lock-held reason={reason}")
        return 0
    consumed = queue_size(project)
    steps = (("sync", ["sync", project, "--commit"], SYNC_TIMEOUT),
             ("project push", ["project", "push", project], PUSH_TIMEOUT))
    try:
        for name, argv, timeout in steps:
            try:
                r = run_step(project, argv, timeout)
            except subprocess.TimeoutExpired:
                log(f"{project} FAILED step={name} timeout after {timeout}s "
                    f"reason={reason} dur={time.time() - started:.1f}s")
                return 1
            if r.returncode == 3:
                park_conflict(project, name, r.stderr or r.stdout)
                log(f"{project} NEEDS-HUMAN step={name} reason={reason} "
                    f"dur={time.time() - started:.1f}s — parked "
                    f"{conflict_path(project).name}, queue kept")
                return 3
            if r.returncode:
                log(f"{project} FAILED step={name} rc={r.returncode} "
                    f"reason={reason} dur={time.time() - started:.1f}s "
                    f"err={(r.stderr or '').strip()[:200]!r} — queue kept, "
                    f"retries next turn")
                return 1
        drain(project, consumed)
        conflict_path(project).unlink(missing_ok=True)
        log(f"{project} ok reason={reason} hints={consumed}B "
            f"dur={time.time() - started:.1f}s")
        return 0
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


# --------------------------------------------------------------- hook halves

def surface_conflict(project: str) -> None:
    """Print a parked exit-3 block so SessionStart puts it in front of the
    agent. Removed once surfaced — if it is still unresolved the next flush
    parks it again, and repeating a stale block forever teaches people to
    ignore it."""
    path = conflict_path(project)
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return
    print(text)
    path.unlink(missing_ok=True)
    log(f"{project} conflict surfaced at session start")


def hook(session_start: bool) -> int:
    if is_internal():
        return 0
    project = project_for_cwd(payload_cwd(read_payload()))
    if not project:
        return 0
    if session_start:
        surface_conflict(project)
    reason = flush_reason(project)
    if not reason:
        return 0
    detach(project, "session-start" if session_start else reason)
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        prog="hook_flush.py",
        description="Background board flush for a tracked worktree. The hook "
                    "modes decide and detach in milliseconds; --run is the "
                    "detached worker.")
    ap.add_argument("--run", metavar="PROJECT", default=None,
                    help="internal: do the flush (detached worker)")
    ap.add_argument("--reason", default="manual", help="internal: why it ran")
    ap.add_argument("--session-start", action="store_true",
                    help="also surface a parked conflict and drain a stale queue")
    ap.add_argument("--status", action="store_true",
                    help="print what this worktree's queue looks like; changes nothing")
    args = ap.parse_args(argv)
    if args.run:
        return worker(args.run, args.reason)
    if args.status:
        project = project_for_cwd(os.getcwd())
        if not project:
            print("not a tracked worktree")
            return 0
        print(f"project        : {project}")
        print(f"queued hints   : {queue_size(project)} bytes "
              f"({queue_path(project)})")
        print(f"last flush     : {minutes_since_flush(project):.1f} min ago "
              f"(floor {FLOOR_MINUTES} min)")
        print(f"flush due      : {flush_reason(project) or 'no'}")
        print(f"parked conflict: "
              f"{'yes — ' + str(conflict_path(project)) if conflict_path(project).exists() else 'none'}")
        print(f"log            : {log_path()}")
        return 0
    return hook(args.session_start)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:                            # noqa: BLE001
        # Never block a turn. The failure is logged, not raised.
        log(f"hook error: {exc!r}")
        sys.exit(0)
