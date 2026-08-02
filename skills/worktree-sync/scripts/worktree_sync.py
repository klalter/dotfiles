#!/usr/bin/env python3
"""Deterministic tracker for the git worktrees under /workspaces/.wt.

Source of truth is a set of JSON manifests in $DOTFILES_DIR/projects/, generated
from git + GitHub facts. A second run with no underlying change rewrites nothing,
so `git status` staying clean *is* the "nothing moved" signal.

    worktree_sync.py scan   <worktree>            # git-only, no network
    worktree_sync.py sync   <worktree|name>       # + PRs, writes the manifest
    worktree_sync.py status [name]                # read manifests, print table
    worktree_sync.py render                       # regenerate projects/README.md
    worktree_sync.py commit                       # commit + push dotfiles (current branch)
    worktree_sync.py project pull <name>          # board -> manifest (human wins)
    worktree_sync.py project push <name>          # pull, then manifest -> board

`sync --commit` chains sync -> render -> commit, and is the everyday call.

ARGUMENT ORDER: the action comes first, the project second —
`task set <project> t7 done`, `project push <project>`. Never
`task <project> set …`.

EXIT CODES, the whole contract:
    0   success
    1   error (bad arguments, missing manifest/scope, git failure)
    3   EXIT_HITL — a human edited that field on the board. Not a failure and
        not retryable: relay the printed block and ask the owner.
Nothing else ever returns 3, and no conflict path ever returns 1.

--json is opt-in on scan, sync, status, task, context and project. It prints
exactly one JSON object on stdout and no prose, so a calling agent can branch
on the result instead of parsing English; human output stays the default.

Tasks carry a free-text Group, dependencies on other tasks, an instruction
body, attachments and optional Start/Target dates. The board is the source of
truth for anything a HUMAN changed there: `project pull` merges those edits
back and stamps them, and the tool refuses to overwrite a stamped field
without --ack-human, exiting EXIT_HITL so a calling agent can tell "needs a
human decision" apart from a real failure.

Discovery/search logic is shared with worktree-pr-view via wt_common.py — the
per-worktree HEAD reflog rule and the single-GraphQL-search rule live there and
must not be re-derived here.
"""
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "worktree-pr-view" / "scripts"))
from wt_common import (  # noqa: E402
    build_query, discover, find_prs, gh_json, repo_slug, sh, worktree_name,
)

DEFAULT_DOTFILES = "/workspaces/my-dotfiles"
COMMITTER = ("Klalter De Abreu Santos", "klalter@kyndryl.com")
PROJECT_SCOPE_HINT = (
    "GitHub Projects v2 needs the 'project' OAuth scope, which no token here has.\n"
    "Run this yourself (gh refuses while GH_TOKEN/GITHUB_TOKEN are set):\n\n"
    "  env -u GH_TOKEN -u GITHUB_TOKEN gh auth refresh -h github.com -s project\n"
)
# Exit codes. 1 is a real failure; 3 means "a human edited this on the board and
# the tool will not overwrite it" — a calling agent must ask, not retry.
EXIT_HITL = 3


# ---------------------------------------------------------------- paths / io

def dotfiles_dir() -> Path:
    return Path(os.environ.get("DOTFILES_DIR") or DEFAULT_DOTFILES)


def projects_dir() -> Path:
    return dotfiles_dir() / "projects"


def dump(obj) -> str:
    """Canonical JSON: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


def emit_json(obj) -> None:
    """Machine-readable output: canonical JSON on stdout, nothing else.

    Every --json command prints exactly one object here and no prose, so a
    calling agent can branch on the result instead of parsing English. Human
    output stays the default; --json is opt-in and never mixed with it.
    """
    print(dump(obj), end="")


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        sys.exit(f"malformed JSON: {path}")


def write_if_changed(path: Path, text: str, dry_run=False) -> bool:
    """Write only on a real change, so no-op runs leave the repo clean."""
    if path.exists() and path.read_text() == text:
        return False
    if not dry_run:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text)
    return True


def load_index() -> dict:
    return read_json(projects_dir() / "index.json", {"projects": []})


def find_entry(index, ref):
    """Resolve a project by name or by worktree path."""
    ref = str(ref)
    for e in index["projects"]:
        if e["name"] == ref:
            return e
    target = Path(ref).resolve()
    for e in index["projects"]:
        if Path(e["worktree"]).resolve() == target:
            return e
    return None


# ---------------------------------------------------------------- git facts

def ahead_behind(path: Path, base: str):
    """(ahead, behind) vs origin/<base>, or (None, None) if the ref is absent."""
    ref = f"origin/{base}"
    if subprocess.run(["git", "-C", str(path), "rev-parse", "--verify", "--quiet", ref],
                      capture_output=True).returncode:
        return None, None
    out = sh("git", "-C", str(path), "rev-list", "--left-right", "--count", f"{ref}...HEAD")
    parts = out.split()
    if len(parts) != 2:
        return None, None
    return int(parts[1]), int(parts[0])   # right=ahead of base, left=behind


def scan_repos(root: Path, prev_repos=None, fetch=False):
    """Git-only facts for every checkout under the worktree. No network unless --fetch."""
    prev = {r["slug"]: r for r in (prev_repos or [])}
    repos = []
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (child / ".git").exists():
            continue
        slug = repo_slug(child)
        if not slug:
            continue
        base = prev.get(slug, {}).get("base", "main")
        if fetch:
            subprocess.run(["git", "-C", str(child), "fetch", "--quiet", "origin", base],
                           capture_output=True)
        ahead, behind = ahead_behind(child, base)
        log = sh("git", "-C", str(child), "log", "-1", "--format=%h%x1f%cI%x1f%s")
        sha, date, subject = (log.split("\x1f") + ["", "", ""])[:3] if log else ("", "", "")
        repos.append({
            "slug": slug,
            "dir": child.name,
            "branch": sh("git", "-C", str(child), "branch", "--show-current"),
            "base": base,
            "ahead": ahead,
            "behind": behind,
            "dirty": bool(sh("git", "-C", str(child), "status", "--porcelain", "-uall")),
            "last_commit": {"sha": sha, "date": date, "subject": subject},
            "prs": [],
        })
    return repos


# ---------------------------------------------------------------- PR detail

ENRICH_FIELDS = """
    id number isDraft reviewDecision
    commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
"""


def enrich(prs):
    """Add node id, review decision, draft flag and check rollup to every PR.

    Batched by GraphQL alias — one request per 40 PRs — because a `gh pr view`
    per PR burns the search quota on a 17-repo worktree. The node id is what
    Projects v2 needs to add an item, so it is collected for closed/merged PRs
    too, not just open ones.
    """
    for i in range(0, len(prs), 40):
        chunk = prs[i:i + 40]
        parts = []
        for n, pr in enumerate(chunk):
            owner, _, name = pr["repo"].partition("/")
            parts.append(
                f'p{n}: repository(owner: "{owner}", name: "{name}") '
                f'{{ pullRequest(number: {pr["number"]}) {{ {ENRICH_FIELDS} }} }}'
            )
        data = gh_json("api", "graphql", "-f", "query=query {" + " ".join(parts) + "}")
        if not data or "data" not in data:
            continue
        for n, pr in enumerate(chunk):
            node = (data["data"] or {}).get(f"p{n}", {})
            node = (node or {}).get("pullRequest") or {}
            pr["node_id"] = node.get("id", "")
            pr["draft"] = bool(node.get("isDraft"))
            if pr["state"] == "OPEN":
                pr["review"] = node.get("reviewDecision") or "REVIEW_REQUIRED"
                commits = (node.get("commits") or {}).get("nodes") or [{}]
                rollup = ((commits[0] or {}).get("commit") or {}).get("statusCheckRollup")
                pr["checks"] = (rollup or {}).get("state") or "NONE"
    for pr in prs:
        pr.setdefault("node_id", "")
        pr.setdefault("draft", False)
        pr.setdefault("review", "")
        pr.setdefault("checks", "")
    return prs


def pr_status(pr):
    """The four board lanes. Review state is a separate field, not a lane."""
    if pr["state"] == "MERGED":
        return "Merged"
    if pr["state"] == "CLOSED":
        return "Cancelled"
    if pr.get("draft"):
        return "Draft"
    return "Open"


def review_label(pr):
    return {"APPROVED": "Approved", "CHANGES_REQUESTED": "Changes requested",
            "REVIEW_REQUIRED": "Review required"}.get(pr.get("review", ""), "")


# ---------------------------------------------------------------- task model
#
# A task is a dict in the manifest's "tasks" list. Only id/title/status/created
# are required; every key added later is OPTIONAL and is dropped when empty, so
# manifests written before this schema existed round-trip byte-for-byte:
#
#   group        "Phase 1 — Policy PoC"   free text, becomes a Group option
#   owner        "TechOps (Patricia)"     free text — a team, a person, or both
#   depends_on   ["t3", "t4"]             other task ids; validated acyclic
#   body         "…"                      instruction text for whoever works it
#   attachments  [{path|url, kind, note}] files the worker must read first
#   start/target "2026-08-10"             ISO dates, plotted by the roadmap
#   last_pushed  {...}                    exactly what the last push wrote
#   human_edited {field: {...}}           a board edit the tool must not undo

TASK_OPTIONAL_KEYS = ("group", "owner", "depends_on", "body", "attachments",
                      "start", "target", "last_pushed", "human_edited")
# Fields a human can meaningfully edit on the board and have merged back.
# "Depends on" and "Blocked" are deliberately NOT here: both are renderings the
# tool owns, and parsing them back would fight the renderer. Dependencies are
# edited with `task dep`.
PULL_FIELDS = {"Status": "status", "Group": "group", "Owner": "owner",
               "Start": "start", "Target": "target"}
# Task-item fields whose empty value must be actively cleared on the board —
# queue_values skips falsy values, so without this a removed group would linger.
CLEARABLE = ("Group", "Owner", "Depends on", "Blocked", "Start", "Target")
ATTACH_BEGIN = "<!-- worktree-sync:attachments -->"
ATTACH_END = "<!-- /worktree-sync:attachments -->"
ATTACH_CONTRACT = (
    "_Read every attachment below before working this task. Paths are relative "
    "to the worktree root; `.drawio` files go through the `kyndryl-drawio-deck` "
    "skill and `.pptx` through the pptx skill._"
)
ATTACH_KINDS = {".drawio": "drawio", ".pptx": "pptx", ".ppt": "pptx",
                ".md": "md", ".png": "image", ".jpg": "image", ".jpeg": "image",
                ".gif": "image", ".svg": "image", ".webp": "image"}
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Tasks are DRAFT issues, and a draft issue has no open/closed state: its dashed
# circle looks identical whether the task is New or Complete, on the board and
# inside a roadmap bar. So the title carries the only completion signal that
# survives into a bar — a Complete task is written to the board as "✓ <title>".
# Render-time only: the manifest, `task list` and the dashboard keep the clean
# title. Set to "" to turn the whole thing off.
DONE_MARKER = "✓ "


def task_num(t) -> int:
    return int(t["id"][1:])


def now_iso() -> str:
    return (datetime.now(timezone.utc).replace(microsecond=0)
            .isoformat().replace("+00:00", "Z"))


def prune_task(t) -> dict:
    """Drop optional keys that carry nothing, so absent stays absent on disk."""
    for k in TASK_OPTIONAL_KEYS:
        if k in t and not t[k]:
            del t[k]
    return t


def group_names(tasks):
    """Distinct groups in first-appearance order (tasks read in id order)."""
    seen = []
    for t in sorted(tasks, key=task_num):
        g = (t.get("group") or "").strip()
        if g and g not in seen:
            seen.append(g)
    return seen


def validate_deps(tasks):
    """Every dependency error, as a list of strings. Empty list == valid."""
    ids = {t["id"] for t in tasks}
    errors = []
    for t in tasks:
        for d in t.get("depends_on") or []:
            if d == t["id"]:
                errors.append(f"{t['id']} depends on itself")
            elif d not in ids:
                errors.append(f"{t['id']} depends on unknown task {d}")
    if errors:
        return errors
    # Kahn: whatever cannot be peeled off is in (or behind) a cycle.
    pending = {t["id"]: set(t.get("depends_on") or []) for t in tasks}
    while True:
        ready = sorted((i for i, d in pending.items() if not d),
                       key=lambda i: int(i[1:]))
        if not ready:
            break
        for i in ready:
            del pending[i]
        for d in pending.values():
            d -= set(ready)
    if pending:
        errors.append("dependency cycle among: " + ", ".join(sorted(pending)))
    return errors


def topo_rank(tasks):
    """{task id: rank} — dependencies first, ties broken by id. Cycles keep
    their manifest order rather than raising; validation is the gate."""
    pending = {t["id"]: set(t.get("depends_on") or []) & {x["id"] for x in tasks}
               for t in tasks}
    rank, n = {}, 0
    while pending:
        ready = sorted((i for i, d in pending.items() if not d),
                       key=lambda i: int(i[1:]))
        if not ready:                       # cycle: fall back to id order
            ready = sorted(pending, key=lambda i: int(i[1:]))
        for i in ready:
            rank[i] = n
            n += 1
            del pending[i]
        for d in pending.values():
            d -= set(ready)
    return rank


def ordered_tasks(tasks):
    """Board/roadmap row order: by group (first-appearance), then dependency
    topology, then id. Ungrouped tasks come last. With no groups and no
    dependencies this is exactly id order, so nothing reshuffles."""
    groups = group_names(tasks)
    rank = topo_rank(tasks)
    return sorted(tasks, key=lambda t: (
        groups.index(t["group"].strip()) if (t.get("group") or "").strip() in groups
        else len(groups),
        rank.get(t["id"], 0), task_num(t)))


def blocked_state(task, by_id):
    """'' (nothing to say), 'Blocked' or 'Ready'.

    Blocked/Ready only describes work that still has to happen, so a Complete
    task is always '' even when it carries dependencies — "Ready" on a finished
    task is noise, and the board field gets actively cleared (Blocked is in
    CLEARABLE) when a task moves into Complete.
    """
    deps = task.get("depends_on") or []
    if not deps or task.get("status") == "Complete":
        return ""
    return "Ready" if all(
        (by_id.get(d) or {}).get("status") == "Complete" for d in deps) else "Blocked"


def deps_label(task, by_id, width=28):
    """The 'Depends on' column: readable ids plus truncated titles."""
    parts = []
    for d in task.get("depends_on") or []:
        title = (by_id.get(d) or {}).get("title", "")
        if len(title) > width:
            title = title[:width - 1].rstrip() + "…"
        parts.append(f"{d} · {title}" if title else d)
    return ", ".join(parts)


def task_json(task, by_id) -> dict:
    """One task as a stable JSON record — the shape every --json command uses.

    Absent optional values are null (not omitted) so a consumer can index every
    key unconditionally. `blocked` is the derived Blocked/Ready state, null once
    the task is Complete or has no dependencies.
    """
    return {
        "id": task["id"],
        "title": task["title"],
        "status": task["status"],
        "created": task.get("created") or None,
        "group": (task.get("group") or "").strip() or None,
        "owner": (task.get("owner") or "").strip() or None,
        "depends_on": list(task.get("depends_on") or []),
        "blocked": blocked_state(task, by_id) or None,
        "start": task.get("start") or None,
        "target": task.get("target") or None,
        "has_body": bool(task.get("body")),
        "attachments": [{"kind": a.get("kind", "other"),
                         "path": a.get("path", ""),
                         "note": a.get("note", "")}
                        for a in task.get("attachments") or []],
        "human_edited": sorted(task.get("human_edited") or {}),
        "draft_id": task.get("draft_id") or None,
    }


def pr_json(pr) -> dict:
    """One PR as a stable JSON record."""
    return {"key": pr["key"], "repo": pr["repo"], "number": pr["number"],
            "title": pr["title"], "status": pr["status"], "state": pr["state"],
            "url": pr["url"], "branch": pr.get("head", ""),
            "draft": bool(pr.get("draft")), "review": review_label(pr) or None,
            "checks": pr.get("checks") or None}


def count_by(values) -> dict:
    out = {}
    for v in values:
        out[v] = out.get(v, 0) + 1
    return out


def attachment_kind(ref) -> str:
    if "://" in ref:
        return "url"
    return ATTACH_KINDS.get(Path(ref).suffix.lower(), "other")


def render_body(task) -> str:
    """The draft-issue body: the owner's text, then a tool-owned attachment
    block between HTML markers. Everything from ATTACH_BEGIN on is regenerated,
    which is what makes a board edit of the prose half recoverable on pull."""
    body = (task.get("body") or "").rstrip()
    atts = task.get("attachments") or []
    if not atts:
        return body
    lines = [ATTACH_BEGIN, "", "### Attachments", "", ATTACH_CONTRACT, ""]
    for a in atts:
        ref = a.get("path") or ""
        shown = f"<{ref}>" if a.get("kind") == "url" else f"`{ref}`"
        note = f" — {a['note']}" if a.get("note") else ""
        lines.append(f"- **{a.get('kind', 'other')}** {shown}{note}")
    lines += ["", ATTACH_END]
    return (body + "\n\n" if body else "") + "\n".join(lines)


def split_body(text) -> str:
    """Recover the owner's half of a body read back off the board."""
    return (text or "").split(ATTACH_BEGIN, 1)[0].rstrip()


