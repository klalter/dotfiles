# worktree-sync internals

Why the tool is shaped the way it is. **Everything here was paid for by hitting
it.** `SKILL.md` tells you what to run; this file tells you what happens if you
try something else, so nobody re-derives a wall by walking into it again.

Read this before changing `scripts/worktree_sync.py`. Nothing here is aspirational
— every claim about the GitHub API was verified against a live project.

---

## 1. The model

One tracked worktree → one JSON manifest in `$DOTFILES_DIR/projects/` → one
GitHub Projects v2 project titled `<lane>/<slug>`, plus a generated
`projects/README.md` dashboard.

- **The manifest is the source of truth for what the tool knows.** The project is
  a downstream render of it.
- **The board is the source of truth for anything a human changed there.** The
  bridge between the two is the per-task `last_pushed` snapshot (§9).
- Project URLs live in `projects/index.json` under `github_project`.

**Projects are personal (`viewer`), not org-owned — on purpose.** One project
holds `kyndryl-cto` *and* `kyndryl-agentic-ai` PRs, which an org project cannot.
The cost: a fine-grained PAT cannot manage user-owned projects at all (Projects is
an org-only permission on fine-grained tokens), so the scope has to come from
`gh auth refresh -s project`.

**`devx` is deliberately not involved.** The `.wt` slugs are hand-made worktree
sets devx does not manage; nothing here reads or writes devx state, and no
`/workspaces/.ai/work/` folders or work items are created for them. The
manifest is the only metadata. This stopped being a choice and became the only
option when the entire `devx work` tree (work items, `worktree-config.yaml`
reconciliation, the ADO bridge, the `/api/work/*` routes and the Work UI) was
deleted from dev-shell.

---

## 2. Item kinds and item identity

Three kinds share one project:

| kind | item type | shown in |
|---|---|---|
| `Task` | draft issue | Tasks · Board / List / Roadmap |
| `PR` | the real PullRequest node | PRs · Board / List |
| `Branch` | draft issue titled `owner/repo:branch` | no view (visibility only) |

Identity rules (`item_key`, `list_items`):

- **PRs key on their URL.**
- **Branch drafts key on their `owner/repo:branch` title.**
- **Task drafts are NOT keyed by title.** The push records the `DraftIssue` node
  id into the task as `draft_id`, and matches on that. This is what lets titles
  stay clean (no `t1 · ` prefix) and lets a retitle update the same item instead
  of creating a second one. The `t<n> · ` pattern is still *recognised* purely to
  adopt items created before that change; do not reintroduce it.
- **Never delete or hand-copy `draft_id`.**

### Never hand-click "Convert to issue"

Conversion swaps the item's content for an `Issue` node with a **different node
id**. The `draft_id` in the manifest stops resolving, so the next push finds no
item for that task, **creates a duplicate draft**, and — because the converted
item is no longer represented in the manifest — **archives the issue it just
made**. There is no recovery path that starts with a hand-click.

**What real issues would take** (out of scope for now, but this is the design if
it is ever wanted): the tool would have to do the conversion itself — `createIssue`
in a chosen home repo, `addProjectV2ItemById`, then store the issue node id
alongside `draft_id` in the task and prefer it when matching. It must be a
*migration* (adopt the existing item, drop the draft) and not a duplication. It
also needs a home repo to put the issues in, which is the reason drafts were
chosen: the board is private and there is no natural repo for cross-repo work.

---

## 3. One Status field holds every lane

A board view is *born* grouping by the built-in `Status` field, and
**`verticalGroupByFields` has no mutation** — the API cannot set a board's column
field. So task lanes and PR lanes are all options of that one `Status` field:

```
New · In progress · Complete · Draft · Open · Merged · Cancelled
```

That is the only arrangement in which **both boards come up grouped correctly
with zero UI setup**. The price is that each board shows the other kind's lanes as
empty columns — cosmetic, hideable in the UI, not worth trading the zero-setup
property for. There is no separate `PR status` field any more (it is in
`LEGACY_FIELDS` and deleted on sight).

`Status` is built-in but **editable**: its stock Todo/In Progress/Done options are
deliberately *replaced*, not extended. Every other single-select is extended and
never shrunk, so a hand-added option survives.

---

## 4. Views: what has an API and what does not

