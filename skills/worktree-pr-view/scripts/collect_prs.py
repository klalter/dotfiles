#!/usr/bin/env python3
"""Collect every PR belonging to a worktree and emit a GitHub saved-view query.

Discovers the repos checked out under a worktree, the branches worked on there,
and the PRs those branches opened — then builds a github.com/pulls search query
that returns exactly that set and nothing else, verifying the result before
printing it.

    collect_prs.py [worktree_path]           # report + query + URL
    collect_prs.py --json                    # machine-readable
    collect_prs.py --save                    # also write .github-view.json

State lives in <worktree>/.github-view.json:

    {
      "name":  "feat/sandbox-cicd",          # view name (defaults to worktree name)
      "color": "purple",
      "icon":  "code-review",
      "extra_prs": ["kyndryl-cto/some-repo#123"],   # PRs others opened
      "exclude_prs": ["kyndryl-cto/other#9"],       # false positives to drop
      "since": "2026-07-30",                 # optional manual date floor
      "branches": {"owner/repo": ["feat/x"]}  # override auto-discovery
    }
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.parse
from pathlib import Path

STATE_FILE = ".github-view.json"
TRUNK = {"main", "master", "develop", "development", "HEAD"}


def sh(*args, check=False):
    r = subprocess.run(args, capture_output=True, text=True)
    if check and r.returncode:
        sys.exit(f"error: {' '.join(args)}\n{r.stderr.strip()}")
    return r.stdout.strip()


def gh_json(*args):
    out = sh("gh", *args)
    try:
        return json.loads(out) if out else None
    except json.JSONDecodeError:
        return None


def worktree_name(root: Path) -> str:
    """/workspaces/.wt/feat/sandbox-cicd -> feat/sandbox-cicd"""
    parts = root.resolve().parts
    if ".wt" in parts:
        return "/".join(parts[parts.index(".wt") + 1:])
    return root.resolve().name


def local_branches(path: Path):
    """Branches checked out in THIS worktree.

    A git worktree shares refs/heads with its parent clone, so listing branches
    would return everything the user has locally. The worktree's own HEAD reflog
    is the only per-worktree signal — it records each branch checked out here.
    """
    names = set()
    cur = sh("git", "-C", str(path), "branch", "--show-current")
    if cur:
        names.add(cur)
    reflog = sh("git", "-C", str(path), "reflog", "show", "HEAD", "--format=%gs")
    for line in reflog.splitlines():
        if "moving from " in line and " to " in line:
            body = line.split("moving from ", 1)[1]
            frm, _, to = body.partition(" to ")
            names.update({frm.strip(), to.strip()})
    return {
        n for n in names
        if n and n not in TRUNK
        and not (len(n) == 40 and all(c in "0123456789abcdef" for c in n))
    }


def discover(root: Path, overrides=None):
    """Return {owner/repo: {branches}} for every git checkout under the worktree."""
    overrides = overrides or {}
    repos = {}
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (child / ".git").exists():
            continue
        url = sh("git", "-C", str(child), "config", "--get", "remote.origin.url")
        if not url:
            continue
        slug = url.rstrip("/").removesuffix(".git").split("github.com")[-1].lstrip(":/")
        if slug.count("/") != 1:
            continue
        branches = set(overrides.get(slug, [])) or local_branches(child)
        if branches:
            repos.setdefault(slug, set()).update(branches)
    return repos


GQL = """
query($q: String!, $after: String) {
  search(type: ISSUE, first: 100, query: $q, after: $after) {
    issueCount
    pageInfo { hasNextPage endCursor }
    nodes { ... on PullRequest {
      number title state url createdAt headRefName
      repository { nameWithOwner } } }
  }
}
"""


def search(query):
    """One GraphQL search, paginated.

    The REST search endpoint allows only 30 requests/minute and does not return
    the head branch, which forced one call per branch and silently exhausted the
    quota. GraphQL returns headRefName and MERGED state, so a whole worktree
    costs a single query.
    """
    out, after = [], None
    while True:
        args = ["api", "graphql", "-f", f"query={GQL}", "-f", f"q={query}"]
        if after:
            args += ["-f", f"after={after}"]
        data = gh_json(*args)
        if not data or "data" not in data:
            err = (data or {}).get("errors", [{}])[0].get("message", "unknown error")
            sys.exit(f"github search failed: {err}")
        res = data["data"]["search"]
        for n in res["nodes"]:
            if not n:
                continue
            repo = n["repository"]["nameWithOwner"]
            out.append({
                "repo": repo,
                "number": n["number"],
                "key": f"{repo}#{n['number']}",
                "title": n["title"],
                "state": n["state"],
                "created": n["createdAt"][:10],
                "head": n["headRefName"],
                "url": n["url"],
            })
        if not res["pageInfo"]["hasNextPage"]:
            return out
        after = res["pageInfo"]["endCursor"]


def find_prs(repos, extra, exclude):
    """Every PR opened from a discovered branch, plus explicitly pinned ones."""
    heads = sorted({b for brs in repos.values() for b in brs})
    q = " ".join(["is:pr"] + [f"repo:{r}" for r in sorted(repos)]
                 + [f"head:{h}" for h in heads])
    found = {}
    for pr in search(q):
        # repo: and head: are OR'd independently, so confirm the actual pairing
        if pr["head"] in repos.get(pr["repo"], set()):
            found[pr["key"]] = pr
    for key in extra:
        slug, _, num = key.partition("#")
        pr = gh_json("pr", "view", num, "--repo", slug,
                     "--json", "number,title,state,createdAt,headRefName,url")
        if pr:
            found[key] = {
                "repo": slug, "number": pr["number"], "key": key,
                "title": pr["title"], "state": pr["state"],
                "created": pr["createdAt"][:10], "head": pr["headRefName"],
                "url": pr["url"],
            }
    for key in exclude:
        found.pop(key, None)
    return found


def build_query(prs, since=None):
    """Query returning exactly `prs`. Adds a date floor when heads collide."""
    repos = sorted({p["repo"] for p in prs.values()})
    heads = sorted({p["head"] for p in prs.values() if p["head"]})
    floor = since or min(p["created"] for p in prs.values())

    def q(with_date):
        parts = ["is:pr"]
        if with_date:
            parts.append(f"created:>={floor}")
        parts += [f"head:{h}" for h in heads]
        parts += [f"repo:{r}" for r in repos]
        return " ".join(parts)

    want = set(prs)
    # prefer the query without a date floor; fall back when branch names collide
    for with_date in (False, True):
        query = q(with_date)
        got = {p["key"] for p in search(query)}
        if got == want:
            return query, sorted(want), []
    query = q(True)
    got = {p["key"] for p in search(query)}
    return query, sorted(want), sorted(got - want)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("path", nargs="?", default=".")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--save", action="store_true")
    args = ap.parse_args()

    root = Path(args.path).resolve()
    if not root.is_dir():
        sys.exit(f"not a directory: {root}")

    state = {}
    sf = root / STATE_FILE
    if sf.exists():
        state = json.loads(sf.read_text())

    repos = discover(root, state.get("branches"))
    if not repos:
        sys.exit(f"no git checkouts with non-trunk branches under {root}")

    prs = find_prs(repos, state.get("extra_prs", []), state.get("exclude_prs", []))
    if not prs:
        sys.exit("no PRs found for this worktree")

    query, included, stray = build_query(prs, state.get("since"))
    url = "https://github.com/pulls?q=" + urllib.parse.quote(query, safe="")

    known = set(state.get("prs", []))
    new = sorted(set(prs) - known) if known else []

    view = {
        "name": state.get("name") or worktree_name(root),
        "color": state.get("color", "purple"),
        "icon": state.get("icon", "code-review"),
        "query": query,
        "url": url,
        "prs": included,
        "extra_prs": state.get("extra_prs", []),
        "exclude_prs": state.get("exclude_prs", []),
        "since": state.get("since"),
    }

    if args.json:
        print(json.dumps({**view, "new_prs": new, "stray": stray,
                          "details": list(prs.values())}, indent=2))
    else:
        print(f"view   : {view['name']}   ({view['color']}, {view['icon']})")
        print(f"repos  : {len(repos)}   PRs: {len(prs)}")
        if new:
            print(f"NEW    : {', '.join(new)}")
        if stray:
            print(f"WARNING: query also returns {len(stray)} unrelated PR(s): "
                  f"{', '.join(stray[:5])}")
            print("         add them to exclude_prs, or set a later \"since\".")
        print()
        for p in sorted(prs.values(), key=lambda x: (x["state"], x["repo"], x["number"])):
            print(f"  {p['state']:<7} {p['key']:<52} {p['title'][:58]}")
        print(f"\nquery:\n{query}\n")
        print(f"url:\n{url}")

    if args.save:
        sf.write_text(json.dumps(view, indent=2) + "\n")
        print(f"\nwrote {sf}", file=sys.stderr)


if __name__ == "__main__":
    main()
