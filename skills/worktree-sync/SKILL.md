---
name: "worktree-sync"
description: "Track the git worktrees under /workspaces/.wt in a deterministic, version-controlled manifest — which repos and branches each worktree holds, every PR that came out of it, and the chat-spawned Tasks — mirrored to one GitHub Project per worktree. Use when Klalter says sync the worktrees, update the worktree manifest, refresh projects, what's in flight, which PRs belong to this worktree, track this worktree, add/close a task, create a new worktree (worktree_sync.py new — NOT devx work), or after opening a PR in a tracked worktree. Also use when he asks about the GitHub project board for worktrees or why it is not updating. Inside a tracked worktree the protocol is automatic: hooks load status at session start and autosync at session end; tasks are created/closed without asking."
---

# Worktree sync

One tracked worktree becomes one JSON manifest in `$DOTFILES_DIR/projects/`, plus a
generated `README.md` dashboard and **one GitHub Projects v2 project per worktree,
titled after it** (e.g. `feat/agent-kaif-deploy` →
<https://github.com/users/klalter_kyndryl/projects/3>). The manifest is the source
of truth; the project is a downstream render of it. Project URLs live in
`projects/index.json` under `github_project`.

```bash
S=$DOTFILES_DIR/skills/worktree-sync/scripts/worktree_sync.py

python3 $S sync agent-kaif-deploy --commit         # the everyday call
python3 $S project push agent-kaif-deploy          # render manifest -> GitHub project
python3 $S task add agent-kaif-deploy "Title" [--status wip] [--push]
python3 $S task set agent-kaif-deploy t3 done --push
python3 $S task list agent-kaif-deploy
python3 $S new feat/my-thing repo1 repo2           # create + track a new worktree
python3 $S status -v                               # what's in flight, no network
python3 $S scan /workspaces/.wt/feat/foo           # git-only, untracked ok
python3 $S context [--cwd DIR]                     # session-start block (hook)
python3 $S autosync [--cwd DIR]                    # session-end full update (hook)
```

## Automatic protocol (hooks — no asking, ever)

`~/.claude/settings.json` wires two hooks, both gated on the session cwd being
inside a worktree registered in `projects/index.json` (outside one they are
silent, instant no-ops):

- **SessionStart → `context`**: injects the project status (open tasks, PR
  counts, board URL) into the session context. No network.
- **SessionEnd → `autosync`**: sync → dashboard → dotfiles commit → GitHub
  project push. Best-effort, never blocks the session from ending.

The behavioral half lives in `agent/AGENTS.md` ("Tracked worktrees"): create a
task the moment new work starts in a chat, close it the moment it finishes,
never ask, show a one-line summary; after a mid-session milestone run
`sync --commit` + `project push` immediately instead of waiting for SessionEnd.

## Creating a new tracked worktree

`new <lane>/<slug> <repo>…` does everything in one shot: makes
`/workspaces/.wt/<lane>/<slug>/`, adds a git worktree per repo (branch
`<lane>/<slug>` cut from each repo's `origin/HEAD`, reused if it exists),
registers the project in `index.json`, seeds the manifest with detected base
branches, and re-renders the dashboard. Repos may be paths or bare names found
under `/workspaces`. Then `project push <slug>` creates the GitHub project.

This replaces the old ceremony for these worktrees: do NOT create
`/workspaces/.ai/work/<app>/<lane>/<kind>/<slug>/` folders, `devx work` items,
or ADO links — the manifest is the only metadata.

## Tasks — track chat-spawned work, not just PRs

A Task is a unit of work, usually spun up mid-conversation — one chat can spin up
several. **When Klalter starts a piece of work in a chat (or asks to track
something), add a task; move it as the work moves; push.** Quote the title (words
like `--commit` inside an unquoted title break argparse).

- Lanes: `New` → `In progress` → `Complete` (aliases: `new/todo`,
  `wip/started/progress`, `done/complete`).
- Tasks live in the manifest's `tasks` key (merged forward, never clobbered) and
  appear on the project as draft-issue items titled exactly the task title — no id
  prefix. Identity is the `draft_id` the push records into each task entry, so
  retitles update the same item; never delete or copy `draft_id` by hand.
- `task set <name> <id> <status> [new title...]` also retitles.

## The everyday call

`sync <name> --commit` chains sync → render → commit+push to dotfiles `main`.
Committing straight to `main` here is standing pre-approved for the dotfiles repo
only. Report what changed — the `NEW:` / `GONE:` / `DIRTY:` lines — not the whole table.

Add `--fetch` when ahead/behind matters (it refreshes `origin/<base>` per repo);
skip it for a quick pass, since without it those counts are as stale as the last fetch.

## Tracking a new worktree

1. Append to `projects/index.json`: `name`, `worktree` (absolute path), `lane`,
   `status: "active"`, `github_project: null`.
2. `python3 $S sync <name> --dry-run` and read the output.
3. **Seed the base branches.** Everything defaults to `main`, which is wrong often
   enough to matter — in `agent-kaif-deploy`, `bridge-kaif-reusable-workflows` bases
   on `agentvisortest` and `bdg-sw-auto-orch-helm-chart` on `master`. A wrong base
   silently produces a nonsense ahead/behind (`+78` instead of `0/−1`). Read the
   worktree's own `README.md`/`CLAUDE.md` table, then edit `base` per repo in the
   manifest and re-sync.
4. `python3 $S sync <name> --commit`.

## Hand-editable keys

These are merged forward on every sync and never clobbered — everything else is
regenerated:

| key | use |
|---|---|
| `base` (per repo) | the branch this repo's PRs target |
| `notes` | free text, rendered above the table in the dashboard |
| `extra_prs` | `owner/repo#n` a teammate opened that belongs to this work |
| `exclude_prs` | drop a false positive |
| `branches` | `{"owner/repo": ["feat/x"]}` — pin branches when the reflog was pruned |
| `since` | force a date floor on the saved-view query |

## The GitHub project (`project push`)

One project per worktree, three item kinds, four views — all created and repaired
by the tool on every push:

| view | layout | filter | lanes (on built-in `Status`) |
|---|---|---|---|
| Tasks · Board | Kanban | `kind:Task` | New / In progress / Complete |
| Tasks · List | table | `kind:Task` | — |
| PRs · Board | Kanban | `kind:PR` | Draft / Open / Merged / Cancelled |
| PRs · List | table | `kind:PR` | — |

All four filter on the custom `Kind` field — the built-in `type:pr` qualifier
rendered an **empty** view when tried, so do not go back to it.

**One Status field holds every lane.** The API cannot set a board's column field
(`verticalGroupByFields` has no mutation), and a board view is born grouping by the
built-in `Status` — so task lanes AND PR lanes are all options of that one field,
and **both boards come up grouped correctly with zero UI setup**. The price: each
board shows the other kind's lanes as empty columns (hide them in the UI if they
bother you; cosmetic, optional). There is no separate `PR status` field anymore.

Item kinds: **Task** (draft issue), **PR** (every PR the worktree produced; also
carries `PR #` like `#41`, `Org`, `Repo name`, `Branch`, `Base`, `Review`),
**Branch** (a branch with no PR yet — kept for visibility, shown in no view, no
status). PR rows are ordered tasks-first, then by (repo, number) via
`updateProjectV2ItemPosition` — the views carry **no saved sort**, so item order is
row order.

Idempotent: it diffs the project against the manifest and writes only differences —
a no-change push is `0 added, 0 set, 0 reordered, 0 archived` in ~2s. Items whose
PR/task left the manifest are **archived**, not deleted. Run it after `sync`; it
reads the manifest, never git.

Things that will bite whoever touches this next:

- **Sorting has no mutation either**, but it is readable: a view found carrying a
  saved sort (someone clicked a column header) is **deleted and recreated** on the
  next push, because a stray sort (e.g. by Base) scrambles the maintained row
  order. Don't hand-sort the standard views; make a personal view for that.
- **Reserved field names**: `Repo` (aliases to built-in `Repository`) and `Type`
  (collides with the built-in `type:` filter qualifier) — hence `Org`+`Repo name`
  and `Kind`. `Status` is built-in but *editable*: its stock Todo/In Progress/Done
  options are deliberately replaced.
- **Column order isn't controllable**: GitHub ignores the order of
  `visibleFieldIds` and `Title` is always pinned first — the tool compares column
  *sets*, so dragging columns around in the UI is safe and won't be fought.
- **Secondary rate limits are real**: ~50 item-mutations back-to-back trips one.
  `gql()` paces mutations (~0.8s) and retries rate-limit errors with a 60s+ backoff;
  a killed push is safe to just re-run — it resumes from the diff.
- **`GH_TOKEN`/`GITHUB_TOKEN` outrank `hosts.yml`.** The Codespace exports both, so
  every Projects call goes through `project_env()`, which strips them. Without that,
  a correctly-scoped token is silently ignored and the gate lies.
- **Projects are personal, not org-owned**, on purpose: one project holds
  `kyndryl-cto` *and* `kyndryl-agentic-ai` PRs. A fine-grained PAT cannot manage
  user-owned projects at all (Projects is an org-only permission there), so the
  scope comes from `gh auth refresh -s project`.

## Honesty rules

- **If the `project` scope is missing**, `project push` exits non-zero with the exact
  `gh auth refresh` command. Relay it; do not work around it, and do not claim the
  board was updated.
- **Never claim a saved view was created** — GitHub saved views have no API at all.
  The manifest's `view.url` is a link to paste; creating the view is a manual UI step
  owned by the `worktree-pr-view` skill.
- Discovery **under-reports** when a worktree's HEAD reflog was pruned or the
  worktree was recreated. If a PR he expects is missing, that is the first suspect —
  pin the branch in `branches` rather than assuming the PR is gone.

## How discovery works

Branches come from each checkout's **own HEAD reflog**, not `git branch`: a worktree
shares `refs/heads` with its parent clone, so listing branches returns everything he
has anywhere. PRs come from **one GraphQL search** for the whole worktree — not REST,
which is rate-limited to 30/min and omits the head branch. Both rules live in
`skills/worktree-pr-view/scripts/wt_common.py`, shared with `collect_prs.py`. Do not
re-derive them; change them there and re-verify both tools.

`repo_slug()` follows a **local-path origin** to the canonical clone, because some
worktrees point `origin` at another directory on disk instead of GitHub.

## Determinism

A sync with no underlying change rewrites nothing — `generated_at` only moves when
some other field did, so `git -C $DOTFILES_DIR status --porcelain projects/` staying
empty is the "nothing moved" signal. JSON is written with sorted keys and 2-space
indent so diffs are reviewable.

Commits force author **and** committer to `Klalter De Abreu Santos
<klalter@kyndryl.com>`; the Codespace otherwise stamps `GitHub <noreply@github.com>`.
If the push 403s, `klalter_kyndryl` lacks push on `klalter/dotfiles` — apply the
scoped `http.extraheader` override with the `klalter` token and re-run `commit`.

## Related

- `worktree-pr-view` — owns the saved-view query for a single worktree; reads the
  same discovery module. The manifest's `view` block holds its query and URL.
- `daily-report` (project-local) — builds the dated PR `.pptx`. It still keeps its
  own PR JSON; pointing it at `projects/<name>.json` is an open follow-up.
- `devx` is deliberately **not** involved: the `.wt` slugs are hand-made worktree
  sets devx does not manage, and nothing here reads or writes devx state.

## Hygiene

Before any commit touching a worktree, clear Python bytecode (the KAIF repos
regenerate it on every test run):

```bash
find . -name '__pycache__' -type d -exec rm -rf {} + ; find . -name '*.pyc' -delete
```