def body_hash(text) -> str:
    return hashlib.sha256((text or "").encode()).hexdigest()[:16]


def board_title(task) -> str:
    """The title as written to the board — decorated, never stored.

    A Complete task gets DONE_MARKER prepended; anything else is the manifest
    title verbatim, which is what removes the marker again when a task moves
    back out of Complete. Idempotent: an already-marked title is left alone, so
    a marker a human typed by hand is not doubled.
    """
    title = task["title"]
    if not DONE_MARKER or task.get("status") != "Complete":
        return title
    return title if title.startswith(DONE_MARKER) else DONE_MARKER + title


def strip_done_marker(title) -> str:
    """The clean title behind a board title. The inverse of board_title."""
    title = title or ""
    if DONE_MARKER and title.startswith(DONE_MARKER):
        return title[len(DONE_MARKER):]
    return title


def task_snapshot(task, deps_text, blocked, body_text) -> dict:
    """Exactly what a push wrote, so the next pull can tell a human edit from
    manifest drift. Rendered-only fields are hashed/stored too, but only the
    PULL_FIELDS half is ever compared back.

    "title" is the DECORATED board title, not the manifest one: the snapshot has
    to hold what is really on the board, or the next pull would read the ✓ back,
    diff it against a clean snapshot and stamp a bogus human_edited on every
    completed task.
    """
    return {"blocked": blocked, "body_hash": body_hash(body_text),
            "depends_on": deps_text, "group": (task.get("group") or "").strip(),
            "owner": (task.get("owner") or "").strip(),
            "start": task.get("start") or "", "status": task["status"],
            "target": task.get("target") or "", "title": board_title(task)}


def stamp_blocks(stamp, want) -> bool:
    """Does this human_edited stamp still guard a write of `want`?

    No, if: there is no stamp; the write is the human's own value; or the stamp
    was already acknowledged. `acked_at` only appears on stamps written before
    ack started CLEARING the stamp (see ack_human) — an acked stamp is a
    released one, never a permanent ratchet on the field.
    """
    if not stamp or stamp.get("acked_at"):
        return False
    return want != stamp.get("value") and want != stamp.get("acked_value")


def conflicts(task, fields=None):
    """[(field, human_value, tool_value, when)] where the manifest now wants to
    change something a human set on the board and nobody acknowledged it."""
    out = []
    for field, stamp in sorted((task.get("human_edited") or {}).items()):
        if fields and field not in fields:
            continue
        want = task.get(field) if field != "status" else task["status"]
        want = (want or "") if isinstance(want, str) else want
        if not stamp_blocks(stamp, want):
            continue
        out.append((field, stamp.get("value"), want, stamp.get("at", "?")))
    return out


def fix_command(project, task, field, value):
    """The exact command that would take the tool's value forward for a field."""
    tid, val = task["id"], f'"{value}"' if value else '""'
    if field in ("group", "owner"):
        return f"task set {project} {tid} {field} {val} --ack-human"
    if field in ("start", "target"):
        return (f"task dates {project} {tid} {task.get('start') or '-'} "
                f"{task.get('target') or '-'} --ack-human")
    if field == "body":
        return f"task body {project} {tid} --file <path> --ack-human"
    if field == "title":
        return f"task set {project} {tid} {task['status'].lower()} {val} --ack-human"
    return f"task set {project} {tid} <new|wip|done> --ack-human"


def print_conflict(project, task, rows):
    """The quotable prompt an agent must relay verbatim — never resolve alone."""
    print("", file=sys.stderr)
    print("HUMAN-EDITED ON THE BOARD — needs a decision, not a retry", file=sys.stderr)
    print(f"  project : {project}", file=sys.stderr)
    print(f"  task    : {task['id']}  {task['title']}", file=sys.stderr)
    for field, human, tool, when in rows:
        print(f"  field   : {field}", file=sys.stderr)
        print(f"    human set : {human!r}   (on GitHub, {when})", file=sys.stderr)
        print(f"    tool wants: {tool!r}", file=sys.stderr)
    print("  options :", file=sys.stderr)
    print("    keep    — do nothing; the human's value stands", file=sys.stderr)
    for field, human, tool, _when in rows:
        print(f"    accept  — worktree_sync.py "
              f"{fix_command(project, task, field, tool)}", file=sys.stderr)
        print(f"    revert  — worktree_sync.py "
              f"{fix_command(project, task, field, human)}".replace(
                  " --ack-human", "  (drop --ack-human: it is already his value)"),
              file=sys.stderr)
    print("  Ask the owner which one. Do not choose for him.", file=sys.stderr)


def ack_human(task, fields=None):
    """The owner approved overwriting his own board edit — RELEASE the guard.

    Ack clears the stamp. It used to only whitelist the one acked value, which
    ratcheted: a later write of a DIFFERENT value, with no new human
    involvement, exited 3 again quoting the original board value, so the field
    drifted toward being uneditable without the one flag the skill says never to
    pass on your own judgement. Clearing puts the field back to normal until a
    human next edits it on the board — `pull_project` re-stamps it then, so
    nothing is lost, and the very next push re-snapshots `last_pushed`.

    Returns the fields it released.
    """
    stamps = task.get("human_edited") or {}
    released = [f for f in sorted(stamps) if not fields or f in fields]
    for field in released:
        del stamps[field]
    if not stamps:
        task.pop("human_edited", None)
    return released


# ---------------------------------------------------------------- commands

def cmd_scan(args):
    root = Path(args.worktree).resolve()
    if not root.is_dir():
        sys.exit(f"not a directory: {root}")
    entry = find_entry(load_index(), root) or {}
    prev = read_json(projects_dir() / f"{entry.get('name', '')}.json", {}) or {}
    repos = scan_repos(root, prev.get("repos"), fetch=args.fetch)
    if args.json:
        emit_json(repos)
        return
    print(f"{root}   {len(repos)} repos")
    for r in repos:
        ab = "-" if r["ahead"] is None else f"+{r['ahead']}/-{r['behind']}"
        flag = " DIRTY" if r["dirty"] else ""
        print(f"  {r['slug']:<62} {r['branch']:<34} base={r['base']:<16} {ab}{flag}")


def build_manifest(entry, root, prev, fetch=False):
    """Everything for one worktree. Hand-edited keys merge forward untouched."""
    repos = scan_repos(root, prev.get("repos"), fetch=fetch)
    overrides = prev.get("branches") or {}
    found = discover(root, overrides, strict=False)

    prs_by_key = find_prs(found, prev.get("extra_prs", []), prev.get("exclude_prs", []))
    prs = enrich(sorted(prs_by_key.values(), key=lambda p: (p["repo"], p["number"])))
    for pr in prs:
        pr["status"] = pr_status(pr)

    by_repo = {}
    for pr in prs:
        by_repo.setdefault(pr["repo"], []).append(pr["key"])
    for r in repos:
        r["prs"] = sorted(by_repo.get(r["slug"], []))

    # A repo's own base branch is not "work without a PR", so it is filtered out
    # here rather than in wt_common — only worktree_sync knows the per-repo base.
    bases = {r["slug"]: r["base"] for r in repos}
    covered = {(pr["repo"], pr["head"]) for pr in prs}
    no_pr = sorted(
        f"{slug}:{b}" for slug, branches in found.items()
        for b in branches
        if (slug, b) not in covered and b != bases.get(slug)
    )

    view = dict(prev.get("view") or {})
    if prs:
        query, _, stray = build_query(prs_by_key, prev.get("since"))
        view = {
            "name": view.get("name") or worktree_name(root),
            "color": view.get("color", "purple"),
            "icon": view.get("icon", "code-review"),
            "query": query,
            "url": "https://github.com/pulls?q=" + urllib.parse.quote(query, safe=""),
            "stray": stray,
        }

    return {
        "name": entry["name"],
        "worktree": str(root),
        "lane": entry.get("lane", ""),
        "repos": repos,
        "prs": prs,
        "branches_no_pr": no_pr,
        "view": view,
        # hand-edited, never clobbered
        "tasks": prev.get("tasks", []),
        "notes": prev.get("notes", []),
        "extra_prs": prev.get("extra_prs", []),
        "exclude_prs": prev.get("exclude_prs", []),
        "branches": overrides,
        "since": prev.get("since"),
    }


def cmd_sync(args):
    index = load_index()
    entry = find_entry(index, args.worktree)
    if not entry:
        sys.exit(f"not a tracked project: {args.worktree}\n"
                 f"add it to {projects_dir() / 'index.json'} first")
    root = Path(entry["worktree"]).resolve()
    if not root.is_dir():
        sys.exit(f"worktree is gone: {root}")

    path = projects_dir() / f"{entry['name']}.json"
    prev = read_json(path, {}) or {}
    manifest = build_manifest(entry, root, prev, fetch=args.fetch)

    # Human board edits are merged in BEFORE anything is written or pushed, so a
    # session can never silently overwrite one. Best-effort: no project, no
    # 'project' scope, or an API hiccup all degrade to "nothing merged".
    pulled = []
    if not args.no_pull:
        pulled = pull_project(entry, manifest, dry_run=True)
        if not args.json:
            for rec in pulled:
                print(f"  HUMAN: {pull_line(rec)}")

    # generated_at only moves when something else did, so no-ops stay clean
    body_changed = {k: v for k, v in prev.items() if k != "generated_at"} != manifest
    manifest["generated_at"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if body_changed or not prev.get("generated_at") else prev["generated_at"]
    )

    changed = write_if_changed(path, dump(manifest), args.dry_run)

    if args.json:
        # The manifest itself IS the machine-readable result of a sync; the
        # merged human edits are already folded into it, so nothing is lost by
        # staying silent about them here.
        emit_json(manifest)
    else:
        old_keys = {p["key"] for p in prev.get("prs", [])}
        new_keys = {p["key"] for p in manifest["prs"]}
        prefix = "[dry-run] " if args.dry_run else ""
        print(f"{prefix}{entry['name']}: {len(manifest['repos'])} repos, "
              f"{len(manifest['prs'])} PRs, "
              f"{len(manifest['branches_no_pr'])} branches without a PR")
        if new_keys - old_keys:
            print(f"  NEW  : {', '.join(sorted(new_keys - old_keys))}")
        if old_keys - new_keys:
            print(f"  GONE : {', '.join(sorted(old_keys - new_keys))}")
        if manifest["view"].get("stray"):
            print(f"  WARNING: view query returns {len(manifest['view']['stray'])} "
                  f"unrelated PR(s) — add them to exclude_prs or set \"since\"")
        if any(r["dirty"] for r in manifest["repos"]):
            dirty = [r["slug"] for r in manifest["repos"] if r["dirty"]]
            print(f"  DIRTY: {', '.join(dirty)}")
        print(f"  {'would write' if args.dry_run else 'wrote'} {path}"
              if changed else "  no change")

    if args.commit and not args.dry_run:
        render(dry_run=False)
        do_commit(f"chore(projects): sync {entry['name']}", dry_run=False)


