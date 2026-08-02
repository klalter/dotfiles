---
name: "worktree-sync"
description: "Track the git worktrees under /workspaces/.wt in a deterministic, version-controlled manifest — which repos and branches each worktree holds, every PR that came out of it, and the chat-spawned Tasks — mirrored to one GitHub Project per worktree. Use when Klalter says sync the worktrees, update the worktree manifest, refresh projects, what's in flight, which PRs belong to this worktree, track this worktree, add/close a task, group tasks into phases, set task dependencies or dates, attach instructions/decks/draw.ios to a task, look at the roadmap, pull human edits back from the board, create a new worktree (worktree_sync.py new — NOT devx work), or after opening a PR in a tracked worktree. Also use when he asks about the GitHub project board for worktrees or why it is not updating. Inside a tracked worktree the protocol is automatic: hooks load status at session start and autosync at session end; tasks are created/closed without asking."
---

# Worktree sync

One tracked worktree = one JSON manifest in `$DOTFILES_DIR/projects/` + one GitHub
Projects v2 board titled `<lane>/<slug>`. **The manifest is the source of truth for
what the tool knows; the board is the source of truth for anything a human changed
there.** `scripts/worktree_sync.py` is the only way to write either.

```bash
S=$DOTFILES_DIR/skills/worktree-sync/scripts/worktree_sync.py
```

## Do this → run that

| You want to | Command |
|---|---|
| Everyday update after any change | `python3 $S sync <project> --commit` |
| …when ahead/behind must be accurate | `python3 $S sync <project> --fetch --commit` |
| See what's in flight (no network) | `python3 $S status -v` |
| Same, for a script/agent | `python3 $S status --json` |
| Push the manifest to the board | `python3 $S project push <project>` |
| Preview a board push | `python3 $S project push <project> --dry-run` |
| Merge a human's board edits back | `python3 $S project pull <project>` |
| Start tracking a new unit of work | `python3 $S task add <project> "Title" --push` |
| …already in progress | `python3 $S task add <project> "Title" --status wip --push` |
| …in a phase, with an owner | `python3 $S task add <project> "Title" --group "Phase 2 — KAIF" --owner "TechOps (Patricia)" --push` |
| Finish a task | `python3 $S task set <project> t7 done --push` |
| Move a task back | `python3 $S task set <project> t7 wip --push` |
| Rename a task | `python3 $S task set <project> t7 wip New title here --push` |
| List tasks | `python3 $S task list <project>` |
| …for a script/agent | `python3 $S task list <project> --json` |
| Change a task's phase | `python3 $S task set <project> t7 group "Phase 3 — POA" --push` |
| Change a task's owner | `python3 $S task set <project> t7 owner "TechOps (Patricia)" --push` |
| Clear an owner or group | `python3 $S task set <project> t7 owner "" --push` |
| Add dependencies | `python3 $S task dep <project> t9 add t5 t6` |
| Remove / clear dependencies | `python3 $S task dep <project> t9 rm t5` · `python3 $S task dep <project> t9 clear` |
| Set dates | `python3 $S task dates <project> t7 2026-08-10 2026-08-20` |
| Clear one date | `python3 $S task dates <project> t7 - 2026-08-20` |
| Fill the roadmap from scratch | `python3 $S task schedule <project> --from 2026-08-10 --days 5` |
| Write a task's instructions | `python3 $S task body <project> t7 --file notes.md` |
| …inline | `python3 $S task body <project> t7 --text "Do X, then Y"` |
| Attach a file or URL | `python3 $S task attach <project> t7 docs/flow.drawio --note "the target flow"` |
| Remove an attachment | `python3 $S task detach <project> t7 docs/flow.drawio` |
| Create + track a new worktree | `python3 $S new feat/my-thing repo1 repo2` then `python3 $S project push my-thing` |
| Git-only facts, untracked ok | `python3 $S scan /workspaces/.wt/feat/foo` |
| Session-start status block (hook) | `python3 $S context [--cwd DIR] [--json]` |
| Session-end full update (hook) | `python3 $S autosync [--cwd DIR]` |
| Regenerate the dashboard | `python3 $S render` |
| Run the offline tests | `python3 $DOTFILES_DIR/skills/worktree-sync/scripts/test_worktree_sync.py` |

`<project>` is the manifest name in `projects/index.json` (`sandbox-cicd`), not the
`<lane>/<slug>` board title. **The action comes first, the project second:**
`task set <project> t7 done`, `project push <project>`. Never `task <project> set`.

