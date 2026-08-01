#!/usr/bin/env python3
"""Deterministic tracker for the git worktrees under /workspaces/.wt.

Source of truth is a set of JSON manifests in $DOTFILES_DIR/projects/, generated
from git + GitHub facts. A second run with no underlying change rewrites nothing,
so `git status` staying clean *is* the "nothing moved" signal.

    worktree_sync.py scan   <worktree>            # git-only, no network
    worktree_sync.py sync   <worktree|name>       # + PRs, writes the manifest
    worktree_sync.py status [name]                # read manifests, print table
    worktree_sync.py render                       # regenerate projects/README.md
    worktree_sync.py commit                       # commit + push dotfiles main
    worktree_sync.py project push <name>          # GitHub Projects v2 (gated)

`sync --commit` chains sync -> render -> commit, and is the everyday call.

Discovery/search logic is shared with worktree-pr-view via wt_common.py — the
per-worktree HEAD reflog rule and the single-GraphQL-search rule live there and
must not be re-derived here.
"""
import argparse
import json
import os
import subprocess
import sys
import time
import urllib.parse
from datetime import datetime, timezone
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


# ---------------------------------------------------------------- paths / io

def dotfiles_dir() -> Path:
    return Path(os.environ.get("DOTFILES_DIR") or DEFAULT_DOTFILES)


def projects_dir() -> Path:
    return dotfiles_dir() / "projects"


def dump(obj) -> str:
    """Canonical JSON: sorted keys, 2-space indent, trailing newline."""
    return json.dumps(obj, indent=2, sort_keys=True) + "\n"


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


# ---------------------------------------------------------------- commands

def cmd_scan(args):
    root = Path(args.worktree).resolve()
    if not root.is_dir():
        sys.exit(f"not a directory: {root}")
    entry = find_entry(load_index(), root) or {}
    prev = read_json(projects_dir() / f"{entry.get('name', '')}.json", {}) or {}
    repos = scan_repos(root, prev.get("repos"), fetch=args.fetch)
    if args.json:
        print(dump(repos), end="")
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

    # generated_at only moves when something else did, so no-ops stay clean
    body_changed = {k: v for k, v in prev.items() if k != "generated_at"} != manifest
    manifest["generated_at"] = (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if body_changed or not prev.get("generated_at") else prev["generated_at"]
    )

    changed = write_if_changed(path, dump(manifest), args.dry_run)

    if args.json:
        print(dump(manifest), end="")
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
        if m.get("tasks"):
            lines += ["| Task | Status | Title |", "| --- | --- | --- |"]
            lines += [f"| `{t['id']}` | {t['status']} | {t['title']} |"
                      for t in m["tasks"]]
            lines.append("")
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