Five views, created and repaired on every push:

| view | layout | filter |
|---|---|---|
| Tasks · Board | `BOARD_LAYOUT` | `kind:Task` |
| Tasks · List | `TABLE_LAYOUT` | `kind:Task` |
| Tasks · Roadmap | `ROADMAP_LAYOUT` | `kind:Task` |
| PRs · Board | `BOARD_LAYOUT` | `kind:PR` |
| PRs · List | `TABLE_LAYOUT` | `kind:PR` |

- **All five filter on the custom `Kind` field.** The built-in `type:pr` qualifier
  was tried and rendered an **empty** view. Do not go back to it. (`Kind` is named
  `Kind` and not `Type` precisely so its filter cannot collide with the built-in
  `type:` qualifier — see §5.)
- **Column order is not controllable.** GitHub ignores the order of
  `visibleFieldIds` and always pins `Title` first. The tool therefore compares
  column *sets*, not sequences — an ordered diff would re-send the configuration
  on every push, forever. Dragging columns around in the UI is safe.
- **Sorting has no mutation, but a saved sort IS readable.** A view found carrying
  one (`sortByFields`) is **deleted and recreated** on the next push, because a
  stray sort (say, by `Base`) scrambles the row order the item-position pass
  maintains. Don't hand-sort the five standard views; make a personal view instead.
- **GitHub *saved views* (the PR-dashboard search kind) have no API at all.** The
  manifest's `view.url` is only a link to paste; creating that view is a manual UI
  step owned by the `worktree-pr-view` skill. Never claim the tool created one.
- The stock `View 1` is deleted once the real views exist.

### The roadmap, precisely

`Tasks · Roadmap` is a genuine `ROADMAP_LAYOUT` view: the enum value exists,
`createProjectV2View` accepts it, and `updateProjectV2View` sets its `filter`.
Three things about it have **no mutation at all**:

1. **Which date fields it plots.** `ProjectV2ViewConfigurationInput` carries only
   `visibleFieldIds` — there is no date-field input — and the view's
   `configuration` exposes only `visibleFields` on read, so it cannot even be
   checked. Open the view once and point it at `Start` and `Target`.
2. **Group-by.** `groupByFields` is readable, never writable (same story as
   `verticalGroupByFields` on boards). Group the roadmap by `Group` once, by hand.
3. **Bar colour by status — verified impossible, do not chase it.** The `Group`
   options already carry colours (BLUE/GREEN/ORANGE/PURPLE via `GROUP_PALETTE`)
   and `Complete` is GREEN in `OPTION_COLORS`, yet roadmap bars still render
   neutral. There is no "colour by" control in the roadmap UI and no field for it
   in the API. Any code added to chase this is dead code. The completion signal
   that *does* reach a bar is the `✓ ` title marker (§9) — that is exactly why it
   exists.

Roadmap views additionally **reject `visibleFieldIds` outright** — *"Roadmap views
do not support visible fields"* — which is why the roadmap's column list in
`VIEW_SPEC` is `None`, meaning "send no configuration". Don't add one back.

---

## 5. Field names: reserved, probed, and free

Every name below was probed against the live API.

| name | verdict |
|---|---|
| `Repo` | **reserved** — GitHub aliases it to the built-in `Repository` field. Hence `Org` + `Repo name`. |
| `Type` | **reserved in effect** — collides with the built-in `type:` filter qualifier. Hence `Kind`. |
| `Assignee` | **reserved** — *"Name cannot have a reserved value"*. This is why the owner field is `Owner`. |
| `Status` | built-in, but **editable**; options replaced (§3). |
| `Group`, `Owner`, `Blocked`, `Depends on`, `Start`, `Target`, `PR #`, `Branch`, `Base`, `Review`, `Last sync` | probed, all **free**. |

`Group` being free is worth stating explicitly: it was probed *because* `Repo` and
`Type` had already bitten, and no fallback to `Phase` turned out to be needed.

**Owner is deliberately plain `TEXT`, not a select.** `TechOps (Patricia)` is a
team *and* a person; a select would force a taxonomy nobody has. `""` clears it.

### The `Group` field does not exist until some task has a group

