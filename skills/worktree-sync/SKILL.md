---
name: "worktree-sync"
description: "Track the git worktrees under /workspaces/.wt in a deterministic, version-controlled manifest — which repos and branches each worktree holds, every PR that came out of it, and the chat-spawned Tasks — mirrored to one GitHub Project per worktree. Use when Klalter says sync the worktrees, update the worktree manifest, refresh projects, what's in flight, which PRs belong to this worktree, track this worktree, add/close a task, group tasks into phases, set task dependencies or dates, attach instructions/decks/draw.ios to a task, look at the roadmap, pull human edits back from the board, create a new worktree (worktree_sync.py new — NOT devx work), or after opening a PR in a tracked worktree. Also use when he asks about the GitHub project board for worktrees or why it is not updating. Inside a tracked worktree the protocol is automatic: hooks load status at session start and autosync at session end; tasks are created/closed without asking."
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
python3 $S project pull agent-kaif-deploy          # board -> manifest (the human wins)
python3 $S task add agent-kaif-deploy "Title" [--status wip] [--group "Phase 2 — KAIF"] [--owner "TechOps (Patricia)"] [--push]
python3 $S task set agent-kaif-deploy t3 done --push
python3 $S task list agent-kaif-deploy
python3 $S new feat/my-thing repo1 repo2           # create + track a new worktree
python3 $S status -v                               # what's in flight, no network
python3 $S scan /workspaces/.wt/feat/foo           # git-only, untracked ok
python3 $S context [--cwd DIR]                     # session-start block (hook)
python3 $S autosync [--cwd DIR]                    # session-end full update (hook)
```

The full task surface — group, dependencies, dates, instructions, attachments:

```bash
python3 $S task set  <name> t3 group "Phase 3 — POA"    # or --group on add/set
python3 $S task set  <name> t3 owner "TechOps (Patricia)"   # or --owner; "" clears
python3 $S task set  <name> t3 dates 2026-08-10 2026-08-20
python3 $S task dates <name> t3 2026-08-10 2026-08-20   # '-' clears one side
python3 $S task dep  <name> t9 add t5 t6                # rm | clear too
python3 $S task body <name> t3 --file notes.md          # or --text "…" or -
python3 $S task attach <name> t3 docs/flow.drawio --note "the target flow"
python3 $S task attach <name> t3 https://github.com/o/r/pull/1
python3 $S task detach <name> t3 docs/flow.drawio
python3 $S task schedule <name> --from 2026-08-10 --days 5 [--overwrite]
python3 $S task set  <name> t3 wip --ack-human          # override a human's board edit
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

Everything past `id`/`title`/`status`/`created` is **optional and pruned when
empty**, so a manifest written before any of it existed round-trips byte-for-byte:

| key | what it is |
|---|---|
| `group` | free text, e.g. `Phase 1 — Policy PoC`; becomes a `Group` option |
| `owner` | free text — who answers for it, e.g. `TechOps (Patricia)` |
| `depends_on` | `["t3","t4"]`; validated on every write |
| `body` | the instruction text the owner writes for whoever works the task |
| `attachments` | `[{path, kind, note}]` — files/URLs to read before acting |
| `start` / `target` | `YYYY-MM-DD`, what the roadmap plots |
| `last_pushed` | exactly what the last push wrote — the human-edit detector |
| `human_edited` | `{field: {at, value, was}}` — a board edit the tool must not undo |

## Group, dependencies, and the roadmap

**Group** is free text on the task and a `SINGLE_SELECT` on the board. Options are
reconciled from the manifest's distinct values in first-appearance order, and are
only ever extended — a hand-added option survives. `Group` was probed against the
API and is **not** reserved (unlike `Repo` and `Type`); no fallback to `Phase` was
needed. The field only appears once some task has a group: GitHub refuses to create
a single-select with no options ("At least one singleSelectOption is required"),
and inventing a placeholder would be a lie on the board. **Confirmed on the live
boards:** a project whose tasks all have no group gets no `Group` field at all, so
it is missing from GitHub's "Group by" menu entirely. That reads exactly like a
broken push and is not one — set a group on one task and push again.

