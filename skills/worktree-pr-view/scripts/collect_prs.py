#!/usr/bin/env python3
"""Collect every PR belonging to a worktree and emit a GitHub saved-view query.

Discovers the repos checked out under a worktree, the branches worked on there,
and the PRs those branches opened — then builds a github.com/pulls search query
that returns exactly that set and nothing else, verifying the result before
printing it.

    collect_prs.py [worktree_path]           # report + query + URL
    collect_prs.py --json                    # machine-readable
    collect_prs.py --save                    # also write .github-view.json

Discovery and search live in wt_common.py, shared with worktree_sync.py.

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
import sys
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from wt_common import build_query, discover, find_prs, worktree_name  # noqa: E402

STATE_FILE = ".github-view.json"


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