Exit codes: **0** ok · **1** error · **3** a human edited that field on the board —
ask him, do not retry.

`--help` on the script and on every subcommand is self-sufficient; `--json` is
available on `scan`, `sync`, `status`, `task`, `context` and `project` and prints
exactly one JSON object with no prose.

## Rules

1. **The human's board edit wins.** Exit code 3 means the owner has to choose:
   relay the printed block verbatim and stop. Never pass `--ack-human` on your own
   judgement, and never silently revert a lane he moved.
2. **Read a task before working it** — its `body` and *every* attachment.
   `.drawio` through `kyndryl-drawio-deck`, `.pptx` through the pptx skill,
   `.md`/images directly, URLs fetched. A task whose attachments were not read has
   not been started.
3. **Create a task the moment new work starts in a chat; close it the moment it
   finishes. Never ask.** One conversation may spin up several; each distinct
   deliverable gets its own. Show one line in the chat, not the whole table.
4. **Never hand-click "Convert to issue"** on a task item. It breaks `draft_id`,
   the next push duplicates the task and archives the issue you just made.
5. **Never delete, copy or hand-edit `draft_id`.**
6. **Never save a sort on the five tool-maintained views.** A stray sort scrambles
   the maintained row order, and the next push deletes and recreates the view.
   Make a personal view instead.
7. **Group-by and the roadmap's date fields are one-time manual UI steps.** They
   have no API. Set them once; never claim the tool set them.
8. **Do not chase roadmap bar colouring.** Verified impossible — no UI control, no
   API. The `✓ ` on a Complete task exists precisely because of this.
9. **A Complete task is written to the board as `✓ <title>`** — drafts have no
   closed state, so the title is the only completion signal that reaches a roadmap
   bar. It is render-time only: the manifest, `task list`, `--json` and the
   dashboard always hold the clean title. Deleting the ✓ by hand is not an edit;
   the next push restores it.
10. **Never edit dependencies or `Blocked` on the board** — both are renderings the
    tool owns and `pull` does not read them back. Use `task dep`.
11. **`Repo`, `Type` and `Assignee` are reserved field names.** Use `Org` +
    `Repo name`, `Kind`, and `Owner`.
12. **`GH_TOKEN`/`GITHUB_TOKEN` must be stripped for every Projects call**
    (`project_env()`). They outrank `hosts.yml`, so leaving them set makes a
    correctly-scoped token be ignored and the scope gate lie.
13. **`commit` pushes the checked-out branch, never a hardcoded `main`.** Do not
    "simplify" that to `HEAD:main`.
14. **A no-change push must report all zeros.** `+0 task(s) … 0 field value(s) set,
    0 cleared, 0 row(s) reordered, 0 archived`. Anything else on an unchanged
    manifest is a bug — chase it, don't paper over it.
15. **Do not hand-edit inside the `<!-- worktree-sync:attachments -->` block** in a
    draft body; it is regenerated on every push. The prose above it is yours.
16. **Quote task titles.** Words like `--commit` inside an unquoted title break
    argparse.
17. **Seed `base` per repo when tracking a new worktree.** Everything defaults to
    `main`, and a wrong base silently produces a nonsense ahead/behind.
18. **Report a sync with its `NEW:` / `GONE:` / `DIRTY:` lines, not the whole
    table.**
19. **Nothing invents dates.** `start`/`target` only appear if `task dates` or
    `task schedule` was run.
20. **Run the test suite after touching the push/pull layer.**

## Honesty rules

- **If the `project` scope is missing**, `project push` exits non-zero with the
  exact `gh auth refresh` command. Relay it; do not work around it, and **do not
  claim the board was updated.**
- **Never claim a saved view was created.** GitHub saved views have no API. The
  manifest's `view.url` is a link to paste; creating it is a manual UI step owned
  by the `worktree-pr-view` skill.
- **Never claim the roadmap is fully configured.** The tool creates the view and
  its filter; its date fields and group-by are manual. Say exactly that.
- **Never claim GitHub links the dependencies.** `Depends on` and `Blocked` are
  columns this tool renders. Projects v2 has no dependency relation.
- **Never resolve a human's board edit yourself.** Exit 3 → relay and stop.
- **Discovery under-reports** when a worktree's HEAD reflog was pruned. If an
  expected PR is missing, suspect that first and pin the branch in `branches` —
  do not report the PR as gone.

## Automatic protocol (hooks)