def render_tasks(tasks):
    """Dashboard task tables, one per Group in group order.

    Every column beyond Task/Status/Title is conditional: a manifest whose tasks
    use none of the new keys renders exactly the table it rendered before, which
    is what keeps `git status projects/` honest as the "nothing moved" signal.
    """
    if not tasks:
        return []
    by_id = {t["id"]: t for t in tasks}
    groups = group_names(tasks)
    has_owner = any((t.get("owner") or "").strip() for t in tasks)
    has_deps = any(t.get("depends_on") for t in tasks)
    has_dates = any(t.get("start") or t.get("target") for t in tasks)
    has_notes = any(t.get("body") or t.get("attachments") or t.get("human_edited")
                    for t in tasks)
    head = ["Task", "Status"]
    head += ["Owner"] if has_owner else []
    head += ["Depends on"] if has_deps else []
    head += ["Dates"] if has_dates else []
    head += ["Title"]
    head += ["Notes"] if has_notes else []

    def row(t):
        cells = [f"`{t['id']}`", t["status"]]
        if has_owner:
            cells.append((t.get("owner") or "").strip() or "—")
        if has_deps:
            ids = ", ".join(f"`{d}`" for d in t.get("depends_on") or []) or "—"
            state = blocked_state(t, by_id)
            cells.append(f"{ids} **blocked**" if state == "Blocked" else ids)
        if has_dates:
            span = " → ".join(x for x in (t.get("start"), t.get("target")) if x)
            cells.append(span or "—")
        cells.append(t["title"])
        if has_notes:
            note = []
            if t.get("body"):
                note.append("body")
            if t.get("attachments"):
                note.append(f"{len(t['attachments'])} file(s)")
            if t.get("human_edited"):
                note.append("human: " + ", ".join(sorted(t["human_edited"])))
            cells.append(" · ".join(note) or "—")
        return "| " + " | ".join(cells) + " |"

    lines, ordered = [], ordered_tasks(tasks)
    for group in (groups + [""] if groups else [""]):
        rows = [t for t in ordered if (t.get("group") or "").strip() == group]
        if not rows:
            continue
        if groups:
            lines += [f"**{group or '(no group)'}**", ""]
        lines += ["| " + " | ".join(head) + " |",
                  "| " + " | ".join("---" for _ in head) + " |"]
        lines += [row(t) for t in rows]
        lines.append("")
    return lines


def render(dry_run=False) -> bool:
    """Regenerate projects/README.md — the Copilot/human-readable dashboard."""
    index = load_index()
    lines = [
        "# Worktree projects",
        "",
        "Generated by `worktree_sync.py render` — do not edit by hand.",
        "Source of truth is the per-project JSON next to this file.",
        "",
    ]
    for entry in sorted(index["projects"], key=lambda e: e["name"]):
        m = read_json(projects_dir() / f"{entry['name']}.json")
        if not m:
            continue
        lines += [f"## {m['name']}", "",
                  f"`{m['worktree']}` · lane `{m['lane']}` · "
                  f"{len(m['repos'])} repos · {len(m['prs'])} PRs · "
                  f"{len(m.get('tasks', []))} tasks · "
                  f"synced {m.get('generated_at', '?')}", ""]
        gp = entry.get("github_project") or {}
        if gp.get("url"):
            lines += [f"Board: [{gp.get('title', gp['url'])}]({gp['url']})", ""]
        if m.get("notes"):
            lines += [f"> {n}" for n in m["notes"]] + [""]
        lines += render_tasks(m.get("tasks") or [])
        lines += ["| Repo | Branch | Base | Ahead/Behind | PRs |",
                  "| --- | --- | --- | --- | --- |"]
        prs = {p["key"]: p for p in m["prs"]}
        for r in m["repos"]:
            ab = "—" if r["ahead"] is None else f"+{r['ahead']} / −{r['behind']}"
            cell = []
            for key in r["prs"]:
                p = prs[key]
                cell.append(f"[#{p['number']}]({p['url']}) {p['status']}")
            dirty = " ⚠️dirty" if r["dirty"] else ""
            lines.append(
                f"| [{r['slug']}](https://github.com/{r['slug']}) | "
                f"`{r['branch']}`{dirty} | `{r['base']}` | {ab} | "
                f"{'<br>'.join(cell) or '—'} |"
            )
        lines.append("")
        if m.get("branches_no_pr"):
            lines += ["**Branches with no PR yet:** "
                      + ", ".join(f"`{b}`" for b in m["branches_no_pr"]), ""]
        if m["view"].get("url"):
            lines += [f"[All PRs for this worktree]({m['view']['url']})", ""]
    return write_if_changed(projects_dir() / "README.md", "\n".join(lines), dry_run)


def cmd_render(args):
    changed = render(args.dry_run)
    print(("would update " if args.dry_run else "updated ") + str(projects_dir() / "README.md")
          if changed else "README.md already current")


def status_json(entry, manifest) -> dict:
    """One project's status as a stable JSON record.

    Shape is identical with and without -v: --json always carries the full
    `tasks`/`prs` arrays, because a machine reader has no use for a verbosity
    switch. `synced` is null and `tracked_only` true for a project that is in
    index.json but has never been synced.
    """
    gp = entry.get("github_project") or {}
    if not manifest:
        return {"name": entry["name"], "lane": entry.get("lane", ""),
                "worktree": entry.get("worktree", ""), "synced": None,
                "tracked_only": True, "board_url": gp.get("url") or None,
                "repos": 0, "pr_count": 0, "pr_status": {}, "prs": [],
                "task_count": 0, "task_open": 0, "task_status": {}, "tasks": [],
                "branches_no_pr": 0, "human_edited": []}
    tasks = manifest.get("tasks") or []
    by_id = {t["id"]: t for t in tasks}
    return {
        "name": manifest["name"],
        "lane": manifest.get("lane", ""),
        "worktree": manifest.get("worktree", ""),
        "synced": manifest.get("generated_at") or None,
        "tracked_only": False,
        "board_url": gp.get("url") or None,
        "repos": len(manifest.get("repos") or []),
        "pr_count": len(manifest.get("prs") or []),
        "pr_status": count_by(p["status"] for p in manifest.get("prs") or []),
        "prs": [pr_json(p) for p in manifest.get("prs") or []],
        "task_count": len(tasks),
        "task_open": len([t for t in tasks if t["status"] != "Complete"]),
        "task_status": count_by(t["status"] for t in tasks),
        "tasks": [task_json(t, by_id) for t in ordered_tasks(tasks)],
        "branches_no_pr": len(manifest.get("branches_no_pr") or []),
        "human_edited": [f"{t['id']}.{f}" for t in sorted(tasks, key=task_num)
                         for f in sorted(t.get("human_edited") or {})],
    }


def cmd_status(args):
    index = load_index()
    entries = [e for e in index["projects"] if not args.name or e["name"] == args.name]
    if not entries:
        sys.exit("no tracked projects" + (f" named {args.name}" if args.name else ""))
    if args.json:
        emit_json({"projects": [
            status_json(e, read_json(projects_dir() / f"{e['name']}.json"))
            for e in entries]})
        return
    for e in entries:
        m = read_json(projects_dir() / f"{e['name']}.json")
        if not m:
            print(f"{e['name']}: never synced")
            continue
        counts = {}
        for p in m["prs"]:
            counts[p["status"]] = counts.get(p["status"], 0) + 1
        summary = ", ".join(f"{v} {k.lower()}" for k, v in sorted(counts.items())) or "no PRs"
        open_tasks = [t for t in m.get("tasks", []) if t["status"] != "Complete"]
        print(f"{m['name']:<24} {len(m['repos'])} repos   {summary}   "
              f"{len(open_tasks)} open task(s)   (synced {m.get('generated_at', '?')})")
        if args.verbose:
            for t in m.get("tasks", []):
                print(f"    {t['status']:<18} {t['id']:<58} {t['title'][:56]}")
            for p in m["prs"]:
                print(f"    {p['status']:<18} {p['key']:<58} {p['title'][:56]}")


def do_commit(message, dry_run=False):
    """Commit projects/ to the dotfiles checkout's current branch, and push it.

    The Codespace exports GIT_COMMITTER_* as "GitHub <noreply@github.com>", which
    would otherwise land on every commit, so both author and committer are forced
    on the command itself.

    The push target is the branch that is checked out, NOT a hardcoded main: while
    a tooling branch is checked out here, `HEAD:main` would quietly land that
    branch's commits on main — a merge nobody asked for, and the one mistake in
    this repo that cannot be undone by explaining it afterwards.
    """
    d = dotfiles_dir()
    if dry_run:
        print(f"[dry-run] would commit+push {d}/projects")
        return
    subprocess.run(["git", "-C", str(d), "add", "projects"], check=True)
    if subprocess.run(["git", "-C", str(d), "diff", "--cached", "--quiet", "projects"]
                      ).returncode == 0:
        print("nothing to commit")
        return
    env = {**os.environ,
           "GIT_AUTHOR_NAME": COMMITTER[0], "GIT_AUTHOR_EMAIL": COMMITTER[1],
           "GIT_COMMITTER_NAME": COMMITTER[0], "GIT_COMMITTER_EMAIL": COMMITTER[1]}
    subprocess.run(["git", "-C", str(d), "commit", "-m", message], env=env, check=True)
    print(sh("git", "-C", str(d), "log", "-1", "--format=%h %an <%ae> | %cn <%ce>"))
    branch = sh("git", "-C", str(d), "rev-parse", "--abbrev-ref", "HEAD").strip()
    push = subprocess.run(["git", "-C", str(d), "push", "origin", f"HEAD:{branch}"],
                          capture_output=True, text=True)
    if push.returncode:
        print(push.stderr.strip(), file=sys.stderr)
        print("\npush failed — klalter_kyndryl cannot push to klalter/dotfiles.\n"
              "See the dotfiles-push-token-override note: reset the scoped\n"
              "http.extraheader with the 'klalter' token, then re-run "
              "`worktree_sync.py commit`.", file=sys.stderr)
        sys.exit(1)
    # Name the branch that was actually pushed. This line used to read
    # "pushed to origin/main" no matter where the push went; an agent relays it
    # verbatim, and falsely claiming a push to main is the single most dangerous
    # thing this tool can say.
    print(f"pushed to origin/{branch}")


def cmd_commit(args):
    do_commit(args.message, args.dry_run)


def project_env():
    """gh env with the Codespace tokens stripped.

    The Codespace exports GH_TOKEN and GITHUB_TOKEN, and both take priority over
    the token in hosts.yml — so after `gh auth refresh -s project` the refreshed,
    correctly-scoped token is ignored unless they are unset for the call.
    """
    return {k: v for k, v in os.environ.items() if k not in ("GH_TOKEN", "GITHUB_TOKEN")}


# One GitHub project per tracked worktree, titled after it (feat/agent-kaif-deploy).
#
# Two first-class item kinds share the project, split into views by field:
#   Task   — a unit of work, usually spun up mid-conversation; draft-issue item,
#            lanes on the built-in Status field (New / In progress / Complete).
#   PR     — every pull request the worktree produced; lanes on "PR status".
#   Branch — a branch with no PR yet; kept for visibility, shown in no view.
TASK_STATUSES = ["New", "In progress", "Complete"]
PR_STATUSES = ["Draft", "Open", "Merged", "Cancelled"]
KINDS = ["Task", "PR", "Branch"]
BLOCKED_STATES = ["Blocked", "Ready"]
OPTION_COLORS = {"New": "GRAY", "In progress": "YELLOW", "Complete": "GREEN",
                 "Draft": "GRAY", "Open": "BLUE", "Merged": "PURPLE",
                 "Cancelled": "RED", "Task": "PINK", "PR": "BLUE", "Branch": "GRAY",
                 "Blocked": "RED", "Ready": "GREEN"}
# Groups are free text, so their option colours cycle by position instead.
GROUP_PALETTE = ["BLUE", "GREEN", "ORANGE", "PURPLE", "PINK", "YELLOW", "RED"]
TASK_ALIASES = {"new": "New", "todo": "New",
                "wip": "In progress", "started": "In progress",
                "in-progress": "In progress", "progress": "In progress",
                "done": "Complete", "complete": "Complete", "completed": "Complete"}