def cmd_status(args):
    index = load_index()
    entries = [e for e in index["projects"] if not args.name or e["name"] == args.name]
    if not entries:
        sys.exit("no tracked projects" + (f" named {args.name}" if args.name else ""))
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
    """Commit projects/ to dotfiles main with the correct identity, and push.

    The Codespace exports GIT_COMMITTER_* as "GitHub <noreply@github.com>", which
    would otherwise land on every commit, so both author and committer are forced
    on the command itself.
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
    push = subprocess.run(["git", "-C", str(d), "push", "origin", "HEAD:main"],
                          capture_output=True, text=True)
    if push.returncode:
        print(push.stderr.strip(), file=sys.stderr)
        print("\npush failed — klalter_kyndryl cannot push to klalter/dotfiles.\n"
              "See the dotfiles-push-token-override note: reset the scoped\n"
              "http.extraheader with the 'klalter' token, then re-run "
              "`worktree_sync.py commit`.", file=sys.stderr)
        sys.exit(1)
    print("pushed to origin/main")


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
OPTION_COLORS = {"New": "GRAY", "In progress": "YELLOW", "Complete": "GREEN",
                 "Draft": "GRAY", "Open": "BLUE", "Merged": "PURPLE",
                 "Cancelled": "RED", "Task": "PINK", "PR": "BLUE", "Branch": "GRAY"}
TASK_ALIASES = {"new": "New", "todo": "New",
                "wip": "In progress", "started": "In progress",
                "in-progress": "In progress", "progress": "In progress",
                "done": "Complete", "complete": "Complete", "completed": "Complete"}
# The four views, created/repaired on every push. "type:pr" is the BUILT-IN
# content-type qualifier (robust); tasks need the custom Kind field — which is
# named Kind, not Type, precisely so its filter doesn't collide with type:pr.
VIEW_SPEC = [
    ("Tasks · Board", "BOARD_LAYOUT", "kind:Task"),
    ("Tasks · List", "TABLE_LAYOUT", "kind:Task"),
    ("PRs · Board", "BOARD_LAYOUT", "type:pr"),
    ("PRs · List", "TABLE_LAYOUT", "type:pr"),
]


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


def field_spec():
    """The fields one worktree-project needs, with their single-select options.

    "Status" is the BUILT-IN single-select — repurposed as the Task lanes so the
    Tasks board groups correctly with zero UI configuration (a new board view
    always groups by Status). Its stock Todo/In Progress/Done options are
    REPLACED, not extended. "Repo" is rejected as a reserved name (GitHub
    aliases it to the built-in Repository field), hence "Repo slug".
    """
    return [
        ("Kind", "SINGLE_SELECT", KINDS),
        ("Status", "SINGLE_SELECT", TASK_STATUSES),
        ("PR status", "SINGLE_SELECT", PR_STATUSES),
        ("Repo slug", "TEXT", None),
        ("Branch", "TEXT", None),
        ("Base", "TEXT", None),
        ("Review", "TEXT", None),
        ("Last sync", "DATE", None),
    ]


def _options_literal(names):
    return "[" + ",".join(
        f'{{name:{s(n)},color:{OPTION_COLORS.get(n, "GRAY")},description:{s("")}}}'
        for n in names) + "]"


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
            wanted = options if name == "Status" else (
                have + [o for o in options if o not in have])
            if have != wanted:
                if not dry_run:
                    gql(f'mutation{{updateProjectV2Field(input:{{fieldId:{s(cur["id"])},'
                        f'singleSelectOptions:{_options_literal(wanted)}}})'
                        f'{{projectV2Field{{... on ProjectV2FieldCommon{{id}}}}}}}}')
                created.append(f"{name} (options)")
    fields = {f["name"]: f for f in gql(q)["node"]["fields"]["nodes"] if f}
    return fields, created


ITEM_QUERY = """
... on ProjectV2Item {
  id
  content { __typename
    ... on PullRequest { url }
    ... on DraftIssue { id title } }
  fieldValues(first: 30) { nodes {
    ... on ProjectV2ItemFieldTextValue { text field { ... on ProjectV2FieldCommon { name } } }
    ... on ProjectV2ItemFieldDateValue { date field { ... on ProjectV2FieldCommon { name } } }
    ... on ProjectV2ItemFieldSingleSelectValue { name field { ... on ProjectV2FieldCommon { name } } }
  } }
}
"""


def item_key(content):
    """Stable identity for a board item.

    PRs key on URL. Task drafts are titled 't<n> · <title>' and key on the
    t-id alone, so a retitle updates the item instead of duplicating it.
    Branch drafts ('owner/repo:branch') key on their full title.
    """
    if content.get("url"):
        return content["url"]
    title = content.get("title") or ""
    tid = title.split(" · ", 1)[0]
    if tid[:1] == "t" and tid[1:].isdigit():
        return f"task:{tid}"
    return title


def list_items(project_id):
    """{key: item} for the whole board."""
    items, after = {}, None
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
                          "draft": content.get("__typename") == "DraftIssue"}
        if not page["pageInfo"]["hasNextPage"]:
            return items
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


def ensure_views(project_id, dry_run=False):
    """Create/repair the four standard views; drop the stock 'View 1'.

    The one thing the API cannot do: set a board's COLUMN field
    (verticalGroupByFields has no mutation). A new board view groups by the
    built-in Status — which is exactly the Task lanes, so the Tasks board is
    right by construction. The PRs board needs one manual click:
    ⌄ next to the view name → Column field → PR status.
    """
    data = gql(f'query{{node(id:{s(project_id)}){{... on ProjectV2{{'
               f'views(first:20){{nodes{{id name layout filter}}}}}}}}}}')
    existing = {v["name"]: v for v in data["node"]["views"]["nodes"] if v}
    touched = []
    for name, layout, flt in VIEW_SPEC:
        view = existing.get(name)
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
        if view.get("filter") != flt and not dry_run:
            gql(f'mutation{{updateProjectV2View(input:{{viewId:{s(view["id"])},'
                f'filter:{s(flt)}}}){{projectV2View{{id}}}}}}')
            if name not in touched:
                touched.append(f"{name} (filter)")
    stock = existing.get("View 1")
    if stock and len(existing) > 1 or (stock and touched):
        if not dry_run:
            gql(f'mutation{{deleteProjectV2View(input:{{viewId:{s(stock["id"])}}})'
                f'{{projectV2View{{id}}}}}}', allow_error=True)
    return touched


def push_project(entry, manifest, dry_run=False):
    index = load_index()
    title = worktree_name(Path(entry["worktree"]))
    project = ensure_project(title, dry_run)
    if not project:
        print(f"[dry-run] would create the '{title}' project")
        return
    fields, created = ensure_fields(project["id"], field_spec(), dry_run)
    if created:
        print(f"  fields {'to create' if dry_run else 'reconciled'}: {', '.join(created)}")
    views = ensure_views(project["id"], dry_run)
    if views:
        print(f"  views {'to create' if dry_run else 'reconciled'}: {', '.join(views)}")

    items = list_items(project["id"])
    today = (manifest.get("generated_at") or "")[:10]
    repo_meta = {r["slug"]: r for r in manifest["repos"]}

    # key -> (field values, draft title or None)
    wanted, updates, retitles = {}, [], []
    added = {"Task": 0, "PR": 0, "Branch": 0}

    for t in manifest.get("tasks", []):
        wanted[f'task:{t["id"]}'] = ({
            "Kind": "Task", "Status": t["status"], "Last sync": today,
        }, f'{t["id"]} · {t["title"]}')
    for pr in manifest["prs"]:
        wanted[pr["url"]] = ({
            "Kind": "PR", "PR status": pr["status"],
            "Repo slug": pr["repo"], "Branch": pr["head"],
            "Base": repo_meta.get(pr["repo"], {}).get("base", ""),
            "Review": review_label(pr), "Last sync": today,
        }, None)
    for ref in manifest["branches_no_pr"]:
        slug, _, branch = ref.partition(":")
        wanted[ref] = ({
            "Kind": "Branch", "Repo slug": slug, "Branch": branch,
            "Base": repo_meta.get(slug, {}).get("base", ""), "Last sync": today,
        }, ref)

    for key, (values, title_wanted) in wanted.items():
        item = items.get(key)
        if not item:
            kind = values["Kind"]
            if dry_run:
                added[kind] += 1
                continue
            if kind == "PR":
                pr = next(p for p in manifest["prs"] if p["url"] == key)
                if not pr.get("node_id"):
                    print(f"  SKIP {pr['key']} — no node id; re-run sync")
                    continue
                data = gql(f'mutation{{addProjectV2ItemById(input:{{'
                           f'projectId:{s(project["id"])},contentId:{s(pr["node_id"])}}})'
                           f'{{item{{id}}}}}}')
                item = {"id": data["addProjectV2ItemById"]["item"]["id"], "values": {}}
            else:
                data = gql(f'mutation{{addProjectV2DraftIssue(input:{{'
                           f'projectId:{s(project["id"])},title:{s(title_wanted)}}})'
                           f'{{projectItem{{id}}}}}}')
                item = {"id": data["addProjectV2DraftIssue"]["projectItem"]["id"],
                        "values": {}, "title": title_wanted}
            added[kind] += 1
        elif (title_wanted and item.get("content_id")
                and item.get("title") != title_wanted):
            retitles.append((item["content_id"], title_wanted))
        for fname, value in values.items():
            if not value or fname not in fields:
                continue
            if item["values"].get(fname) != value:
                updates.append((item["id"], fields[fname], value))

    if not dry_run:
        for content_id, new_title in retitles:
            gql(f'mutation{{updateProjectV2DraftIssue(input:{{'
                f'draftIssueId:{s(content_id)},title:{s(new_title)}}})'
                f'{{draftIssue{{id}}}}}}')

    # one project == one worktree, so anything not in the manifest is stale
    stale = [i for k, i in items.items() if k not in wanted]
    if not dry_run:
        for i in stale:
            gql(f'mutation{{archiveProjectV2Item(input:{{projectId:{s(project["id"])},'
                f'itemId:{s(i["id"])}}}){{item{{id}}}}}}')

    n_updates = apply_updates(project["id"], updates, dry_run)
    prefix = "[dry-run] " if dry_run else ""
    print(f"{prefix}{project['url']}\n"
          f"  +{added['Task']} task(s), +{added['PR']} PR(s), "
          f"+{added['Branch']} branch item(s), "
          f"{len(retitles)} retitled, "
          f"{n_updates} field value(s) {'to set' if dry_run else 'set'}, "
          f"{len(stale)} archived")

    if not dry_run:
        for e in index["projects"]:
            if e["name"] == entry["name"]:
                e["github_project"] = {"number": project["number"], "id": project["id"],
                                       "title": title, "url": project["url"]}
        write_if_changed(projects_dir() / "index.json", dump(index))


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

    if args.action == "add":
        if not args.title:
            sys.exit("usage: task add <project> <title...>")
        nid = max((int(t["id"][1:]) for t in tasks), default=0) + 1
        task = {"id": f"t{nid}", "title": " ".join(args.title),
                "status": TASK_ALIASES.get(args.status.lower(), "New"),
                "created": datetime.now(timezone.utc).date().isoformat()}
        tasks.append(task)
        print(f"added {task['id']} [{task['status']}] {task['title']}")
    elif args.action == "set":
        if not args.title or len(args.title) < 2:
            sys.exit("usage: task set <project> <id> <new|wip|done> [title...]")
        tid, status = args.title[0], TASK_ALIASES.get(args.title[1].lower())
        task = next((t for t in tasks if t["id"] == tid), None)
        if not task:
            sys.exit(f"no task {tid} in {entry['name']}")
        if status:
            task["status"] = status
        if len(args.title) > 2:
            task["title"] = " ".join(args.title[2:])
        elif not status:
            sys.exit(f"unknown status {args.title[1]!r} "
                     f"(use: {', '.join(sorted(set(TASK_ALIASES)))})")
        print(f"{task['id']} -> [{task['status']}] {task['title']}")
    else:   # list
        if not tasks:
            print(f"no tasks in {entry['name']}")
        for t in tasks:
            print(f"  {t['id']:<5} {t['status']:<12} {t['title']}")
        return

    manifest["tasks"] = sorted(tasks, key=lambda t: int(t["id"][1:]))
    write_if_changed(path, dump(manifest))
    if args.push:
        push_project(entry, manifest, dry_run=False)
    else:
        print("(run `project push` to reflect this on the board)")


def cmd_project(args):
    """GitHub Projects v2 sync — gated on the 'project' OAuth scope."""
    probe = subprocess.run(
        ["gh", "api", "graphql", "-f", "query=query{viewer{projectsV2(first:1){nodes{id}}}}"],
        capture_output=True, text=True, env=project_env())
    if probe.returncode or "INSUFFICIENT_SCOPES" in probe.stdout + probe.stderr:
        sys.exit(PROJECT_SCOPE_HINT)
    if not args.name:
        sys.exit("usage: worktree_sync.py project push <name>")
    entry = find_entry(load_index(), args.name)
    if not entry:
        sys.exit(f"not a tracked project: {args.name}")
    manifest = read_json(projects_dir() / f"{entry['name']}.json")
    if not manifest:
        sys.exit(f"no manifest for {entry['name']} — run sync first")
    push_project(entry, manifest, args.dry_run)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("scan", help="git-only facts, no network")
    p.add_argument("worktree")
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_scan)

    p = sub.add_parser("sync", help="scan + PRs, write the manifest")
    p.add_argument("worktree")
    p.add_argument("--fetch", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--json", action="store_true")
    p.add_argument("--commit", action="store_true")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("status", help="read manifests, print the table")
    p.add_argument("name", nargs="?")
    p.add_argument("-v", "--verbose", action="store_true")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("render", help="regenerate projects/README.md")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("commit", help="commit + push dotfiles main")
    p.add_argument("-m", "--message", default="chore(projects): sync worktree manifests")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_commit)

    p = sub.add_parser("project", help="GitHub Projects v2 (gated)")
    p.add_argument("action", choices=["push"])
    p.add_argument("name", nargs="?")
    p.add_argument("--dry-run", action="store_true")
    p.set_defaults(func=cmd_project)

    p = sub.add_parser("task", help="manage a worktree's Tasks")
    p.add_argument("action", choices=["add", "set", "list"])
    p.add_argument("name", help="tracked project name")
    p.add_argument("title", nargs="*", help="add: title words; set: <id> <status> [title...]")
    p.add_argument("--status", default="new", help="initial status for add")
    p.add_argument("--push", action="store_true", help="push the board after the change")
    p.set_defaults(func=cmd_task)

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