GitHub refuses to create a single-select with no options — *"At least one
singleSelectOption is required for data_type SINGLE_SELECT"* — and inventing a
placeholder option would be a lie on the board. So `field_spec()` only includes
`Group` once some task carries one.

**Confirmed on the live boards:** a project whose tasks all have no group gets no
`Group` field at all, so it is missing from GitHub's "Group by" menu entirely.
That reads exactly like a broken push and is not one. Set a group on one task and
push again.

Group option colours cycle by position (`GROUP_PALETTE`) because groups are free
text; the fixed lanes get fixed colours (`OPTION_COLORS`).

---

## 6. Writing field values

- **Single-select options must be re-sent with their ids.**
  `ProjectV2SingleSelectFieldOptionInput` takes an *optional* `id`; without it an
  option update **recreates** the options and drops every value already assigned
  to them. `_options_literal` passes the ids it knows — do not drop that.
- **Empty values need `clearProjectV2ItemFieldValue`.** `queue_values` only ever
  *sets* (it skips falsy values), so a `Group` or a date the owner removed would
  linger on the board forever. `CLEARABLE` lists the task fields that get actively
  blanked: `Group`, `Owner`, `Depends on`, `Blocked`, `Start`, `Target`.
- Writes are batched by GraphQL alias: ~20 `updateProjectV2ItemFieldValue` per
  request, ~20 clears, ~10 `updateProjectV2DraftIssue` (title/body).

---

## 7. Row order

Order is **group (first appearance) → dependency topology → id**
(`ordered_tasks`), then PRs by `(repo, number)`, then branch items. With no groups
and no dependencies that is exactly id order, so nothing reshuffles on a project
that uses neither.

It is applied with `updateProjectV2ItemPosition`, and only the **suffix after the
first out-of-place row** is moved — moving every row on every push would burn the
mutation budget for nothing. This only works because the views carry no saved sort
(§4): item order *is* row order.

---

## 8. Dependencies are a rendering, not a relation

**Projects v2 has no native dependency link.** `depends_on` lives on the task in
the manifest; `Depends on` on the board is a rendered text column
(`t5 · Step 2 — chart, t6 · …`) and `Blocked`/`Ready` is derived from it.

Both columns are tool-owned, and `project pull` deliberately does **not** read them
back — parsing that text would fight the renderer. Edit dependencies with
`task dep`, never on the board. Never tell anyone GitHub links them.

Every write validates the whole graph (`validate_deps`) and refuses on an unknown
id, a self-reference, or a cycle (Kahn's algorithm: whatever cannot be peeled off
is in or behind a cycle). `topo_rank` falls back to id order inside a cycle rather
than raising — validation is the gate, ordering is not.

**`Blocked` is blank on a Complete task.** Blocked/Ready describes work still to
do; "Ready" on something already finished is noise. Because `Blocked` is in
`CLEARABLE`, completing a task actively clears the field on the board rather than
leaving a stale value.

### Filling the roadmap: `task schedule`

`task schedule <project> --from YYYY-MM-DD [--days N] [--overwrite]` is the
**opt-in** date fill, so the roadmap is not empty on day one. **Nothing fabricates
dates unless this command is run.**

It walks tasks in dependency order and gives each a window of `--days` calendar
days — **weekends included; it is an ordering aid, not a plan**. A task with no
dependencies starts on `--from`; a task with dependencies starts the day after its
latest dependency's `Target`. A task that already carries **both** dates keeps them
and only contributes its `Target` to the chain, unless `--overwrite`.

`set_dates` refuses a start later than its target, and `-` clears one side.

---

## 9. The `✓ ` completion marker

A task item is a **draft issue, and a draft issue has no open/closed state.** Its
dashed-circle icon is byte-identical whether the task is `New` or `Complete` — on
the board, and (the part that actually hurts) inside a roadmap bar, where the
`Status` column is not shown at all and bar colour cannot be driven from status
(§4.3). Drafts are kept on purpose (§2). So **the title text is the only completion
signal that reaches a roadmap bar**, and a `Complete` task is *written* to the
board as `✓ <title>`.

It is a **render-time decoration, never data**:

- `board_title()` adds it on push; `strip_done_marker()` removes it on pull.
  `DONE_MARKER = "✓ "` at the top of the script switches it (`""` disables it
  entirely, and the tests cover that).