# The four views, created/repaired on every push. All filter on the custom
# Kind field: the built-in "type:pr" qualifier rendered an EMPTY view when
# tried, while custom-field filters are proven to work. (Kind is named Kind,
# not Type, so its filter can't collide with the built-in type qualifier.)
# The last element is the visible-column list — without it the PR views show
# the built-in Status column, which PRs never fill, reading as "No status".
#
# Both boards group by the BUILT-IN Status field, which is what a board
# groups by by default — task lanes and PR lanes are all options of that one
# field, because the API cannot set a board's column field, and this is the
# only way both boards come up grouped correctly with zero UI setup. The
# price is a few empty columns per board (hideable in the UI, cosmetic).
#
# "Tasks · Roadmap" is a real ROADMAP_LAYOUT view — the enum value exists and
# createProjectV2View accepts it, and its filter is settable. Two things about
# it are NOT settable by any mutation and stay one-off UI steps: which DATE
# fields it plots (ProjectV2ViewConfigurationInput carries only visibleFieldIds)
# and what it groups by (groupByFields is readable, never writable). Roadmap
# views also REJECT visibleFieldIds outright — "Roadmap views do not support
# visible fields" — so its column list is None, meaning "send no configuration".
VIEW_SPEC = [
    ("Tasks · Board", "BOARD_LAYOUT", "kind:Task",
     ["Title", "Status", "Group", "Owner", "Depends on", "Blocked", "Last sync"]),
    ("Tasks · List", "TABLE_LAYOUT", "kind:Task",
     ["Title", "Status", "Group", "Owner", "Depends on", "Blocked",
      "Start", "Target", "Last sync"]),
    ("Tasks · Roadmap", "ROADMAP_LAYOUT", "kind:Task", None),
    ("PRs · Board", "BOARD_LAYOUT", "kind:PR",
     ["Title", "PR #", "Status", "Review", "Repo name"]),
    ("PRs · List", "TABLE_LAYOUT", "kind:PR",
     ["Title", "PR #", "Status", "Review", "Org", "Repo name",
      "Branch", "Base", "Last sync"]),
]
# Fields from earlier schema generations, deleted on sight.
LEGACY_FIELDS = ["PR status", "Repo slug"]


def gql(query, allow_error=False):
    """One GraphQL call with the Codespace tokens stripped.

    Mutations are paced (GitHub asks for ~1s between content mutations) and
    secondary-rate-limit responses are retried with a long backoff — 48
    back-to-back item adds reliably trip the limit otherwise.
    """
    if query.lstrip().startswith("mutation"):
        time.sleep(0.8)
    for attempt in range(4):
        r = subprocess.run(["gh", "api", "graphql", "-f", f"query={query}"],
                           capture_output=True, text=True, env=project_env())
        try:
            payload = json.loads(r.stdout) if r.stdout else {}
        except json.JSONDecodeError:
            payload = {}
        if "data" in payload and "errors" not in payload:
            return payload["data"]
        msg = (payload.get("errors", [{}])[0].get("message")
               or r.stderr.strip() or "unknown GraphQL error")
        if "rate limit" in msg.lower() and attempt < 3:
            wait = 60 * (attempt + 1)
            print(f"  rate limited — waiting {wait}s…", file=sys.stderr)
            time.sleep(wait)
            continue
        if allow_error:
            return None
        sys.exit(f"GraphQL failed: {msg}")


def s(value) -> str:
    """A GraphQL string literal. JSON escaping is GraphQL-compatible."""
    return json.dumps("" if value is None else str(value))


def ensure_project(title, dry_run=False):
    """Find the viewer's project with this title, creating it if absent."""
    data = gql("query{viewer{id projectsV2(first:100){nodes{id number title url}}}}")
    viewer = data["viewer"]
    for node in viewer["projectsV2"]["nodes"]:
        if node["title"] == title:
            return node
    if dry_run:
        return None
    data = gql(
        f'mutation{{createProjectV2(input:{{ownerId:{s(viewer["id"])},'
        f'title:{s(title)}}}){{projectV2{{id number title url}}}}}}')
    return data["createProjectV2"]["projectV2"]


def field_spec(manifest=None):
    """The fields one worktree-project needs, with their single-select options.

    "Status" is the BUILT-IN single-select, repurposed to hold ALL lanes —
    task lanes and PR lanes as one option set — so that both boards group
    correctly with zero UI configuration (a board view always groups by
    Status, and the API cannot change a board's column field). Its stock
    Todo/In Progress/Done options are REPLACED, not extended. "Repo" is
    rejected as a reserved name (GitHub aliases it to the built-in Repository
    field), hence Org + "Repo name". "Group" was probed and is NOT reserved.

    "Group" is only in the spec once some task carries one: a SINGLE_SELECT
    must be created with at least one option ("At least one singleSelectOption
    is required for data_type SINGLE_SELECT"), and inventing a placeholder
    option would be a lie on the board.
    """
    groups = group_names((manifest or {}).get("tasks") or [])
    spec = [
        ("Kind", "SINGLE_SELECT", KINDS),
        ("Status", "SINGLE_SELECT", TASK_STATUSES + PR_STATUSES),
    ]
    if groups:
        spec.append(("Group", "SINGLE_SELECT", groups))
    spec += [
        # Free TEXT on purpose: "TechOps (Patricia)" is a team plus a person, and
        # a select would force a taxonomy nobody has. "Owner" was probed and is
        # free; "Assignee" IS reserved ("Name cannot have a reserved value").
        ("Owner", "TEXT", None),
        ("Depends on", "TEXT", None),
        ("Blocked", "SINGLE_SELECT", BLOCKED_STATES),
        ("Start", "DATE", None),
        ("Target", "DATE", None),
        ("PR #", "TEXT", None),
        ("Org", "TEXT", None),
        ("Repo name", "TEXT", None),
        ("Branch", "TEXT", None),
        ("Base", "TEXT", None),
        ("Review", "TEXT", None),
        ("Last sync", "DATE", None),
    ]
    return spec


def _options_literal(names, known=None):
    """Option list for create/update.

    Existing options are re-sent WITH their id: ProjectV2SingleSelectFieldOptionInput
    takes an optional id, and without it an update recreates the options and drops
    every value already assigned to them.
    """
    known = known or {}
    out = []
    for i, n in enumerate(names):
        color = OPTION_COLORS.get(n) or GROUP_PALETTE[i % len(GROUP_PALETTE)]
        oid = f'id:{s(known[n])},' if n in known else ""
        out.append(f'{{{oid}name:{s(n)},color:{color},description:{s("")}}}')
    return "[" + ",".join(out) + "]"


def ensure_fields(project_id, spec, dry_run=False):
    """Create missing fields and reconcile single-select options.

    The built-in Status field gets its options REPLACED (the stock
    Todo/In Progress/Done must go so the Task lanes are the only columns);
    every other single-select is extended, never shrunk, so a hand-added
    option survives.
    """
    q = (f'query{{node(id:{s(project_id)}){{... on ProjectV2{{fields(first:50){{nodes{{'
         f'... on ProjectV2FieldCommon{{id name dataType}} '
         f'... on ProjectV2SingleSelectField{{id name dataType options{{id name}}}}'
         f'}}}}}}}}}}')
    existing = {f["name"]: f for f in gql(q)["node"]["fields"]["nodes"] if f}
    created = []
    for legacy in LEGACY_FIELDS:
        if legacy in existing and not dry_run:
            gql(f'mutation{{deleteProjectV2Field(input:{{'
                f'fieldId:{s(existing[legacy]["id"])}}}){{projectV2Field{{'
                f'... on ProjectV2FieldCommon{{id}}}}}}}}', allow_error=True)
            created.append(f"{legacy} (deleted)")
    for name, dtype, options in spec:
        cur = existing.get(name)
        if not cur:
            if dry_run:
                created.append(name)
                continue
            opts = f",singleSelectOptions:{_options_literal(options)}" if options else ""
            gql(f'mutation{{createProjectV2Field(input:{{projectId:{s(project_id)},'
                f'dataType:{dtype},name:{s(name)}{opts}}}){{projectV2Field{{'
                f'... on ProjectV2FieldCommon{{id name}}}}}}}}')
            created.append(name)
        elif options:
            have = [o["name"] for o in cur.get("options", [])]
            known = {o["name"]: o["id"] for o in cur.get("options", [])}
            wanted = options if name == "Status" else (
                have + [o for o in options if o not in have])
            if have != wanted:
                if not dry_run:
                    gql(f'mutation{{updateProjectV2Field(input:{{fieldId:{s(cur["id"])},'
                        f'singleSelectOptions:{_options_literal(wanted, known)}}})'
                        f'{{projectV2Field{{... on ProjectV2FieldCommon{{id}}}}}}}}')
                created.append(f"{name} (options)")
    fields = {f["name"]: f for f in gql(q)["node"]["fields"]["nodes"] if f}
    return fields, created


ITEM_QUERY = """
... on ProjectV2Item {
  id
  content { __typename
    ... on PullRequest { url }
    ... on DraftIssue { id title body } }
  fieldValues(first: 30) { nodes {
    ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { name } } }
    ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } }
    ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } }
  } }
}
"""


def item_key(content):
    """Stable identity for a board item.

    PRs key on URL; branch drafts key on their 'owner/repo:branch' title.
    Task drafts are NOT identified by title at all — their DraftIssue id is
    recorded as draft_id in the manifest, so titles stay clean and retitles
    update in place. The 't<n> · ' pattern is only recognised to adopt items
    created before that change.
    """
    if content.get("url"):
        return content["url"]
    title = content.get("title") or ""
    tid = title.split(" · ", 1)[0]
    if tid[:1] == "t" and tid[1:].isdigit():
        return f"task:{tid}"
    return title


def list_items(project_id):
    """({key: item}, [item ids in board order]) for the whole project."""
    items, order, after = {}, [], None
    while True:
        cursor = f',after:{s(after)}' if after else ""
        data = gql(f'query{{node(id:{s(project_id)}){{... on ProjectV2{{'
                   f'items(first:100{cursor}){{pageInfo{{hasNextPage endCursor}}'
                   f'nodes{{{ITEM_QUERY}}}}}}}}}}}')
        page = data["node"]["items"]
        for n in page["nodes"]:
            if not n:
                continue
            content = n.get("content") or {}
            key = item_key(content)
            if not key:
                continue
            values = {}
            for fv in n["fieldValues"]["nodes"]:
                if not fv or not fv.get("field"):
                    continue
                values[fv["field"]["name"]] = (
                    fv.get("text") or fv.get("date") or fv.get("name"))
            items[key] = {"id": n["id"], "values": values,
                          "content_id": content.get("id"),
                          "title": content.get("title"),
                          "body": content.get("body") or "",
                          "draft": content.get("__typename") == "DraftIssue"}
            order.append(n["id"])
        if not page["pageInfo"]["hasNextPage"]:
            return items, order
        after = page["pageInfo"]["endCursor"]


def value_literal(field, value):
    dtype = field["dataType"]
    if dtype == "TEXT":
        return f"{{text:{s(value)}}}"
    if dtype == "DATE":
        return f"{{date:{s(value)}}}"
    if dtype == "SINGLE_SELECT":
        for o in field.get("options", []):
            if o["name"] == value:
                return f"{{singleSelectOptionId:{s(o['id'])}}}"
    return None


def apply_updates(project_id, updates, dry_run=False):
    """Batch field writes, ~20 aliased mutations per request."""
    if dry_run or not updates:
        return len(updates)
    for i in range(0, len(updates), 20):
        parts = []
        for n, (item_id, field, value) in enumerate(updates[i:i + 20]):
            lit = value_literal(field, value)
            if not lit:
                continue
            parts.append(
                f'm{n}:updateProjectV2ItemFieldValue(input:{{projectId:{s(project_id)},'
                f'itemId:{s(item_id)},fieldId:{s(field["id"])},value:{lit}}})'
                f'{{projectV2Item{{id}}}}')
        if parts:
            gql("mutation{" + " ".join(parts) + "}")
    return len(updates)


def apply_clears(project_id, clears, dry_run=False):
    """Blank a field that used to have a value — queue_values only ever sets."""
    if dry_run or not clears:
        return len(clears)
    for i in range(0, len(clears), 20):
        parts = [
            f'c{n}:clearProjectV2ItemFieldValue(input:{{projectId:{s(project_id)},'
            f'itemId:{s(item_id)},fieldId:{s(field["id"])}}}){{projectV2Item{{id}}}}'
            for n, (item_id, field) in enumerate(clears[i:i + 20])]
        gql("mutation{" + " ".join(parts) + "}")
    return len(clears)


def apply_drafts(drafts, dry_run=False):
    """Title/body writes on draft issues, ~10 aliased mutations per request."""
    if dry_run or not drafts:
        return len(drafts)
    for i in range(0, len(drafts), 10):
        parts = []
        for n, (content_id, title, body) in enumerate(drafts[i:i + 10]):
            parts.append(
                f'd{n}:updateProjectV2DraftIssue(input:{{draftIssueId:{s(content_id)},'
                f'title:{s(title)},body:{s(body)}}}){{draftIssue{{id}}}}')
        gql("mutation{" + " ".join(parts) + "}")
    return len(drafts)


