---
name: "worktree-pr-view"
description: "Collect every pull request belonging to a git worktree - open, merged and closed - and produce a GitHub saved-view search query for the Pull requests dashboard, named after the worktree. Use when Klalter says save this worktree's PRs to a view, create/update the GitHub view, add this PR to the view, refresh the view, or asks which PRs belong to this worktree. Also use after opening a new PR in a worktree that already has a view, to keep it current."
---

# Worktree PR view

Turns a worktree into a single GitHub **Pull requests → Views** entry holding
every PR that came out of it, whatever its state.

## The one thing to be honest about

GitHub's saved views (the **Views** section in the `github.com/pulls` sidebar)
have **no API**. Verified: no REST endpoint, and the only GraphQL view mutations
are `createProjectV2View`/`updateProjectV2View`, which belong to Projects v2 — a
different feature in a different place.

So this skill automates everything up to the click:

| | |
|---|---|
| discover the worktree's PRs | automated |
| build a query returning exactly those | automated |
| verify the query returns no strays | automated |
| detect newly-opened PRs | automated |
| create / update the view itself | **manual, in the UI** |

Never claim the view was created. Produce the URL and tell him what to click.

## Usage

```bash
python3 ~/.claude/skills/worktree-pr-view/scripts/collect_prs.py <worktree> [--save] [--json]
```

Default path is `.`. `--save` writes/refreshes `<worktree>/.github-view.json`.

## First time — creating the view

1. Run the script against the worktree.
2. Give him the URL and these steps:
   - open it, confirm the PR list looks right
   - **Views → `+`** in the left sidebar of `github.com/pulls`
   - paste the query, name it **the worktree name** (e.g. `feat/sandbox-cicd`)
   - colour **purple**, icon **code-review**
   - Save
3. Run again with `--save` so the state file records what is in the view.

## Updating

Run the script again. It compares against `prs` in the state file and prints a
`NEW:` line for anything that appeared since. If the **query string changed**,
he has to paste the new one into the existing view — editing the saved search is
also UI-only. If only PR *states* changed (open → merged), the query still
matches and nothing needs doing: merged and closed PRs stay in the view because
the query never filters on state.

Re-run with `--save` afterwards.

## `.github-view.json`

Lives in the worktree root. Everything is optional; the defaults are usually right.

```json
{
  "name": "feat/sandbox-cicd",
  "color": "purple",
  "icon": "code-review",
  "extra_prs": ["kyndryl-cto/bdg-eng-tops-techops-bom-input#971"],
  "exclude_prs": [],
  "since": "2026-07-30",
  "branches": { "kyndryl-cto/some-repo": ["feat/x"] }
}
```

- **`extra_prs`** — PRs *someone else* opened that belong to this work. Auto-discovery
  only finds branches checked out in the worktree, so TechOps-authored PRs and the
  like must be pinned here by `owner/repo#number`.
- **`exclude_prs`** — drop a false positive.
- **`since`** — force a date floor. Normally computed.
- **`branches`** — override discovery for a repo when the reflog has been pruned.

## How discovery works, and why

**Branches come from the worktree's own HEAD reflog**, not `git branch`. A git
worktree *shares `refs/heads` with its parent clone*, so listing branches returns
every branch the user has anywhere — on a real worktree that produced 14 PRs when
5 were wanted. The per-worktree reflog records exactly the branches checked out in
that directory.

Consequence to remember: **if the reflog is pruned or the worktree was recreated,
discovery under-reports.** Use `branches` in the state file to pin them.

**One GraphQL search, not one REST search per branch.** The REST search endpoint
allows 30 requests/minute and does not return the head branch, which forced a call
per branch and silently exhausted the quota mid-run — results came back empty with
no error. GraphQL returns `headRefName` and a real `MERGED` state, so a whole
worktree costs one query. Do not "simplify" this back to REST.

`repo:` and `head:` qualifiers are OR'd independently by GitHub search, so the
script re-checks each result's actual (repo, head) pairing locally before keeping
it.

**The query self-verifies.** It first tries without a date floor, runs the search,
and compares the result set to the intended one. Only if they differ does it add
`created:>=<earliest PR>`. This matters because branch names get reused — a
reviewer's `patch-1`/`patch-5` branches collide constantly, and without the floor
the same query returned 46 PRs instead of 7. If strays survive even with the
floor, the script prints a `WARNING` naming them; add them to `exclude_prs` or set
a later `since`.

## Reporting back

Give him: the view name, the PR table grouped by state, anything new since last
run, and the URL. Keep it short — he can see the detail in the terminal. Flag the
`WARNING` line if it appears; do not bury it.