`~/.claude/settings.json` wires two hooks, both gated on the session cwd being
inside a worktree registered in `projects/index.json`. Outside one they are silent,
instant no-ops.

- **SessionStart → `context`** injects the project status (open tasks, PR counts,
  board URL). No network.
- **SessionEnd → `autosync`** runs sync → dashboard → dotfiles commit → board push.

After a mid-session milestone (PR opened/merged, task finished) run
`sync <project> --commit` + `project push <project>` right away instead of waiting
for SessionEnd. The behavioural half of this lives in `agent/AGENTS.md`.

## Task fields

Required: `id`, `title`, `status`, `created`. Everything else is optional and
pruned when empty, so an older manifest round-trips byte-for-byte.

| key | what it is |
|---|---|
| `group` | free text, e.g. `Phase 1 — Policy PoC`; becomes a `Group` board option |
| `owner` | free text — who answers for it, e.g. `TechOps (Patricia)` |
| `depends_on` | `["t3","t4"]`; validated acyclic on every write |
| `body` | the instruction text for whoever works the task |
| `attachments` | `[{path, kind, note}]` — read every one before acting |
| `start` / `target` | `YYYY-MM-DD`, what the roadmap plots |
| `draft_id` | the board item's identity — tool-owned, never touch |
| `last_pushed` | exactly what the last push wrote — the human-edit detector |
| `human_edited` | `{field: {at, value, was}}` — a board edit the tool must not undo |

Statuses: `New` → `In progress` → `Complete`. Aliases: `new`/`todo`,
`wip`/`started`/`progress`, `done`/`complete`.

## Hand-editable manifest keys

Merged forward on every sync and never clobbered; everything else is regenerated.

| key | use |
|---|---|
| `base` (per repo) | the branch this repo's PRs target |
| `notes` | free text, rendered above the table in the dashboard |
| `extra_prs` | `owner/repo#n` a teammate opened that belongs to this work |
| `exclude_prs` | drop a false positive |
| `branches` | `{"owner/repo": ["feat/x"]}` — pin branches when the reflog was pruned |
| `since` | force a date floor on the saved-view query |

## The board

| view | layout | filter | lanes |
|---|---|---|---|
| Tasks · Board | Kanban | `kind:Task` | New / In progress / Complete |
| Tasks · List | table | `kind:Task` | — |
| Tasks · Roadmap | roadmap | `kind:Task` | — (date fields + group-by: manual, once) |
| PRs · Board | Kanban | `kind:PR` | Draft / Open / Merged / Cancelled |
| PRs · List | table | `kind:PR` | — |

Item kinds: **Task** (draft issue), **PR** (every PR the worktree produced, with
`PR #`, `Org`, `Repo name`, `Branch`, `Base`, `Review`), **Branch** (a branch with
no PR yet — visibility only, in no view). All lanes are options of the one built-in
`Status` field. Both boards show the other kind's lanes as empty columns; that is
cosmetic and is the price of both boards grouping correctly with zero UI setup.

`project push` is idempotent: it diffs the board against the manifest and writes
only differences. Items whose PR or task left the manifest are archived, not
deleted.

## Tracking an existing worktree

1. Append to `projects/index.json`: `name`, `worktree` (absolute path), `lane`,
   `status: "active"`, `github_project: null`.
2. `python3 $S sync <project> --dry-run` and read the output.
3. Seed `base` per repo in the manifest (rule 17), then re-sync.
4. `python3 $S sync <project> --commit`, then `python3 $S project push <project>`.

For a *new* worktree use `new <lane>/<slug> <repo>…` instead. It makes
`/workspaces/.wt/<lane>/<slug>/`, adds a git worktree per repo on branch
`<lane>/<slug>` cut from that repo's `origin/HEAD` (reused if the branch already
exists), registers the project, seeds the manifest with detected base branches and
renders the dashboard. Repos may be paths or bare names found under `/workspaces`.
Then `project push <slug>` creates the GitHub project.

Do **not** create `/workspaces/.ai/work/` folders, `devx work` items or ADO links
for these; the manifest is the only metadata.

## Reference

- **[`references/internals.md`](references/internals.md)** — why any of this is the
  way it is: the Projects v2 API archaeology, the reserved names, the verified dead
  ends, the rate-limit and determinism reasoning, the `✓` snapshot trap, and the
  bugs already fixed. **Read it before changing the script.**
- `worktree-pr-view` — owns the saved-view query for a single worktree and shares
  the discovery module.
- `daily-report` (project-local) — the dated PR `.pptx`; still keeps its own PR
  JSON.