def ensure_views(project_id, fields, dry_run=False):
    """Create/repair the four standard views; drop the stock 'View 1'.

    Boards group by the built-in Status field — the default a board view is
    born with, and the API cannot change a board's column field — which is why
    Status holds every lane (task AND PR). Sorting also has no mutation, but a
    saved sort IS readable: a view found carrying one is deleted and recreated
    fresh, because a stray sort (e.g. by Base) scrambles the row order the
    item-position pass maintains.
    """
    data = gql(f'query{{node(id:{s(project_id)}){{... on ProjectV2{{'
               f'views(first:20){{nodes{{id name layout filter '
               f'sortByFields(first:5){{nodes{{direction}}}} '
               f'fields(first:30){{nodes{{... on ProjectV2FieldCommon{{id}}}}}}}}}}}}}}}}')
    existing = {v["name"]: v for v in data["node"]["views"]["nodes"] if v}
    touched = []
    for name, layout, flt, columns in VIEW_SPEC:
        view = existing.get(name)
        if view and (view.get("sortByFields") or {}).get("nodes"):
            if dry_run:
                touched.append(f"{name} (recreate: stray sort)")
                continue
            gql(f'mutation{{deleteProjectV2View(input:{{viewId:{s(view["id"])}}})'
                f'{{projectV2View{{id}}}}}}', allow_error=True)
            view = None
            touched.append(f"{name} (recreated: stray sort)")
        if not view:
            if dry_run:
                touched.append(name)
                continue
            data = gql(f'mutation{{createProjectV2View(input:{{'
                       f'projectId:{s(project_id)},name:{s(name)},layout:{layout}}})'
                       f'{{projectV2View{{id}}}}}}')
            view = {"id": data["createProjectV2View"]["projectV2View"]["id"],
                    "filter": None, "layout": layout}
            touched.append(name)
        parts = []
        if view.get("filter") != flt:
            parts.append(f"filter:{s(flt)}")
        if view.get("layout") != layout:
            parts.append(f"layout:{layout}")
        # columns is None for the roadmap, which rejects visibleFieldIds.
        if columns is not None:
            want_cols = [fields[c]["id"] for c in columns if c in fields]
            have_cols = [f["id"] for f in (view.get("fields") or {}).get("nodes", []) if f]
            # GitHub does not preserve visibleFieldIds order, so compare as sets —
            # an ordered diff re-sends the config on every push, forever.
            if want_cols and set(have_cols) != set(want_cols):
                ids = ",".join(s(i) for i in want_cols)
                parts.append(f"configuration:{{visibleFieldIds:[{ids}]}}")
        if parts and not dry_run:
            gql(f'mutation{{updateProjectV2View(input:{{viewId:{s(view["id"])},'
                f'{",".join(parts)}}}){{projectV2View{{id}}}}}}')
            if name not in touched:
                touched.append(f"{name} (config)")
    stock = existing.get("View 1")
    if stock and len(existing) > 1 or (stock and touched):
        if not dry_run:
            gql(f'mutation{{deleteProjectV2View(input:{{viewId:{s(stock["id"])}}})'
                f'{{projectV2View{{id}}}}}}', allow_error=True)
    return touched


def conflict_json(project, task, rows):
    """The exit-3 payload: one record per field a human owns and the tool wants
    to change, with the exact commands that would resolve it either way."""
    return [{"task": task["id"], "title": task["title"], "field": field,
             "human_value": human, "tool_value": tool, "human_set_at": when,
             "accept_command": f"worktree_sync.py {fix_command(project, task, field, tool)}",
             "revert_command": f"worktree_sync.py {fix_command(project, task, field, human)}"
                               .replace(" --ack-human", "")}
            for field, human, tool, when in rows]


def guard_human_edits(entry, manifest, ack=False, dry_run=False, as_json=False):
    """Refuse to push over a field a human changed on the board.

    Runs before any mutation, and after the pull that push_project does first —
    so a board edit made since the last pull is a merge or a conflict here, never
    a silent revert. With --ack-human the owner has consciously superseded his
    own edit: the stamp is CLEARED, so the field behaves normally again until a
    human next edits it on the board.

    On a conflict this exits EXIT_HITL (3) — never 1. The human-readable block
    always goes to stderr, because a calling agent must relay it verbatim; with
    --json the same information also lands on stdout as structured data.
    """
    blocking, acked = [], False
    for t in manifest.get("tasks", []):
        rows = conflicts(t)
        if not rows:
            continue
        if ack:
            ack_human(t)
            acked = True
        else:
            blocking.append((t, rows))
    if blocking:
        for t, rows in blocking:
            print_conflict(entry["name"], t, rows)
        print(f"\nrefusing to push {entry['name']}: {len(blocking)} task(s) carry a "
              f"human board edit the manifest wants to change.\n"
              f"Ask the owner, then re-run with --ack-human to take his answer "
              f"forward.", file=sys.stderr)
        if as_json:
            emit_json({"command": "push", "project": entry["name"],
                       "dry_run": bool(dry_run), "status": "needs_human",
                       "exit_code": EXIT_HITL,
                       "conflicts": [rec for t, rows in blocking
                                     for rec in conflict_json(entry["name"], t, rows)]})
        sys.exit(EXIT_HITL)
    if acked and not dry_run:
        write_if_changed(projects_dir() / f"{entry['name']}.json", dump(manifest))
    return acked


def push_project(entry, manifest, dry_run=False, ack=False, as_json=False, emit=True,
                 pull=True):
    """Render the manifest onto the GitHub project. Returns the summary dict.

    `as_json` swaps the printed summary for that dict; `emit=False` prints
    nothing at all and leaves the caller to nest the return value (which is what
    `task … --push --json` does, so one command still prints one object).

    **A push PULLS FIRST by default.** Without that, a bare `project push`
    silently reverts a board edit made since the last pull: the guard only
    refuses on an ALREADY-STAMPED field, and a fresh edit has no stamp yet, so
    the push just writes the manifest's value back over it. Pulling first turns
    that fresh edit into either a merge (the board wins, quietly) or an exit 3
    (the manifest wants something else, so the owner decides). `pull=False` is
    for the one caller that has just pulled — `autosync` — so it does not pay
    for two round-trips at session end.
    """
    index = load_index()
    merged = []
    if pull:
        merged = pull_project(entry, manifest, dry_run=dry_run)
        if emit and not as_json:
            for rec in merged:
                print(f"  HUMAN: {pull_line(rec)}")
    guard_human_edits(entry, manifest, ack, dry_run, as_json)
    # NOT named `title`: the task loop below binds that to each board title, and
    # a shared name silently stamped the LAST task's title into index.json's
    # github_project.title (and from there into the dashboard's board link).
    project_title = worktree_name(Path(entry["worktree"]))
    project = ensure_project(project_title, dry_run)
    if not project:
        summary = {"command": "push", "project": entry["name"], "dry_run": True,
                   "status": "would_create_project", "board_url": None,
                   "board_title": project_title, "merged_from_board": merged}
        if emit:
            if as_json:
                emit_json(summary)
            else:
                print(f"[dry-run] would create the '{project_title}' project")
        return summary
    quiet = as_json or not emit
    fields, created = ensure_fields(project["id"], field_spec(manifest), dry_run)
    if created and not quiet:
        print(f"  fields {'to create' if dry_run else 'reconciled'}: {', '.join(created)}")
    views = ensure_views(project["id"], fields, dry_run)
    if views and not quiet:
        print(f"  views {'to create' if dry_run else 'reconciled'}: {', '.join(views)}")

    items, board_order = list_items(project["id"])
    drafts_by_id = {i["content_id"]: i for i in items.values() if i.get("content_id")}
    today = (manifest.get("generated_at") or "")[:10]
    repo_meta = {r["slug"]: r for r in manifest["repos"]}

    kept, updates, clears, drafts = set(), [], [], []
    desired_order = []           # item ids in the order the rows should appear
    added = {"Task": 0, "PR": 0, "Branch": 0}
    skipped = []                 # PRs with no node id — re-run sync
    manifest_dirty = False

    def queue_values(item, values):
        for fname, value in values.items():
            if value and fname in fields and item["values"].get(fname) != value:
                updates.append((item["id"], fields[fname], value))

    def queue_clears(item, values):
        """Only for CLEARABLE task fields: an emptied Group must actually go."""
        for fname in CLEARABLE:
            if (not values.get(fname) and fname in fields
                    and item["values"].get(fname)):
                clears.append((item["id"], fields[fname]))

    # Tasks: matched by draft_id, never by title, so titles stay clean.
    # Row order is group -> dependency topology -> id (see ordered_tasks).
    tasks = manifest.get("tasks", [])
    by_id = {t["id"]: t for t in tasks}
    for t in ordered_tasks(tasks):
        body = render_body(t)
        title = board_title(t)      # decorated for the board; the manifest stays clean
        item = drafts_by_id.get(t.get("draft_id"))
        if not item:
            item = items.get(f'task:{t["id"]}')   # adopt a pre-rename 't1 · …' item
        if not item:
            if dry_run:
                added["Task"] += 1
                continue
            data = gql(f'mutation{{addProjectV2DraftIssue(input:{{'
                       f'projectId:{s(project["id"])},title:{s(title)},'
                       f'body:{s(body)}}})'
                       f'{{projectItem{{id content{{... on DraftIssue{{id}}}}}}}}}}')
            node = data["addProjectV2DraftIssue"]["projectItem"]
            item = {"id": node["id"], "values": {}, "title": title,
                    "body": body, "content_id": node["content"]["id"]}
            added["Task"] += 1
        elif item.get("title") != title or (item.get("body") or "") != body:
            drafts.append((item["content_id"], title, body))
        if t.get("draft_id") != item.get("content_id"):
            t["draft_id"] = item["content_id"]
            manifest_dirty = True
        kept.add(item["id"])
        desired_order.append(item["id"])
        deps_text = deps_label(t, by_id)
        blocked = blocked_state(t, by_id)
        values = {"Kind": "Task", "Status": t["status"], "Last sync": today,
                  "Group": (t.get("group") or "").strip(),
                  "Owner": (t.get("owner") or "").strip(),
                  "Depends on": deps_text,
                  "Blocked": blocked, "Start": t.get("start") or "",
                  "Target": t.get("target") or ""}
        queue_values(item, values)
        queue_clears(item, values)
        snap = task_snapshot(t, deps_text, blocked, body)
        if t.get("last_pushed") != snap and not dry_run:
            t["last_pushed"] = snap
            manifest_dirty = True

    for pr in sorted(manifest["prs"], key=lambda p: (p["repo"], p["number"])):
        org, _, repo_name = pr["repo"].partition("/")
        values = {
            "Kind": "PR", "Status": pr["status"], "PR #": f'#{pr["number"]}',
            "Org": org, "Repo name": repo_name, "Branch": pr["head"],
            "Base": repo_meta.get(pr["repo"], {}).get("base", ""),
            "Review": review_label(pr), "Last sync": today,
        }
        item = items.get(pr["url"])
        if not item:
            if dry_run:
                added["PR"] += 1
                continue
            if not pr.get("node_id"):
                skipped.append(pr["key"])
                if not quiet:
                    print(f"  SKIP {pr['key']} — no node id; re-run sync")
                continue
            data = gql(f'mutation{{addProjectV2ItemById(input:{{'
                       f'projectId:{s(project["id"])},contentId:{s(pr["node_id"])}}})'
                       f'{{item{{id}}}}}}')
            item = {"id": data["addProjectV2ItemById"]["item"]["id"], "values": {}}
            added["PR"] += 1
        kept.add(item["id"])
        desired_order.append(item["id"])
        queue_values(item, values)

    for ref in manifest["branches_no_pr"]:
        slug, _, branch = ref.partition(":")
        org, _, repo_name = slug.partition("/")
        values = {"Kind": "Branch", "Org": org, "Repo name": repo_name,
                  "Branch": branch,
                  "Base": repo_meta.get(slug, {}).get("base", ""), "Last sync": today}
        item = items.get(ref)
        if not item:
            if dry_run:
                added["Branch"] += 1
                continue
            data = gql(f'mutation{{addProjectV2DraftIssue(input:{{'
                       f'projectId:{s(project["id"])},title:{s(ref)}}})'
                       f'{{projectItem{{id}}}}}}')
            item = {"id": data["addProjectV2DraftIssue"]["projectItem"]["id"],
                    "values": {}, "title": ref}
            added["Branch"] += 1
        kept.add(item["id"])
        desired_order.append(item["id"])
        queue_values(item, values)

    apply_drafts(drafts, dry_run)
    if manifest_dirty and not dry_run:
        write_if_changed(projects_dir() / f"{entry['name']}.json", dump(manifest))

    # one project == one worktree, so anything not in the manifest is stale
    stale = [i for i in items.values() if i["id"] not in kept]
    if not dry_run:
        for i in stale:
            gql(f'mutation{{archiveProjectV2Item(input:{{projectId:{s(project["id"])},'
                f'itemId:{s(i["id"])}}}){{item{{id}}}}}}')

    # Row order: tasks, then PRs by (repo, number), then branches. Views have
    # no saved sort (ensure_views kills strays), so the item order IS the row
    # order. Only the suffix after the first out-of-place row is moved.
    known = set(board_order)
    current = ([i for i in board_order if i in kept]
               + [i for i in desired_order if i not in known])
    moved = 0
    if current != desired_order:
        first_bad = next(n for n, (a, b) in enumerate(zip(current, desired_order))
                         if a != b)
        if not dry_run:
            for n in range(first_bad, len(desired_order)):
                after = (f',afterId:{s(desired_order[n - 1])}' if n else "")
                gql(f'mutation{{updateProjectV2ItemPosition(input:{{'
                    f'projectId:{s(project["id"])},itemId:{s(desired_order[n])}'
                    f'{after}}}){{clientMutationId}}}}', allow_error=True)
        moved = len(desired_order) - first_bad

    n_updates = apply_updates(project["id"], updates, dry_run)
    n_clears = apply_clears(project["id"], clears, dry_run)
    summary = {
        "command": "push", "project": entry["name"], "dry_run": bool(dry_run),
        "status": "ok", "board_url": project["url"],
        "board_title": project_title, "board_number": project["number"],
        "fields_reconciled": created, "views_reconciled": views,
        "added_tasks": added["Task"], "added_prs": added["PR"],
        "added_branches": added["Branch"], "draft_edits": len(drafts),
        "values_set": n_updates, "values_cleared": n_clears,
        "rows_reordered": moved, "archived": len(stale),
        "skipped_prs": skipped,
        # what the pull-first step merged back before writing anything
        "merged_from_board": merged,
    }
    if as_json and emit:
        emit_json(summary)
    elif emit:
        prefix = "[dry-run] " if dry_run else ""
        print(f"{prefix}{project['url']}\n"
              f"  +{added['Task']} task(s), +{added['PR']} PR(s), "
              f"+{added['Branch']} branch item(s), "
              f"{len(drafts)} title/body edit(s), "
              f"{n_updates} field value(s) {'to set' if dry_run else 'set'}, "
              f"{n_clears} cleared, "
              f"{moved} row(s) reordered, {len(stale)} archived")

    if not dry_run:
        for e in index["projects"]:
            if e["name"] == entry["name"]:
                e["github_project"] = {"number": project["number"], "id": project["id"],
                                       "title": project_title, "url": project["url"]}
        write_if_changed(projects_dir() / "index.json", dump(index))
    return summary


