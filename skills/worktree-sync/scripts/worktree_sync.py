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
    number isDraft reviewDecision
    commits(last: 1) { nodes { commit { statusCheckRollup { state } } } }
"""


def enrich(prs):
    """Add review decision, draft flag and check rollup to OPEN PRs.

    Batched by GraphQL alias — one request per 40 PRs — because a `gh pr view`
    per PR burns the search quota on a 17-repo worktree.
    """
    open_prs = [p for p in prs if p["state"] == "OPEN"]
    for i in range(0, len(open_prs), 40):
        chunk = open_prs[i:i + 40]
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
            pr["draft"] = bool(node.get("isDraft"))
            pr["review"] = node.get("reviewDecision") or "REVIEW_REQUIRED"
            commits = (node.get("commits") or {}).get("nodes") or [{}]
            rollup = ((commits[0] or {}).get("commit") or {}).get("statusCheckRollup")
            pr["checks"] = (rollup or {}).get("state") or "NONE"
    for pr in prs:
        pr.setdefault("draft", False)
        pr.setdefault("review", "")
        pr.setdefault("checks", "")
    return prs


def pr_status(pr):
    if pr["state"] == "MERGED":
        return "Merged"
    if pr["state"] == "CLOSED":
        return "Closed"
    if pr.get("draft"):
        return "Draft"
    if pr.get("review") == "CHANGES_REQUESTED":
        return "Changes requested"
    if pr.get("review") == "APPROVED":
        return "Approved"
    return "Open"


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
                  f"synced {m.get('generated_at', '?')}", ""]
        if m.get("notes"):
            lines += [f"> {n}" for n in m["notes"]] + [""]
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
        print(f"{m['name']:<24} {len(m['repos'])} repos   {summary}   "
              f"(synced {m.get('generated_at', '?')})")
        if args.verbose:
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


def cmd_project(args):
    """GitHub Projects v2 sync — gated on an OAuth scope nothing here has yet."""
    probe = subprocess.run(
        ["gh", "api", "graphql", "-f", "query=query{viewer{projectsV2(first:1){nodes{id}}}}"],
        capture_output=True, text=True)
    if probe.returncode or "INSUFFICIENT_SCOPES" in probe.stdout + probe.stderr:
        sys.exit(PROJECT_SCOPE_HINT)
    sys.exit(
        "the 'project' scope is present, but the Projects v2 push is not implemented "
        "yet.\nIt was deliberately left until the scope existed to be tested against — "
        "see the plan's Layer 2."
    )


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

    args = ap.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
