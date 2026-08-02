#!/usr/bin/env python3
"""PostToolUse[Bash] hook — notice work that changed the board's inputs.

Detect, never act. This runs after EVERY Bash tool call, so it does exactly
one thing: match the command string against a small pattern set and append one
JSON line to `$DOTFILES_DIR/projects/.queue/<project>.jsonl`. No network, no
git, no manifest read beyond `projects/index.json`. Budget: well under 50 ms.

It exits immediately, silently, status 0 when:

* `WT_SYNC_INTERNAL=1` — the background flusher is running worktree_sync.py and
  must not queue its own work;
* the cwd is not inside a worktree registered in `projects/index.json` — the
  same gate the SessionStart/SessionEnd hooks use;
* the command matches nothing.

Detection is best-effort by design. An agent can open a PR through an MCP tool
or the web UI, and a teammate can open one from anywhere; the queue only ever
says "something probably moved, flush sooner". The *guarantee* that a PR is
found is the periodic `sync`, which searches GitHub. Never treat a missing
queue line as evidence that nothing happened.

The queue is append-only, one JSON object per line, so a killed session leaves
a readable file behind and a torn last line costs at most one hint.

Claude Code only: Codex and Copilot expose no equivalent hook.
"""
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from hook_common import (  # noqa: E402
    is_internal, payload_cwd, project_for_cwd, queue_dir, queue_path,
    read_payload, utc_now,
)

# What the flusher cares about, and nothing else. `git push` is included
# because a push usually precedes or updates a PR; the flusher is cheap on a
# no-op, so a slightly eager pattern costs ~2 s in the background, while a
# missed one costs a stale board until the next SessionEnd.
PATTERNS = (
    ("prs-changed", re.compile(r"\bgh\s+pr\s+(?:create|merge|close|ready|edit)\b")),
    # `git push`, and every real-world dressing of it: `git -C /path push`,
    # `git --no-pager push`, `git -c foo=bar push`. Bounded, and stopped at a
    # shell separator so it cannot reach across `&&` into an unrelated command.
    ("prs-changed", re.compile(r"\bgit\b[^;&|\n]{0,60}?\bpush\b")),
    # `python3 …/worktree_sync.py task …`, and the `S=…/worktree_sync.py`
    # shorthand SKILL.md itself teaches (`python3 $S task set …`).
    ("tasks-changed",
     re.compile(r"(?:worktree_sync\.py|\$S\b|\$\{S\})\s+task\b")),
)

CMD_CAP = 300          # a queued hint is evidence, not an archive


def classify(command: str) -> str:
    for kind, pattern in PATTERNS:
        if pattern.search(command):
            return kind
    return ""


def main() -> int:
    if is_internal():
        return 0
    payload = read_payload()
    command = (payload.get("tool_input") or {}).get("command") or ""
    if not command:
        return 0
    project = project_for_cwd(payload_cwd(payload))
    if not project:
        return 0
    kind = classify(command)
    if not kind:
        return 0
    line = json.dumps({"at": utc_now(), "kind": kind, "cmd": command[:CMD_CAP]},
                      sort_keys=True) + "\n"
    queue_dir().mkdir(parents=True, exist_ok=True)
    # One open + one write under O_APPEND: concurrent sessions interleave whole
    # lines, never halves.
    with open(queue_path(project), "a", encoding="utf-8") as fh:
        fh.write(line)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:                                   # noqa: BLE001
        # A bookkeeping hint is never worth failing a tool call over.
        sys.exit(0)
