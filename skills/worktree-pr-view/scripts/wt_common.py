#!/usr/bin/env python3
"""Shared worktree/PR discovery used by collect_prs.py and worktree_sync.py.

Everything here was proven in collect_prs.py first; the comments explain *why*
each rule exists, because every one of them was a bug once. Do not "simplify"
them away.
"""
import json
import subprocess
import sys
from pathlib import Path

# FETCH_HEAD/ORIG_HEAD are pseudo-refs the reflog records like branches; they can
# never be a PR head, so they are dropped alongside the trunks.
TRUNK = {"main", "master", "develop", "development", "HEAD", "FETCH_HEAD", "ORIG_HEAD"}


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


def _slug_from_url(url: str):
    """github.com URL -> owner/repo, or None if it isn't one."""
    if not url or "github.com" not in url:
        return None
    slug = url.rstrip("/").removesuffix(".git").split("github.com")[-1].lstrip(":/")
    return slug if slug.count("/") == 1 else None


def repo_slug(path: Path, _depth=0):
    """owner/repo for a checkout, following local-path origins.

    Some worktrees point origin at another clone on disk (e.g.
    bdg-sw-auto-orch-helm-chart -> /workspaces/orch/...), so the slug has to be
    resolved through that clone's own origin. Bounded to avoid a symlink loop.
    """
    url = sh("git", "-C", str(path), "config", "--get", "remote.origin.url")
    if not url:
        return None
    slug = _slug_from_url(url)
    if slug:
        return slug
    if _depth < 3:
        target = Path(url).expanduser()
        if not target.is_absolute():
            target = (path / target).resolve()
        if target.is_dir():
            return repo_slug(target, _depth + 1)
    return None


def discover(root: Path, overrides=None, strict=True):
    """Return {owner/repo: {branches}} for every git checkout under the worktree.

    strict=True reproduces collect_prs.py exactly: only direct github.com
    origins, and repos with no non-trunk branch are dropped. strict=False also
    resolves local-path origins and keeps repos with an empty branch set, which
    worktree_sync needs in order to report them.
    """
    overrides = overrides or {}
    repos = {}
    for child in sorted(p for p in root.iterdir() if p.is_dir()):
        if not (child / ".git").exists():
            continue
        if strict:
            url = sh("git", "-C", str(child), "config", "--get", "remote.origin.url")
            if not url:
                continue
            slug = _slug_from_url(url)
        else:
            slug = repo_slug(child)
        if not slug:
            continue
        branches = set(overrides.get(slug, [])) or local_branches(child)
        if branches or not strict:
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
    searchable = {r: b for r, b in repos.items() if b}
    heads = sorted({b for brs in searchable.values() for b in brs})
    found = {}
    if searchable:
        q = " ".join(["is:pr"] + [f"repo:{r}" for r in sorted(searchable)]
                     + [f"head:{h}" for h in heads])
        for pr in search(q):
            # repo: and head: are OR'd independently, so confirm the actual pairing
            if pr["head"] in searchable.get(pr["repo"], set()):
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