def find_project(title):
    """The viewer's project with this title, or None — never creates, never
    exits. Used by the pull path so a missing 'project' scope degrades to a
    silent no-op inside sync/autosync instead of failing the whole run."""
    data = gql("query{viewer{projectsV2(first:100){nodes{id number title url}}}}",
               allow_error=True)
    if not data:
        return None
    for node in data["viewer"]["projectsV2"]["nodes"]:
        if node["title"] == title:
            return node
    return None


def pull_project(entry, manifest, dry_run=False):
    """Merge human board edits back into the manifest. The board wins.

    A field is a HUMAN edit exactly when the board no longer holds what the
    last push wrote (task["last_pushed"]). Tool drift — manifest changed, board
    still holds the pushed value — is left alone for the next push to fix.
    Tasks with no last_pushed yet (never pushed, or pushed by an older version)
    are skipped: without a snapshot there is nothing to compare against and
    guessing would manufacture fake "human edits".

    "Depends on" and "Blocked" are NOT pulled — they are renderings the tool
    owns. Dependencies are edited with `task dep`.

    Returns a list of {task, field, board, tool} records — one per merged edit.
    `pull_line` renders one for humans; --json emits them as-is.
    """
    project = find_project(worktree_name(Path(entry["worktree"])))
    if not project:
        return []
    items, _ = list_items(project["id"])
    drafts = {i["content_id"]: i for i in items.values() if i.get("content_id")}
    merged, when = [], now_iso()

    def stamp(task, key, value, was):
        task.setdefault("human_edited", {})[key] = {
            "at": when, "value": value, "was": was}
        merged.append({"task": task["id"], "field": key, "board": value,
                       "tool": was, "at": when})

    for t in manifest.get("tasks", []):
        snap = t.get("last_pushed")
        item = drafts.get(t.get("draft_id"))
        if not snap or not item:
            continue
        for fname, key in sorted(PULL_FIELDS.items()):
            board = item["values"].get(fname) or ""
            if board == (snap.get(key) or ""):
                continue
            if key == "status" and board not in TASK_STATUSES:
                print(f"  ignoring {t['id']}: board Status {board!r} is not a task "
                      f"lane ({'/'.join(TASK_STATUSES)})", file=sys.stderr)
                continue
            if key in ("start", "target") and board and not DATE_RE.match(board):
                print(f"  ignoring {t['id']}: {fname} {board!r} is not YYYY-MM-DD",
                      file=sys.stderr)
                continue
            stamp(t, key, board, snap.get(key) or "")
            if key == "status":
                t["status"] = board
            else:
                t[key] = board
            snap[key] = board
        # Titles are compared and merged with DONE_MARKER stripped off BOTH
        # sides: the board title of a Complete task carries the ✓, the manifest
        # never does. Without the strip the first pull after a completed task is
        # pushed would read its own marker back and stamp a bogus human_edited
        # on every completed task — and a real human retitle would bake the ✓
        # into the manifest. The snapshot keeps the raw board value, since that
        # is what is actually on the board; the next push re-decorates it.
        board_title_now = item.get("title") or ""
        clean_board = strip_done_marker(board_title_now)
        clean_snap = strip_done_marker(snap.get("title"))
        if clean_board != clean_snap:
            stamp(t, "title", clean_board, clean_snap)
            t["title"] = clean_board
            snap["title"] = board_title_now
        board_body = item.get("body") or ""
        if body_hash(board_body) != snap.get("body_hash"):
            own = split_body(board_body)
            stamp(t, "body", own[:60] + ("…" if len(own) > 60 else ""),
                  "<the body the tool pushed>")
            t["body"] = own
            snap["body_hash"] = body_hash(render_body(t))
        prune_task(t)

    if merged and not dry_run:
        write_if_changed(projects_dir() / f"{entry['name']}.json", dump(manifest))
    return merged


def pull_line(rec) -> str:
    """One merged board edit, for humans."""
    return (f"{rec['task']}.{rec['field']}: board {rec['board']!r} "
            f"(tool had {rec['tool']!r})")


def cmd_pull(entry, manifest, dry_run=False, as_json=False):
    merged = pull_project(entry, manifest, dry_run)
    if as_json:
        emit_json({"command": "pull", "project": entry["name"],
                   "dry_run": bool(dry_run), "merged_count": len(merged),
                   "merged": merged})
        if merged and not dry_run:
            render()
        return
    prefix = "[dry-run] " if dry_run else ""
    if not merged:
        print(f"{prefix}{entry['name']}: no human board edits to merge")
        return
    print(f"{prefix}{entry['name']}: {len(merged)} human edit(s) merged — "
          f"the board wins")
    for rec in merged:
        print(f"  {pull_line(rec)}")
    print("  these fields are now stamped human_edited; changing them again "
          "needs --ack-human")
    if not dry_run:
        render()


def resolve_repo(ref):
    """A repo argument may be a path or a bare name found under /workspaces."""
    p = Path(ref).expanduser()
    if p.is_dir() and (p / ".git").exists():
        return p.resolve()
    for cand in [Path("/workspaces") / ref, *Path("/workspaces").glob(f"*/{ref}")]:
        if cand.is_dir() and (cand / ".git").exists():
            return cand.resolve()
    return None


def default_branch(repo: Path) -> str:
    head = sh("git", "-C", str(repo), "symbolic-ref", "--short", "-q",
              "refs/remotes/origin/HEAD")
    if head.startswith("origin/"):
        return head[len("origin/"):]
    for cand in ("main", "master"):
        if not subprocess.run(["git", "-C", str(repo), "rev-parse", "--verify",
                               "--quiet", f"origin/{cand}"],
                              capture_output=True).returncode:
            return cand
    return "main"


def cmd_new(args):
    """Create a tracked worktree in one shot: directory, git worktrees for the
    named repos, index registration, seed manifest, dashboard. No devx work
    items, no /workspaces/.ai/work folders — the manifest IS the metadata.
    """
    if "/" not in args.name:
        sys.exit("name must be <lane>/<slug>, e.g. feat/my-thing")
    lane, _, slug = args.name.partition("/")
    root = Path("/workspaces/.wt") / lane / slug
    index = load_index()
    if find_entry(index, slug):
        sys.exit(f"project {slug!r} is already tracked")
    branch = args.branch or args.name

    repos = []
    for ref in args.repos:
        repo = resolve_repo(ref)
        if not repo:
            sys.exit(f"cannot find repo {ref!r} under /workspaces")
        repos.append(repo)
    if not repos:
        sys.exit("name at least one repo (path or bare name under /workspaces)")

    root.mkdir(parents=True, exist_ok=True)
    seed = []
    for repo in repos:
        dest = root / repo.name
        base = default_branch(repo)
        if dest.exists():
            print(f"  exists  {dest}")
        else:
            subprocess.run(["git", "-C", str(repo), "fetch", "--quiet", "origin", base],
                           capture_output=True)
            has_branch = not subprocess.run(
                ["git", "-C", str(repo), "rev-parse", "--verify", "--quiet", branch],
                capture_output=True).returncode
            cmd = ["git", "-C", str(repo), "worktree", "add", str(dest)]
            cmd += [branch] if has_branch else ["-b", branch, f"origin/{base}"]
            r = subprocess.run(cmd, capture_output=True, text=True)
            if r.returncode:
                sys.exit(f"worktree add failed for {repo.name}:\n{r.stderr.strip()}")
            print(f"  created {dest}  [{branch} from origin/{base}]")
        wt_slug = repo_slug(dest)
        if wt_slug:
            seed.append({"slug": wt_slug, "base": base})

    index["projects"].append({
        "name": slug, "worktree": str(root), "lane": lane,
        "status": "active", "github_project": None,
    })
    write_if_changed(projects_dir() / "index.json", dump(index))

    entry = find_entry(load_index(), slug)
    manifest = build_manifest(entry, root, {"repos": seed}, fetch=False)
    manifest["generated_at"] = (datetime.now(timezone.utc)
                                .replace(microsecond=0).isoformat()
                                .replace("+00:00", "Z"))
    write_if_changed(projects_dir() / f"{slug}.json", dump(manifest))
    render()
    print(f"\ntracked: {slug}  ({len(seed)} repos, branch {branch})")
    print(f"next: worktree_sync.py project push {slug}   # creates the GitHub project")


def entry_for_cwd(cwd=None):
    """The tracked project whose worktree contains cwd, or None.

    This is the gate for all automatic behavior: outside a tracked worktree
    both hook commands must no-op instantly and silently.
    """
    cwd = Path(cwd or os.getcwd()).resolve()
    for e in load_index()["projects"]:
        root = Path(e["worktree"]).resolve()
        if cwd == root or str(cwd).startswith(str(root) + os.sep):
            return e
    return None


PROTOCOL_LINE = (
    "Protocol: this session must keep the project current — create a task "
    "(`task add`) when new work starts, close it (`task set <id> done`) when it "
    "finishes, without asking; autosync pushes everything at session end. "
    "The board is the source of truth for anything a human changed there: "
    "propose, never overwrite.")


def cmd_context(args):
    """Session-start context block. Reads the manifest only — no network."""
    entry = entry_for_cwd(args.cwd)
    if not entry:
        # Not a tracked worktree. Silent for humans (the hook runs everywhere);
        # --json still answers, so an agent can test tracked-ness in one call.
        if args.json:
            emit_json({"tracked": False, "cwd": str(Path(args.cwd or os.getcwd()).resolve())})
        return
    m = read_json(projects_dir() / f"{entry['name']}.json")
    if not m:
        if args.json:
            emit_json({"tracked": True, "synced": False, "project": entry["name"],
                       "worktree": entry.get("worktree", ""),
                       "hint": f"worktree_sync.py sync {entry['name']}"})
            return
        print(f"[worktree-sync] {entry['name']} is tracked but never synced — "
              f"run: worktree_sync.py sync {entry['name']}")
        return
    if args.json:
        st = status_json(entry, m)
        emit_json({"tracked": True, "synced": True, "project": entry["name"],
                   "worktree": st["worktree"], "board_url": st["board_url"],
                   "generated_at": st["synced"], "repos": st["repos"],
                   "pr_status": st["pr_status"], "pr_count": st["pr_count"],
                   "open_tasks": [t for t in st["tasks"] if t["status"] != "Complete"],
                   "task_count": st["task_count"],
                   "human_edited": st["human_edited"],
                   "branches_no_pr": st["branches_no_pr"],
                   "protocol": PROTOCOL_LINE})
        return
    gp = entry.get("github_project") or {}
    counts = {}
    for p in m["prs"]:
        counts[p["status"]] = counts.get(p["status"], 0) + 1
    lines = [
        f"[worktree-sync] Tracked worktree: {entry['name']} "
        f"({len(m['repos'])} repos, last synced {m.get('generated_at', '?')})",
        f"GitHub project: {gp.get('url', 'not created yet')}",
        "PRs: " + (", ".join(f"{v} {k.lower()}" for k, v in sorted(counts.items()))
                   or "none"),
    ]
    all_tasks = m.get("tasks", [])
    by_id = {t["id"]: t for t in all_tasks}
    open_tasks = [t for t in ordered_tasks(all_tasks) if t["status"] != "Complete"]
    if open_tasks:
        lines.append("Open tasks:")
        for t in open_tasks:
            bits = [f"  {t['id']} [{t['status']}]"]
            if t.get("group"):
                bits.append(f"[{t['group']}]")
            if t.get("owner"):
                bits.append(f"[owner: {t['owner']}]")
            bits.append(t["title"])
            if blocked_state(t, by_id) == "Blocked":
                bits.append(f"(BLOCKED by {', '.join(t['depends_on'])})")
            if t.get("body") or t.get("attachments"):
                bits.append(f"(read the task body/{len(t.get('attachments') or [])} "
                            f"attachment(s) on the board before working it)")
            lines.append(" ".join(bits))
    else:
        lines.append("Open tasks: none")
    stamped = [f"{t['id']}.{f}" for t in all_tasks
               for f in sorted(t.get("human_edited") or {})]
    if stamped:
        lines.append("Human-edited on the board (do NOT change without asking): "
                     + ", ".join(stamped))
    if m.get("branches_no_pr"):
        lines.append(f"Branches without a PR: {len(m['branches_no_pr'])}")
    lines.append(PROTOCOL_LINE)
    print("\n".join(lines))