- `board_title()` is idempotent: an already-marked title is left alone, so a marker
  a human typed by hand is never doubled.
- The manifest, `task list`, `--json` and `projects/README.md` only ever hold the
  clean title. Nothing stores the ✓.
- **`last_pushed.title` DOES hold the decorated title**, because that snapshot's
  contract is "what the last push actually wrote to the board". Storing the clean
  title there would make the very next pull read our own ✓ back, diff it against a
  clean snapshot, and stamp a bogus `human_edited.title` on *every* completed task
  — freezing them all behind `--ack-human` for no reason. This is the single
  nastiest trap in the file and there is a test named after it.
- Pull strips a leading `✓ ` from **both** sides before comparing, and merges the
  stripped text, so a human who retitles a completed task round-trips and never
  bakes the marker into the manifest.
- Deleting the ✓ by hand is **not** read as an edit; the next push puts it back.
  Moving `Complete → In progress` removes it on the next push.
- Expected one-off when this first landed: one retitle of every already-Complete
  task. It converges — the push after that is `0 title/body edit(s)`.

---

## 10. Human-edit detection

A field is a **human** edit exactly when the board no longer holds what the last
push wrote. Tool drift (manifest changed, board still holds the pushed value) is
left alone for the next push to fix.

- Snapshot: `task["last_pushed"]` — `{blocked, body_hash, depends_on, group,
  owner, start, status, target, title}`.
- Pulled fields (`PULL_FIELDS`): `Status`, `Group`, `Owner`, `Start`, `Target`,
  plus the title and the prose half of the body. **Not** `Depends on` / `Blocked`
  (§8).
- A task with **no `last_pushed` yet is skipped**. Without a snapshot there is
  nothing to compare against, and guessing would manufacture fake "human edits".
  This is also why the first push after a schema change is a baseline: edits made
  *before* it cannot be detected.
- A Task dragged into a PR lane (`Merged`, …) is ignored with a warning, as is a
  date that is not `YYYY-MM-DD`.
- A merged edit is stamped `human_edited: {field: {at, value, was}}`.
- `task set` and `project push` then **refuse** to change a stamped field: they
  print the block and exit **3**.
- `--ack-human` records `acked_value`/`acked_at` on the stamp, so the guard stays
  quiet until a human touches that field again.
- `sync` and `autosync` run the pull **before** pushing, so a session can never
  silently overwrite a board edit. `sync --no-pull` skips it; a missing project or
  a missing `project` scope degrades to a quiet no-op (`find_project` never exits).

### Body round-trip

The draft body is the owner's prose, then a tool-owned block between HTML markers:

```
<the owner's prose>

<!-- worktree-sync:attachments -->
### Attachments
_Read every attachment below before working this task…_
- **drawio** `docs/flow.drawio` — the target flow
- **url** <https://github.com/o/r/pull/1>
<!-- /worktree-sync:attachments -->
```

Everything from `ATTACH_BEGIN` on is regenerated on every push. That is exactly
what makes a board edit of the prose half recoverable: `pull` keeps the text before
the marker (`split_body`) and drops the rest. Hand-editing *inside* the marked
block is overwritten without warning.

Attachment paths are stored worktree-relative when the file lives under the
worktree and absolute otherwise; URLs verbatim. `kind` is inferred from the suffix
(`drawio`, `pptx`, `md`, `image`, `url`, `other`) and can be forced with `--kind`.

---

## 11. Exit codes

`0` success · `1` error · `3` `EXIT_HITL`.

3 is deliberately distinct from 1 so a calling agent can tell "needs a human
decision" from a real failure — a retry loop on a conflict would be exactly the
wrong behaviour. There are exactly three `sys.exit(EXIT_HITL)` sites
(`guard_human_edits`, the `guarded` closure in `cmd_task`, and the autosync
re-raise) and a test greps the source to keep it that way.

`autosync` is best-effort and swallows failures so a session can always end — with
the **one** exception of `EXIT_HITL`, which it re-raises. Losing a pending human
decision behind a 0 would be the tool silently deciding the one thing it is not
allowed to decide. Both hooks in `~/.claude/settings.json` end in `|| true`, so a
non-zero exit still never blocks the session.

---

## 12. Rate limits, batching, and pacing