**Owner** is deliberately plain `TEXT`, not a select: `TechOps (Patricia)` is a
team *and* a person, and a select would force a taxonomy nobody has. `""` clears
it. `Owner` was probed and is free; **`Assignee` is reserved** ("Name cannot have a
reserved value") — do not try to reuse it for this.

**Dependencies** are `depends_on` on the task. Every write validates the whole
graph and refuses on an unknown id, a self-reference or a cycle. **Projects v2 has
no native dependency link** — the `Depends on` column is a rendering (`t5 · Step 2
— chart, t6 · …`) and `Blocked`/`Ready` is derived (blocked = some dependency is
not `Complete`). Both are tool-owned: `project pull` deliberately does **not** read
them back, because parsing that text would fight the renderer. Edit dependencies
with `task dep`, never on the board.

**Row order** is group (first appearance) → dependency topology → id. With no
groups and no dependencies that is exactly id order, so nothing reshuffles.

### What the roadmap view really is

`Tasks · Roadmap` is a genuine `ROADMAP_LAYOUT` view, created by the tool: the enum
value exists, `createProjectV2View` accepts it, and `updateProjectV2View` sets its
`filter` to `kind:Task`. Two things about it have **no mutation at all** and are
one-off UI steps — do not claim otherwise:

- **Which date fields it plots.** `ProjectV2ViewConfigurationInput` carries only
  `visibleFieldIds`; there is no date-field input, and the view's `configuration`
  exposes only `visibleFields` on read, so it cannot even be checked. Open the view
  once and point it at `Start` and `Target`.
- **Group-by.** `groupByFields` is readable, never writable (same as
  `verticalGroupByFields` on boards). Group the roadmap by `Group` once, by hand.

Roadmap views also **reject `visibleFieldIds` outright** — "Roadmap views do not
support visible fields" — which is why its column list in `VIEW_SPEC` is `None`,
meaning "send no configuration". Don't add one back.

`task schedule --from 2026-08-10 [--days 5]` is the **opt-in** date fill so the
roadmap is not empty on day one. It walks tasks in dependency order and gives each
a window of `--days` calendar days (weekends included — it is an ordering aid, not
a plan): a task with no dependencies starts on `--from`, a task with dependencies
starts the day after its latest dependency's `Target`. Tasks that already carry
both dates keep them unless `--overwrite`. Nothing fabricates dates unless this
command is run.

## Instructions and attachments

A task can carry a `body` the owner writes and `attachments` he drops in. Both are
pushed into the draft issue so they are visible on the item:

```
<the owner's prose>

<!-- worktree-sync:attachments -->
### Attachments
_Read every attachment below before working this task…_
- **drawio** `docs/flow.drawio` — the target flow
- **url** <https://github.com/o/r/pull/1>
<!-- /worktree-sync:attachments -->
```

Everything from the marker on is regenerated on every push, which is what makes a
board edit of the prose half recoverable: `pull` keeps the text before the marker
and drops the rest. **Do not hand-edit inside the marked block** — it is overwritten.

Paths are stored worktree-relative when the file lives under the worktree and
absolute otherwise; URLs are stored verbatim. `kind` is inferred from the suffix
(`drawio`, `pptx`, `md`, `image`, `url`, `other`) and can be forced with `--kind`.

**Contract for whoever works the task** — the agent picking it up must read `body`
and *every* attachment before acting: `.drawio` through the `kyndryl-drawio-deck`
skill, `.pptx` through the pptx skill, `.md`/images directly, URLs fetched. A task
whose attachments were not read has not been started.

## The board is the source of truth for human edits

The manifest is the source of truth for what the *tool* knows; the board is the
source of truth for anything a *human* changed there. The bridge is a per-task
`last_pushed` snapshot of exactly what the last push wrote.

- `project pull <name>` reads the board. Board value **==** `last_pushed` → nobody
  touched it, the manifest wins as before. Board value **!=** `last_pushed` → a
  human moved it, so **the board wins**: the value is merged into the manifest and
  stamped `human_edited: {field: {at, value, was}}`.
- Pulled fields are `Status`, `Group`, `Owner`, `Start`, `Target`, the title, and
  the prose half of the body. A task with no `last_pushed` yet is skipped — without a
  snapshot there is nothing to compare, and guessing would manufacture fake human
  edits. A Task dragged into a PR lane (`Merged`, …) is ignored with a warning.
- `sync` and `autosync` run this reconciliation **before** pushing, so a session
  can never silently overwrite a board edit. `sync --no-pull` skips it; a missing
  project or missing `project` scope degrades to a quiet no-op.
- `task set` and `project push` then **refuse** to change a stamped field: they
  print the field, what the human set and when, what the tool wants, and the
  options — and exit **3** (`EXIT_HITL`), which is deliberately distinct from 1 so
  a calling agent can tell "needs a human decision" from a real failure.
- `--ack-human` on `task set`/`project push` takes the owner's answer forward: it
  records the approved value on the stamp, so the guard stays quiet until a human
  touches that field again.

**The agent's job is to propose, not to decide.** When validating that a task was
really implemented, update the manifest and push — but if the tool exits 3, relay
the block verbatim (current status, what the human set and when, what you believe
it should be, and the keep / move-forward / move-back options) and wait. Never
re-run with `--ack-human` on your own judgement, and never silently revert a lane
the owner moved.

## The everyday call

`sync <name> --commit` chains sync → render → commit+push to **whatever branch the
dotfiles checkout is on** — normally `main`, where committing straight is standing
pre-approved for this repo only. It is deliberately *not* `HEAD:main`: while a
tooling branch is checked out here, a hardcoded target would push that branch's
commits to `main` and merge something nobody approved. Report what changed — the
`NEW:` / `GONE:` / `DIRTY:` lines — not the whole table.

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

One project per worktree, three item kinds, five views — all created and repaired
by the tool on every push:

| view | layout | filter | lanes (on built-in `Status`) |
|---|---|---|---|
| Tasks · Board | Kanban | `kind:Task` | New / In progress / Complete |
| Tasks · List | table | `kind:Task` | — |
| Tasks · Roadmap | roadmap | `kind:Task` | — (date fields + group-by: UI, see above) |
| PRs · Board | Kanban | `kind:PR` | Draft / Open / Merged / Cancelled |
| PRs · List | table | `kind:PR` | — |

All five filter on the custom `Kind` field — the built-in `type:pr` qualifier
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
a no-change push is `+0 task(s) … 0 field value(s) set, 0 cleared, 0 row(s)
reordered, 0 archived` in ~2s. Items whose PR/task left the manifest are
**archived**, not deleted. Run it after `sync`; it reads the manifest, never git.

Things that will bite whoever touches this next:

- **Sorting has no mutation either**, but it is readable: a view found carrying a
  saved sort (someone clicked a column header) is **deleted and recreated** on the
  next push, because a stray sort (e.g. by Base) scrambles the maintained row
  order. Don't hand-sort the standard views; make a personal view for that.
- **Reserved field names**: `Repo` (aliases to built-in `Repository`) and `Type`
  (collides with the built-in `type:` filter qualifier) — hence `Org`+`Repo name`
  and `Kind`. `Status` is built-in but *editable*: its stock Todo/In Progress/Done
  options are deliberately replaced. `Group`, `Owner`, `Blocked`, `Depends on`,
  `Start` and `Target` were all probed and are free; `Assignee` is **not** (it
  raises "Name cannot have a reserved value"), so Owner is `Owner`.
- **Single-select options must be re-sent with their ids.**
  `ProjectV2SingleSelectFieldOptionInput` takes an optional `id`; without it an
  option update *recreates* the options and drops every value already assigned to
  them. `_options_literal` passes the ids it knows — do not drop that.
- **Empty values need `clearProjectV2ItemFieldValue`.** `queue_values` only ever
  sets, so a Group or date the owner removed would linger on the board forever.
  `CLEARABLE` lists the task fields that get actively blanked.
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
- **Never claim the roadmap is fully configured.** The tool creates the roadmap
  view and its filter; the date fields it plots and its group-by have no mutation
  and must be set once in the UI. Say exactly that, and never that the tool set them.
- **Never claim GitHub links the dependencies.** `Depends on` and `Blocked` are
  columns this tool renders. Projects v2 has no dependency relation.
- **Never resolve a human's board edit yourself.** Exit code 3 means the owner has
  to choose; relay the printed block and stop.
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

Every optional task key is **dropped when empty**, and the dashboard's extra task
columns (`Depends on`, `Dates`, `Notes`) and its per-group headings only appear
when some task actually uses them — a project that uses none of the new features
renders and pushes exactly as it did before, so the signal stays honest. The one
expected one-off: the first push after this schema lands adds the new fields and
the roadmap view to the project, and stamps `last_pushed` into every task. That
baseline is what makes human-edit detection possible; edits made *before* it
cannot be detected.

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
