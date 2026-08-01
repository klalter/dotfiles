---
name: "worktree-sync"
description: "Track the git worktrees under /workspaces/.wt in a deterministic, version-controlled manifest — which repos and branches each worktree holds, how far each branch is from its base, and every PR that came out of it. Use when Klalter says sync the worktrees, update the worktree manifest, refresh projects, what's in flight, what am I working on, which repos are in this worktree, which PRs belong to this worktree, track this worktree, add this worktree to the board, or after opening a PR in a tracked worktree. Also use when he asks about the GitHub project board for worktrees or why it is not updating."
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
python3 $S status -v                               # what's in flight, no network
python3 $S scan /workspaces/.wt/feat/foo           # git-only, untracked ok
```

## Tasks — track chat-spawned work, not just PRs

A Task is a unit of work, usually spun up mid-conversation — one chat can spin up
several. **When Klalter starts a piece of work in a chat (or asks to track
something), add a task; move it as the work moves; push.** Quote the title (words
like `--commit` inside an unquoted title break argparse).

- Lanes: `New` → `In progress` → `Complete` (aliases: `new/todo`,
  `wip/started/progress`, `done/complete`).
- Tasks live in the manifest's `tasks` key (merged forward, never clobbered) and
  appear on the project as draft-issue items titled `t<n> · <title>`. Retitles
  update the same item — identity is the `t<n>` prefix, so never strip it by hand.
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

| view | layout | filter | lanes |
|---|---|---|---|
| Tasks · Board | Kanban | `kind:Task` | New / In progress / Complete |
| Tasks · List | table | `kind:Task` | — |
| PRs · Board | Kanban | `type:pr` (built-in) | Draft / Open / Merged / Cancelled |
| PRs · List | table | `type:pr` | — |

Item kinds: **Task** (draft issue, lanes on the built-in `Status` field), **PR**
(every PR the worktree produced; lanes on `PR status`, review state in `Review`),
**Branch** (a branch with no PR yet — kept for visibility, shown in no view, and
NOT given a PR status; that overload was confusing and is gone).

Idempotent: it diffs the project against the manifest and writes only differences —
a no-change push is `0 added, 0 set, 0 archived` in ~2s. Items whose PR/task left
the manifest are **archived**, not deleted. Run it after `sync`; it reads the
manifest, never git.

Things that will bite whoever touches this next:

- **The API cannot set a board's column field** (`verticalGroupByFields` has no
  mutation). A new board groups by the built-in `Status` — which IS the Task lanes,
  so the Tasks board is right by construction. **The PRs board needs one manual
  click, once per project:** open PRs · Board → ⌄ on the view tab → Column field →
  `PR status`. Say so when creating a new project; never claim it's grouped.
- **Reserved field names**: `Repo` (aliases to built-in `Repository`) and `Type`
  (collides with the built-in `type:` filter qualifier) — hence `Repo slug` and
  `Kind`. `Status` is built-in but *editable*: its stock Todo/In Progress/Done
  options are deliberately replaced with the Task lanes.
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