- **Secondary rate limits are real**: ~50 item-mutations back-to-back trips one
  (48 consecutive item adds did it reliably).
- `gql()` sleeps ~0.8s before every mutation and retries a rate-limit error with a
  60s / 120s / 180s backoff.
- A killed push is safe to just re-run: it resumes from the diff.
- PR enrichment (`enrich`) batches by GraphQL alias, one request per 40 PRs — a
  `gh pr view` per PR burns the search quota on a 17-repo worktree. The node id is
  collected for closed and merged PRs too, because that is what
  `addProjectV2ItemById` needs.
- PRs come from **one GraphQL search** for the whole worktree, never REST — REST is
  rate-limited to 30/min *and* omits the head branch.

---

## 13. Tokens

**`GH_TOKEN` / `GITHUB_TOKEN` outrank `hosts.yml`.** The Codespace exports both, so
after `gh auth refresh -s project` the refreshed, correctly-scoped token is
*silently ignored* and the scope gate lies. Every Projects call therefore goes
through `project_env()`, which strips both variables. Do not remove that.

The refresh command itself must be run by a human, and `gh` refuses while those
variables are set:

```bash
env -u GH_TOKEN -u GITHUB_TOKEN gh auth refresh -h github.com -s project
```

---

## 14. Discovery

- **Branches come from each checkout's own HEAD reflog**, not `git branch`: a
  worktree shares `refs/heads` with its parent clone, so listing branches returns
  everything he has anywhere.
- **PRs come from one GraphQL search** (§12).
- Both rules live in `skills/worktree-pr-view/scripts/wt_common.py`, shared with
  `collect_prs.py`. Do not re-derive them here; change them there and re-verify
  both tools.
- `repo_slug()` follows a **local-path origin** to the canonical clone, because
  some worktrees point `origin` at another directory on disk instead of GitHub.
- A repo's own base branch is filtered out of `branches_no_pr` in
  `worktree_sync.py`, not in `wt_common` — only worktree_sync knows the per-repo
  base.
- **Discovery under-reports** when a worktree's HEAD reflog was pruned or the
  worktree was recreated. If an expected PR is missing, that is the first suspect:
  pin the branch in the manifest's `branches` override rather than assuming the PR
  is gone.

### Base branches must be seeded

Everything defaults to `main`, which is wrong often enough to matter — in
`agent-kaif-deploy`, `bridge-kaif-reusable-workflows` bases on `agentvisortest` and
`bdg-sw-auto-orch-helm-chart` on `master`. A wrong base silently produces a
nonsense ahead/behind (`+78` instead of `0/−1`). Read the worktree's own
`README.md`/`CLAUDE.md` table, set `base` per repo in the manifest, re-sync.

---

## 15. Determinism

- A sync with no underlying change **rewrites nothing**: `generated_at` only moves
  when some other field did, so `git -C $DOTFILES_DIR status --porcelain projects/`
  staying empty *is* the "nothing moved" signal.
- JSON is written with sorted keys and 2-space indent so diffs are reviewable
  (`dump`), and only written on a real change (`write_if_changed`).
- Every optional task key is **dropped when empty** (`prune_task`), and the
  dashboard's extra task columns (`Owner`, `Depends on`, `Dates`, `Notes`) and its
  per-group headings only appear when some task actually uses them. A project that
  uses none of the newer features renders and pushes exactly as it did before, so
  the signal stays honest.
- A no-change board push is
  `+0 task(s) … 0 field value(s) set, 0 cleared, 0 row(s) reordered, 0 archived`
  in ~2s. Anything else on an unchanged manifest is a bug worth chasing.
- Items whose PR or task left the manifest are **archived**, never deleted.
- `tasks`, `notes`, `extra_prs`, `exclude_prs`, `branches` and `since` are **merged
  forward** by `build_manifest` and never clobbered; everything else in the
  manifest is regenerated from git and GitHub on every sync.
- **`sync` does not fetch by default.** Ahead/behind is only as fresh as the last
  fetch; `--fetch` refreshes `origin/<base>` per repo and is slower. Use it when
  ahead/behind actually matters, skip it for a quick pass.
- When reporting a sync, quote the `NEW:` / `GONE:` / `DIRTY:` lines — not the
  whole table.