def cmd_autosync(args):
    """Session-end auto-update: sync -> render -> commit -> project push.

    Best-effort by design: a failed step is reported and swallowed (exit 0) so a
    session can always end. The ONE exception is EXIT_HITL — a human board edit
    needs the owner's decision, and losing that behind a 0 would be the tool
    silently dropping the only thing it is not allowed to decide, so 3 is
    re-raised. Both hooks in settings.json end in `|| true`, so this still never
    blocks the session.
    """
    entry = entry_for_cwd(args.cwd)
    if not entry:
        return
    try:
        path = projects_dir() / f"{entry['name']}.json"
        prev = read_json(path, {}) or {}
        root = Path(entry["worktree"]).resolve()
        manifest = build_manifest(entry, root, prev, fetch=False)
        for rec in pull_project(entry, manifest, dry_run=True):
            print(f"[worktree-sync] HUMAN edit merged from the board — "
                  f"{pull_line(rec)}")
        body_changed = {k: v for k, v in prev.items() if k != "generated_at"} != manifest
        manifest["generated_at"] = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat()
            .replace("+00:00", "Z")
            if body_changed or not prev.get("generated_at") else prev["generated_at"])
        write_if_changed(path, dump(manifest))
        render()
        do_commit(f"chore(projects): autosync {entry['name']}")
        # pull=False: the pull above already ran, and session end is the one
        # place where a second round-trip is felt as latency.
        push_project(entry, manifest, dry_run=False, pull=False)
        print(f"[worktree-sync] autosync done for {entry['name']}")
    except SystemExit as e:          # sys.exit from helpers (e.g. missing scope)
        if e.code == EXIT_HITL:
            print("[worktree-sync] autosync stopped before the board push: a human "
                  "edit above needs the owner's decision. Relay the block verbatim "
                  "and re-run `project push <name> --ack-human` only if he says so.",
                  file=sys.stderr)
            sys.exit(EXIT_HITL)
        else:
            print(f"[worktree-sync] autosync partial: {e}", file=sys.stderr)
    except Exception as e:           # noqa: BLE001 — never block session end
        print(f"[worktree-sync] autosync failed: {e}", file=sys.stderr)


def read_body_arg(args):
    """--file PATH | --text "…" | a bare '-' for stdin."""
    if args.file:
        p = Path(args.file).expanduser()
        if not p.is_file():
            sys.exit(f"no such file: {p}")
        return p.read_text().rstrip()
    if args.text is not None:
        return args.text.rstrip()
    return sys.stdin.read().rstrip()


def store_ref(root: Path, ref: str) -> str:
    """URLs verbatim; paths worktree-relative when they live under the worktree,
    absolute otherwise (so a shared asset outside the tree still resolves)."""
    if "://" in ref:
        return ref
    p = Path(ref).expanduser()
    p = p if p.is_absolute() else (Path.cwd() / p)
    try:
        return str(p.resolve().relative_to(root))
    except ValueError:
        return str(p.resolve())


def cmd_task(args):
    """Manage the worktree's Tasks — units of work, often spun up mid-chat."""
    entry = find_entry(load_index(), args.name)
    if not entry:
        sys.exit(f"not a tracked project: {args.name}")
    path = projects_dir() / f"{entry['name']}.json"
    manifest = read_json(path)
    if manifest is None:
        sys.exit(f"no manifest for {entry['name']} — run sync first")
    tasks = manifest.setdefault("tasks", [])
    by_id = {t["id"]: t for t in tasks}
    rest, act = args.rest, args.action
    as_json = getattr(args, "json", False)
    touched = None                      # the task this invocation changed

    def say(text):
        if not as_json:
            print(text)

    def pick(tid):
        if tid not in by_id:
            sys.exit(f"no task {tid} in {entry['name']}")
        return by_id[tid]

    def guarded(task, field, value):
        """A human's board edit is never overwritten without an explicit ack."""
        stamp = (task.get("human_edited") or {}).get(field)
        if not stamp_blocks(stamp, value):
            return
        if not args.ack_human:
            rows = [(field, stamp.get("value"), value, stamp.get("at", "?"))]
            print_conflict(entry["name"], task, rows)
            if as_json:
                emit_json({"command": "task", "action": act, "project": entry["name"],
                           "status": "needs_human", "exit_code": EXIT_HITL,
                           "conflicts": conflict_json(entry["name"], task, rows)})
            sys.exit(EXIT_HITL)
        human = stamp.get("value")
        ack_human(task, [field])          # release, do not whitelist one value
        say(f"  ack: {task['id']}.{field} — overriding the human's "
            f"{human!r} with {value!r}; the guard on this field is released "
            f"until he edits it on the board again")

    def label(task):
        tags = "".join(f" [{task[k]}]" for k in ("group", "owner") if task.get(k))
        return f"[{task['status']}]{tags} {task['title']}"

    if act == "add":
        if not rest:
            sys.exit('usage: task add <project> "Title" [--status wip] '
                     '[--group "…"] [--owner "TechOps (Patricia)"]')
        task = {"id": f"t{max((task_num(t) for t in tasks), default=0) + 1}",
                "title": " ".join(rest),
                "status": TASK_ALIASES.get(args.status.lower(), "New"),
                "created": datetime.now(timezone.utc).date().isoformat()}
        for key, val in (("group", args.group), ("owner", args.owner)):
            if val:
                task[key] = val.strip()
        tasks.append(task)
        touched = task
        say(f"added {task['id']} {label(task)}")

    elif act == "set":
        if len(rest) < 2:
            sys.exit("usage: task set <project> <id> <new|wip|done> [title...]\n"
                     '       task set <project> <id> group "Phase 3 — POA"\n'
                     '       task set <project> <id> owner "TechOps (Patricia)"\n'
                     "       task set <project> <id> dates <start> <target>")
        task, verb = pick(rest[0]), rest[1].lower()
        if verb in ("group", "owner"):
            new = " ".join(rest[2:]).strip()
            guarded(task, verb, new)
            task[verb] = new
        elif verb == "dates":
            set_dates(task, rest[2:], guarded)
        else:
            status = TASK_ALIASES.get(verb)
            if not status:
                sys.exit(f"unknown status {rest[1]!r} (use: "
                         f"{', '.join(sorted(set(TASK_ALIASES)))}, group, owner, dates)")
            guarded(task, "status", status)
            task["status"] = status
            if len(rest) > 2:
                guarded(task, "title", " ".join(rest[2:]))
                task["title"] = " ".join(rest[2:])
        # --group/--owner also work alongside a status change, and "" clears.
        for key, val in (("group", args.group), ("owner", args.owner)):
            if val is not None and verb != key:
                guarded(task, key, val.strip())
                task[key] = val.strip()
        touched = task
        say(f"{task['id']} -> {label(task)}")

    elif act == "dep":
        if len(rest) < 2:
            sys.exit("usage: task dep <project> <id> add|rm|clear [ids...]")
        task, verb, refs = pick(rest[0]), rest[1].lower(), rest[2:]
        deps = list(task.get("depends_on") or [])
        if verb == "add":
            deps += [r for r in refs if r not in deps]
        elif verb in ("rm", "remove"):
            deps = [d for d in deps if d not in refs]
        elif verb == "clear":
            deps = []
        else:
            sys.exit(f"unknown dep verb {rest[1]!r} (add, rm, clear)")
        task["depends_on"] = sorted(set(deps), key=lambda i: int(i[1:] or 0))
        touched = task
        say(f"{task['id']} depends on "
            f"{', '.join(task['depends_on']) or '(nothing)'}")

    elif act == "dates":
        if len(rest) < 2:
            sys.exit("usage: task dates <project> <id> <start> [target]   "
                     "('-' clears one side)")
        touched = pick(rest[0])
        set_dates(touched, rest[1:], guarded)
        say(f"{rest[0]} -> {by_id[rest[0]].get('start', '—')} → "
            f"{by_id[rest[0]].get('target', '—')}")

    elif act == "body":
        if not rest:
            sys.exit("usage: task body <project> <id> --file F | --text '…' | -")
        task = pick(rest[0])
        body = read_body_arg(args)
        guarded(task, "body", body)
        task["body"] = body
        touched = task
        say(f"{task['id']} body set ({len(body.splitlines())} line(s))")

    elif act == "attach":
        if len(rest) < 2:
            sys.exit("usage: task attach <project> <id> <path-or-url> [--note '…']")
        task, ref = pick(rest[0]), " ".join(rest[1:])
        root = Path(entry["worktree"]).resolve()
        stored = store_ref(root, ref)
        kind = args.kind or attachment_kind(stored)
        if kind != "url" and not (root / stored).exists() and not Path(stored).exists():
            print(f"  warning: {stored} does not exist yet (stored anyway)",
                  file=sys.stderr)
        atts = [a for a in (task.get("attachments") or []) if a["path"] != stored]
        atts.append({"kind": kind, "note": args.note or "", "path": stored})
        task["attachments"] = sorted(atts, key=lambda a: a["path"])
        touched = task
        say(f"{task['id']} + {kind} {stored}")

    elif act == "detach":
        if len(rest) < 2:
            sys.exit("usage: task detach <project> <id> <stored-path-or-url>")
        task, ref = pick(rest[0]), " ".join(rest[1:])
        atts = task.get("attachments") or []
        keep = [a for a in atts if a["path"] != ref]
        if len(keep) == len(atts):
            sys.exit(f"{task['id']} has no attachment {ref!r} — "
                     f"have: {', '.join(a['path'] for a in atts) or 'none'}")
        task["attachments"] = keep
        touched = task
        say(f"{task['id']} - {ref}")

    elif act == "schedule":
        schedule_tasks(tasks, args, guarded, quiet=as_json)

    else:   # list
        if as_json:
            emit_json({"command": "task", "action": "list",
                       "project": entry["name"], "task_count": len(tasks),
                       "tasks": [task_json(t, by_id) for t in ordered_tasks(tasks)]})
        else:
            list_tasks(entry, tasks)
        return

    errors = validate_deps(tasks)
    if errors:
        sys.exit("refusing to write — dependency graph is invalid:\n  "
                 + "\n  ".join(errors))
    manifest["tasks"] = sorted((prune_task(t) for t in tasks), key=task_num)
    write_if_changed(path, dump(manifest))
    pushed = None
    if args.push:
        pushed = push_project(entry, manifest, dry_run=False, ack=args.ack_human,
                              as_json=as_json, emit=not as_json)
    elif not as_json:
        print("(run `project push` to reflect this on the board)")
    if as_json:
        by_id = {t["id"]: t for t in manifest["tasks"]}
        emit_json({"command": "task", "action": act, "project": entry["name"],
                   "status": "ok",
                   "task": task_json(touched, by_id) if touched else None,
                   "task_count": len(manifest["tasks"]),
                   "pushed": pushed})


def set_dates(task, values, guarded):
    """<start> [target]; '-' clears that side."""
    for key, raw in zip(("start", "target"), values):
        if raw == "-":
            guarded(task, key, "")
            task[key] = ""
            continue
        if not DATE_RE.match(raw):
            sys.exit(f"{raw!r} is not a YYYY-MM-DD date")
        guarded(task, key, raw)
        task[key] = raw
    if task.get("start") and task.get("target") and task["start"] > task["target"]:
        sys.exit(f"{task['id']}: start {task['start']} is after target {task['target']}")


def schedule_tasks(tasks, args, guarded, quiet=False):
    """Opt-in date fill so the roadmap is not empty on day one.

    Walks tasks in dependency order and gives each one a window of --days
    calendar days (weekends included — this is an ordering aid, not a plan):
    a task with no dependencies starts on --from, a task with dependencies
    starts the day after its latest dependency's Target. Tasks that already
    carry both dates keep them and only contribute their Target, unless
    --overwrite. Nothing is invented unless this command is run.
    """
    if not args.start_from or not DATE_RE.match(args.start_from or ""):
        sys.exit("usage: task schedule <project> --from YYYY-MM-DD "
                 "[--days N] [--overwrite]")
    base = date.fromisoformat(args.start_from)
    span = timedelta(days=max(1, args.days) - 1)
    rank, targets, filled = topo_rank(tasks), {}, 0
    for t in sorted(tasks, key=lambda x: rank.get(x["id"], 0)):
        done = [targets[d] for d in t.get("depends_on") or [] if d in targets]
        start = max(done) + timedelta(days=1) if done else base
        if t.get("start") and t.get("target") and not args.overwrite:
            targets[t["id"]] = date.fromisoformat(t["target"])
            continue
        target = start + span
        guarded(t, "start", start.isoformat())
        guarded(t, "target", target.isoformat())
        t["start"], t["target"] = start.isoformat(), target.isoformat()
        targets[t["id"]] = target
        filled += 1
        if not quiet:
            print(f"  {t['id']:<5} {start} → {target}  {t['title'][:46]}")
    if not quiet:
        print(f"scheduled {filled} task(s) from {base} in {args.days}-day windows")