The test suite (`scripts/test_worktree_sync.py`) is **offline, stdlib only, and
touches no real manifest**: it fakes the board at the seams the real code already
has (`ensure_project` / `ensure_fields` / `ensure_views` / `list_items` /
`apply_drafts` / `apply_updates` / `apply_clears` / `gql`), so `ordered_tasks`,
`board_title`, `task_snapshot`, the draft diff and the whole of `pull_project` are
the real code under test.

---

## 16. Commits

`sync --commit` chains sync → render → commit+push to **whatever branch the
dotfiles checkout is on**.

It is deliberately *not* `HEAD:main`: while a tooling branch is checked out here, a
hardcoded target would push that branch's commits to `main` and merge something
nobody approved — the one mistake in this repo that cannot be undone by explaining
it afterwards.

Author **and** committer are forced to `Klalter De Abreu Santos
<klalter@kyndryl.com>` on the commit command itself, because the Codespace exports
`GIT_COMMITTER_NAME=GitHub` / `GIT_COMMITTER_EMAIL=noreply@github.com` and those
silently override `git config`.

If the push 403s, `klalter_kyndryl` lacks push on `klalter/dotfiles`: reset the
scoped `http.extraheader` with the `klalter` token and re-run `commit`.

---

## 17. Bugs that were fixed here — do not reintroduce

- **`title` rebinding in `push_project`.** The project title and the per-task board
  title shared the name `title`, so after the task loop `title` held the *last
  task's* title — and that is what got written into `index.json` as
  `github_project.title`, and from there into the dashboard's board-link text. The
  project title is now `project_title` and the loop keeps `title`. A test asserts
  the index title.
- **`Ready` on a Complete task** (§8).

---

## 18. Dead ends — verified, do not retry

| attempt | what happened |
|---|---|
| Filtering views with the built-in `type:pr` qualifier | rendered an **empty** view; custom `Kind` field works |
| Setting a board's column field via API | `verticalGroupByFields` has no mutation |
| Setting a roadmap's group-by via API | `groupByFields` readable, never writable |
| Setting a roadmap's date fields via API | no input exists; `configuration` exposes only `visibleFields` |
| Sending `visibleFieldIds` to a roadmap view | *"Roadmap views do not support visible fields"* |
| Ordering board columns via `visibleFieldIds` | order ignored, `Title` always pinned first |
| Setting a view's sort via API | no mutation (readable only) |
| Colouring roadmap bars by status | no control in the UI, no field in the API; options already have colours and bars stay neutral |
| Creating a GitHub *saved view* (PR dashboard) | no API at all; manual UI step |
| Naming a field `Repo` / `Type` / `Assignee` | reserved (§5) |
| Creating a single-select with zero options | *"At least one singleSelectOption is required"* |
| Updating single-select options without ids | recreates the options, drops every assigned value |
| Relying on `queue_values` to blank a field | it only sets; needs `clearProjectV2ItemFieldValue` |
| A fine-grained PAT for user-owned projects | not possible; Projects is org-only there |
| Trusting `hosts.yml` while `GH_TOKEN` is exported | env token wins silently, scope gate lies |
| REST for PR discovery | 30/min limit, and it omits the head branch |
| `git branch` for worktree branch discovery | returns every branch in the parent clone |
| Converting a task draft to an issue by hand | breaks `draft_id`, duplicates, then archives the new issue (§2) |
| Hardcoding `HEAD:main` as the push target | would land a tooling branch's commits on `main` (§16) |

---

## 19. Related tools

- **`worktree-pr-view`** — owns the GitHub saved-view query for a single worktree
  and shares `wt_common.py` discovery. The manifest's `view` block holds its query
  and URL.
- **`daily-report`** (project-local) — builds the dated PR `.pptx`. It still keeps
  its own PR JSON; pointing it at `projects/<name>.json` is an open follow-up.

## 20. Hygiene

Before any commit touching a worktree, clear Python bytecode (the KAIF repos
regenerate it on every test run):

```bash
find . -name '__pycache__' -type d -exec rm -rf {} + ; find . -name '*.pyc' -delete
```

Run the offline test suite after touching the push/pull layer:

```bash
python3 $DOTFILES_DIR/skills/worktree-sync/scripts/test_worktree_sync.py
```