def list_tasks(entry, tasks):
    """id, status, Group, Owner, then title with deps/blocked/markers.

    Group is the third column (what is this part of) and Owner the fourth (who
    answers for it) — the two accountability columns sit together, ahead of the
    title, so a glance down the list answers "whose phase is stuck".
    """
    if not tasks:
        print(f"no tasks in {entry['name']}")
        return
    by_id = {t["id"]: t for t in tasks}
    width = max([len(t.get("group") or "") for t in tasks] + [5])
    owidth = max([len((t.get("owner") or "").strip()) for t in tasks] + [5])
    for t in ordered_tasks(tasks):
        marks = []
        if t.get("depends_on"):
            marks.append("deps " + ",".join(t["depends_on"]))
        if blocked_state(t, by_id) == "Blocked":
            marks.append("BLOCKED")
        if t.get("start") or t.get("target"):
            marks.append(f"{t.get('start', '?')}→{t.get('target', '?')}")
        if t.get("body"):
            marks.append("body")
        if t.get("attachments"):
            marks.append(f"{len(t['attachments'])} file(s)")
        if t.get("human_edited"):
            marks.append("HUMAN:" + ",".join(sorted(t["human_edited"])))
        tail = f"   [{'; '.join(marks)}]" if marks else ""
        print(f"  {t['id']:<5} {t['status']:<12} "
              f"{(t.get('group') or '—'):<{width}}  "
              f"{((t.get('owner') or '').strip() or '—'):<{owidth}}  "
              f"{t['title']}{tail}")


def cmd_project(args):
    """GitHub Projects v2 sync — gated on the 'project' OAuth scope."""
    probe = subprocess.run(
        ["gh", "api", "graphql", "-f", "query=query{viewer{projectsV2(first:1){nodes{id}}}}"],
        capture_output=True, text=True, env=project_env())
    if probe.returncode or "INSUFFICIENT_SCOPES" in probe.stdout + probe.stderr:
        sys.exit(PROJECT_SCOPE_HINT)
    if not args.name:
        sys.exit(f"usage: worktree_sync.py project {args.action} <name>")
    entry = find_entry(load_index(), args.name)
    if not entry:
        sys.exit(f"not a tracked project: {args.name}")
    manifest = read_json(projects_dir() / f"{entry['name']}.json")
    if not manifest:
        sys.exit(f"no manifest for {entry['name']} — run sync first")
    if args.action == "pull":
        cmd_pull(entry, manifest, args.dry_run, args.json)
    else:
        # Pull-then-push is the default: a bare push that skipped the pull would
        # silently revert a board edit made since the last one. --no-pull is for
        # a caller that has just pulled.
        push_project(entry, manifest, args.dry_run, args.ack_human,
                     as_json=args.json, pull=not args.no_pull)


EXIT_CODE_HELP = """exit codes:
  0  success
  1  error (bad arguments, missing manifest, missing 'project' scope, git failure)
  3  a human edited that field on the GitHub board and the tool refuses to
     overwrite it. NOT a failure and NOT retryable: relay the printed block to
     the owner verbatim and wait. Re-run with --ack-human only if he says so.
"""

MAIN_EPILOG = """\
the everyday calls:
  worktree_sync.py sync <project> --commit          scan + PRs + dashboard + git commit
  worktree_sync.py project push <project>           manifest -> GitHub board
  worktree_sync.py task add <project> "Title" --push
  worktree_sync.py task set <project> t7 done --push
  worktree_sync.py status -v                        what's in flight (no network)

argument order — the one that is easy to get backwards:
  the ACTION comes first, then the PROJECT:
      task set <project> t7 done      CORRECT
      task <project> set t7 done      WRONG
      project push <project>          CORRECT
  <project> is the manifest name in projects/index.json (e.g. sandbox-cicd),
  not the "<lane>/<slug>" board title. `sync` and `scan` also accept a path.

--json is available on scan, sync, status, task, context and project. It prints
exactly one JSON object and no prose, so an agent can branch on the result.

""" + EXIT_CODE_HELP

TASK_EPILOG = """\
ORDER: task <action> <project> [args…]   — action first, project second.

  task add      <project> "Title" [--status new|wip|done] [--group G] [--owner O] [--push]
  task list     <project> [--json]
  task set      <project> <id> <new|wip|done> [new title words…]
  task set      <project> <id> group "Phase 3 — POA"     ("" clears)
  task set      <project> <id> owner "TechOps (Patricia)" ("" clears)
  task set      <project> <id> dates <start> <target>
  task dates    <project> <id> <start> [target]          ('-' clears one side)
  task dep      <project> <id> add|rm|clear [ids…]
  task body     <project> <id> --file F | --text "…" | -     (- reads stdin)
  task attach   <project> <id> <path-or-url> [--note "…"] [--kind K]
  task detach   <project> <id> <stored-path-or-url>
  task schedule <project> --from YYYY-MM-DD [--days N] [--overwrite]

Quote the title: words like --commit inside an unquoted title break argparse.
Add --push to reflect the change on the GitHub board in the same call.

""" + EXIT_CODE_HELP


def main():
    ap = argparse.ArgumentParser(
        prog="worktree_sync.py",
        description="Deterministic tracker for the git worktrees under "
                    "/workspaces/.wt: one JSON manifest per worktree in "
                    "$DOTFILES_DIR/projects/, mirrored to one GitHub Projects v2 "
                    "board. The manifest is the source of truth for what the tool "
                    "knows; the board is the source of truth for anything a human "
                    "changed there.",
        epilog=MAIN_EPILOG,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True, metavar="<command>")

    p = sub.add_parser(
        "scan", help="git-only facts for one worktree, no network",
        description="Print repos/branches/ahead-behind for a worktree directory. "
                    "Reads git only and writes nothing, so it works on an "
                    "untracked worktree too.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="example:\n  worktree_sync.py scan /workspaces/.wt/feat/foo\n")
    p.add_argument("worktree", help="worktree directory (absolute path)")
    p.add_argument("--fetch", action="store_true",
                   help="refresh origin/<base> first, so ahead/behind is current")
    p.add_argument("--json", action="store_true", help="print the repo list as JSON")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser(
        "sync", help="scan + PRs, merge board edits, write the manifest",
        description="Rebuild one worktree's manifest from git + GitHub. Merges any "
                    "human board edit back first (the board wins), then writes "
                    "projects/<project>.json. A run with no underlying change "
                    "rewrites nothing.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  worktree_sync.py sync sandbox-cicd --dry-run\n"
               "  worktree_sync.py sync sandbox-cicd --commit   # the everyday call\n\n"
               + EXIT_CODE_HELP)
    p.add_argument("worktree", metavar="project",
                   help="project name from projects/index.json, or a worktree path")
    p.add_argument("--fetch", action="store_true",
                   help="refresh origin/<base> per repo (slower, accurate ahead/behind)")
    p.add_argument("--dry-run", action="store_true", help="write nothing")
    p.add_argument("--json", action="store_true",
                   help="print the resulting manifest as JSON instead of a summary")
    p.add_argument("--commit", action="store_true",
                   help="also render the dashboard and commit+push projects/")
    p.add_argument("--no-pull", action="store_true",
                   help="skip merging human board edits back first")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser(
        "status", help="read the manifests and print what is in flight (no network)",
        description="Summarise every tracked project, or one named project. Reads "
                    "the manifests only — no git, no network.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="examples:\n"
               "  worktree_sync.py status\n"
               "  worktree_sync.py status sandbox-cicd -v\n"
               "  worktree_sync.py status --json | jq '.projects[].task_open'\n")
    p.add_argument("name", nargs="?", help="one project name (default: all)")
    p.add_argument("-v", "--verbose", action="store_true",
                   help="also list every task and PR (human output only)")
    p.add_argument("--json", action="store_true",
                   help="print {projects:[…]} as JSON; -v does not change the shape")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser(
        "render", help="regenerate projects/README.md",
        description="Rewrite the dashboard from the manifests. Idempotent.")
    p.add_argument("--dry-run", action="store_true", help="report, write nothing")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser(
        "commit", help="commit + push projects/ on the dotfiles' CURRENT branch",
        description="Commit projects/ and push it to whatever branch the dotfiles "
                    "checkout is on — never a hardcoded main. Author and committer "
                    "are forced to Klalter De Abreu Santos <klalter@kyndryl.com>.")
    p.add_argument("-m", "--message", default="chore(projects): sync worktree manifests")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser(
        "project", help="GitHub Projects v2 board: push or pull",
        description="push: pull first (the board wins), then render the manifest "
                    "onto the board (idempotent — it diffs and writes only "
                    "differences). "
                    "pull: merge human board edits back into the manifest; the "
                    "board wins and each merged field is stamped human_edited.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="ORDER: project <push|pull> <project>\n\n"
               "examples:\n"
               "  worktree_sync.py project push sandbox-cicd\n"
               "  worktree_sync.py project push sandbox-cicd --dry-run --json\n"
               "  worktree_sync.py project pull sandbox-cicd\n\n"
               "Needs the 'project' OAuth scope:\n"
               "  env -u GH_TOKEN -u GITHUB_TOKEN gh auth refresh -h github.com "
               "-s project\n\n" + EXIT_CODE_HELP)
    p.add_argument("action", choices=["push", "pull"], help="push or pull")
    p.add_argument("name", nargs="?", metavar="project",
                   help="project name from projects/index.json")
    p.add_argument("--dry-run", action="store_true",
                   help="report what would change; mutate nothing")
    p.add_argument("--json", action="store_true", help="print the summary as JSON")
    p.add_argument("--ack-human", action="store_true",
                   help="push: take the owner's answer forward over a field he "
                        "edited on the board, and release the guard on it. "
                        "Never pass this on your own judgement.")
    p.add_argument("--no-pull", action="store_true",
                   help="push: skip the pull that runs first. Only for a caller "
                        "that has just pulled — a bare push without it can "
                        "revert a fresh board edit.")
    p.set_defaults(func=cmd_project)

    p = sub.add_parser(
        "new", help="create + track a new /workspaces/.wt worktree",
        description="One shot: make /workspaces/.wt/<lane>/<slug>/, add a git "
                    "worktree per repo on branch <lane>/<slug>, register the "
                    "project in index.json, seed the manifest, render the "
                    "dashboard. No devx work items, no /workspaces/.ai/work "
                    "folders — the manifest is the only metadata.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="example:\n"
               "  worktree_sync.py new feat/my-thing bdg-sw-plcy-policy-service "
               "bdg-sw-plcy-policy-helm-charts\n"
               "  worktree_sync.py project push my-thing   # then create the board\n")
    p.add_argument("name", help="<lane>/<slug>, e.g. feat/my-thing")
    p.add_argument("repos", nargs="*", help="repo paths or bare names under /workspaces")
    p.add_argument("--branch", default=None, help="branch name (default: <lane>/<slug>)")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser(
        "context", help="session-start context block (SessionStart hook)",
        description="Print the tracked project's status for the worktree "
                    "containing --cwd. Silent and instant outside a tracked "
                    "worktree. Reads the manifest only — no network.")
    p.add_argument("--cwd", default=None, help="directory to resolve (default: $PWD)")
    p.add_argument("--json", action="store_true",
                   help='print as JSON; outside a tracked worktree emits {"tracked": false}')
    p.set_defaults(func=cmd_context)

    p = sub.add_parser(
        "autosync", help="session-end sync+render+commit+push (SessionEnd hook)",
        description="Best-effort full update for the worktree containing --cwd: "
                    "sync -> dashboard -> dotfiles commit -> board push. Silent "
                    "outside a tracked worktree. Failures are reported and "
                    "swallowed (exit 0); a pending human decision still exits 3.")
    p.add_argument("--cwd", default=None, help="directory to resolve (default: $PWD)")
    p.set_defaults(func=cmd_autosync)

    p = sub.add_parser(
        "task", help="manage a project's Tasks (action FIRST, then project)",
        usage="worktree_sync.py task <action> <project> [args…] [options]",
        description="Tasks are chat-spawned units of work. They live in the "
                    "manifest and appear on the board as draft issues.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=TASK_EPILOG)
    p.add_argument("action", choices=["add", "set", "list", "dep", "dates",
                                      "body", "attach", "detach", "schedule"],
                   help="what to do (comes BEFORE the project name)")
    p.add_argument("name", metavar="project",
                   help="project name from projects/index.json")
    p.add_argument("rest", nargs="*", metavar="args",
                   help='add: "Title"; set: <id> <new|wip|done|group|owner|dates> '
                        "[value…]; dep: <id> add|rm|clear [ids…]; "
                        "dates: <id> <start> [target]; "
                        "body/attach/detach: <id> [ref]; list/schedule: nothing")
    p.add_argument("--status", default="new",
                   help="add: initial status (new|wip|done, default new)")
    p.add_argument("--group", default=None,
                   help='add/set: grouping, e.g. "Phase 2 — KAIF" ("" clears it)')
    p.add_argument("--owner", default=None,
                   help='add/set: who answers for it, e.g. "TechOps (Patricia)" '
                        '("" clears it)')
    p.add_argument("--note", default=None, help="attach: a note for the attachment")
    p.add_argument("--kind", default=None,
                   help="attach: override the inferred kind "
                        "(drawio|pptx|md|image|url|other)")
    p.add_argument("--file", default=None, help="body: read the text from this file")
    p.add_argument("--text", default=None, help="body: the text itself")
    p.add_argument("--from", dest="start_from", default=None,
                   help="schedule: first Start date, YYYY-MM-DD")
    p.add_argument("--days", type=int, default=5,
                   help="schedule: calendar days per task window (default 5)")
    p.add_argument("--overwrite", action="store_true",
                   help="schedule: also redate tasks that already have dates")
    p.add_argument("--ack-human", action="store_true",
                   help="take the owner's answer forward over a field he edited on "
                        "the board, and release the guard on it. Never pass this "
                        "on your own judgement.")
    p.add_argument("--push", action="store_true",
                   help="push the board right after the change")
    p.add_argument("--json", action="store_true",
                   help="print one JSON object instead of prose "
                        "(includes the push summary under 'pushed')")
    p.set_defaults(func=cmd_task)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
