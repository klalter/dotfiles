# Plan — deterministic project automation for tracked worktrees

Status: **proposal**, nothing implemented. Scope: worktrees under `/workspaces/.wt/`
registered in `projects/index.json`. Everywhere else this whole document is inert.

The goal: a session cannot *forget* to record work. Tasks, PRs and status move onto the
GitHub project because the machinery guarantees it, not because an agent remembered a
rule. And every write goes through one deterministic tool, so three different agent CLIs
cannot invent three different behaviours.

---

## 1. What is already true

- `worktree_sync.py` is the only writer. It is idempotent, has `--json` on the read
  commands, and an exit-code contract (`0` ok, `1` error, `3` needs a human).
- Two hooks exist: **SessionStart → `context`** (injects board state) and
  **SessionEnd → `autosync`** (sync → render → commit → push). Both are gated on the cwd
  being a tracked worktree.
- The board wins for anything a human edited: a push snapshots what it wrote, a pull
  detects divergence and stamps `human_edited`, and later writes refuse with exit 3.

## 2. What is missing

1. **Mid-session drift.** Everything between SessionStart and SessionEnd is invisible.
   Open a PR at 10:00 and the board learns about it when the session ends — maybe hours
   later, maybe never if the session is killed.
2. **No task-level history.** A task has a status and a body, but no record of *what
   happened when*. "Where are we" has to be reconstructed from chat.
3. **PRs and tasks are unrelated.** Both are board items; nothing says PR #465 is the
   work of t5.
4. **Nothing enforces the tool.** An agent can call `gh api graphql` against the board
   directly and bypass every rule in the skill.

## 3. Three constraints that shape the design

- **A push can take minutes.** 52 field writes plus 61 reorders ran past two minutes;
  mutations are paced ~0.8 s to stay under secondary rate limits. A no-op push is ~2 s.
  → **No hook may ever push synchronously inside a tool call.**
- **Detection is best-effort; discovery is the guarantee.** A hook can watch for
  `gh pr create`, but an agent might open a PR through an MCP tool, the web UI, or a
  teammate might. → Hooks *hint*; the periodic `sync` (a GraphQL search across the
  worktree's repos) is what actually finds PRs. Never rely on the hint alone.
- **The human's board edit must survive automation.** Today `project push` on its own
  does not pull first and will silently revert a fresh edit. → Every automated flush is
  **pull-then-push**, never push alone. This is a prerequisite, not a nice-to-have.

---

## 4. Design

Three layers. Each is useful alone; together they close the loop.

```
  agent (Claude / Codex / Copilot)
        │
        │  typed calls
        ▼
  ┌───────────────────────┐        ┌──────────────────────────┐
  │  Layer 1: MCP tools   │───────▶│  worktree_sync.py        │
  │  (dev-shell-mcp)      │        │  the only writer         │
  └───────────────────────┘        └──────────┬───────────────┘
        ▲                                     │
        │ hints                               │ pull-then-push
  ┌─────┴─────────────────┐        ┌──────────▼───────────────┐
  │  Layer 2: hooks       │        │  GitHub Project board    │
  │  detect · queue ·     │        └──────────────────────────┘
  │  flush · guard        │
  └───────────────────────┘
  ┌───────────────────────┐
  │  Layer 3: task journal│  what happened, on the task itself
  └───────────────────────┘
```

### Layer 1 — MCP tools: the deterministic surface

Wrap the CLI as typed tools in `dev-shell-mcp`, each a thin shell over
`worktree_sync.py … --json`:

| tool | maps to |
|---|---|
| `wt_status` | `status --json` / `context --json` |
| `wt_task_add` / `wt_task_set` / `wt_task_get` | `task add` / `task set` / `task list --json` |
| `wt_task_log` | `task log` (new, §Layer 3) |
| `wt_task_link_pr` | `task pr add` (new) |
| `wt_sync` / `wt_push` / `wt_pull` | `sync` / `project push` / `project pull` |

Why this matters more than convenience: **typed parameters cannot drift.** Today an agent
has to remember that it is `task set <project> t7 done` and not `task <project> set` — I
got that wrong myself on the first try. A tool schema makes it unrepresentable. It also
gives Codex and Copilot the same surface without re-reading a 228-line skill.

Exit 3 becomes a typed result — `{"status":"needs_human","conflicts":[…]}` — so an agent
branches on a field instead of parsing prose, and **no tool exposes `--ack-human`.**
Overriding a human's edit stays a deliberate human-authorised act on the CLI.

### Layer 2 — Hooks: the guarantee

Four hooks, all no-ops outside a tracked worktree, all wrapped so a failure never blocks.

**(a) `PostToolUse[Bash]` — detect, never act.** Matches the command string against a
small pattern set and appends one line to a queue file. Must stay under ~50 ms.

| pattern | queued intent |
|---|---|
| `gh pr create` / `merge` / `close` / `ready` / `edit` | `prs-changed` |
| `git push` | `prs-changed` (a push often precedes or updates a PR) |
| `worktree_sync.py task …` | `tasks-changed` |
| `gh api graphql … ProjectV2` | `board-touched-directly` (audit) |

Queue file: `$DOTFILES_DIR/projects/.queue/<project>.jsonl`, one JSON object per line
(`{at, kind, cmd}`). Append-only, cheap, survives a crashed session.

**(b) `Stop` — flush.** Fires when the assistant finishes a turn: the natural boundary,
because the work is done and the user is reading. If the queue is non-empty *or* the last
flush is older than N minutes (default 20), run:

```
worktree_sync.py sync <project> --pull --commit && worktree_sync.py project push <project>
```

Run it **in the background** with a lock, and let the *next* turn report the result — a
turn must never wait minutes on a board push. On exit 3 the flush stops and writes the
conflict block where the next SessionStart `context` will surface it verbatim. **A hook
never passes `--ack-human`.**

**(c) `PreToolUse[Bash]` — guard.** Deny (exit 2 with a message) any Bash command that
mutates a tracked project board directly: `gh project item-*`, or `gh api graphql` whose
body contains a ProjectV2 mutation, when the cwd is a tracked worktree. The message names
the tool command to use instead. This is what turns "agents should use the tool" from a
rule in a document into something the harness enforces. Read-only `gh api graphql` stays
allowed — the field test needed it, and so did I.

**(d) `SessionStart` / `SessionEnd`** — unchanged, except SessionStart also drains a
stale queue left by a killed session.

**Loop safety.** The flusher runs `worktree_sync.py`, which the PostToolUse detector
would otherwise queue again. Guard with an env var (`WT_SYNC_INTERNAL=1`) set by the
flusher and checked first by the detector.

**Concurrency.** Multiple sessions in different worktrees already interleave commits in
`$DOTFILES_DIR` — that happened repeatedly today. The flusher takes an flock on
`$DOTFILES_DIR/projects/.lock` around manifest-write + commit + push, and skips (rather
than queues) if the lock is held: the other holder is about to do the same work.

### Layer 3 — The task journal

Give each task an append-only history so "where are we" is readable off the board.

- Manifest: `log: [{at, actor, kind, text}]`, `actor` = `agent` | `human` | `hook`.
- CLI: `task log <project> t7 "…" [--kind note|status|pr|blocked]`.
- Rendered into the draft-issue body under a `## Activity` heading, below the
  instructions and attachments, newest last. Round-trips the same way attachments do
  (split on a marker comment), so a human editing the prose half never fights it.
- Written automatically by: status changes (`t7: New → In progress`), the PR hook
  (`PR #465 opened`, `PR #465 merged`), and the flusher when it merges a human board edit
  (`status set to Complete on the board by a human`).
- Agents write to it deliberately for anything a later reader needs: what was tried, what
  was ruled out, what is blocked and on whom.

**PR ↔ task linking.** `task pr add <project> t5 owner/repo#465` stores the relation;
the board renders it as a `PRs` text column on the task and the journal records it. The
PR-creation hook attaches the new PR to the session's focused task
(`task focus <project> t5`, stored per worktree) when one is set, and otherwise logs
`unattached PR #n` so it is visible rather than lost.

---

## 5. What this buys, concretely

- A PR opened at 10:00 is on the board minutes later, attached to the task that produced
  it, with a journal line — not at session end, and not never.
- "Where are we" is answerable from the board alone: phase, owner, dependency, dates,
  status, and a dated history per task.
- Another agent picking up t13 reads its body, attachments and journal, and knows what
  the last session tried.
- An agent physically cannot hand-edit the board around the tool.
- The human's edits still win, because every automated path is pull-then-push and no
  automated path can ack.

## 6. Order of work

Each step is independently useful; stop anywhere.

| # | step | why first |
|---|---|---|
| 0 | **Fix `project push` to pull first** (or refuse without a recent pull) | Prerequisite. Automating a push that reverts human edits multiplies the bug. |
| 0b | Fix the false `pushed to origin/main` line; make `--ack-human` release the guard | Both are already-known defects that automation would amplify. |
| 1 | Task journal (`task log`, `## Activity` render) | Pure value, no hooks, no risk. |
| 2 | PR ↔ task link + `task focus` | Needed before a PR hook has anywhere to attach. |
| 3 | PostToolUse detector + queue (no flushing yet) | Observe for a day; check the patterns catch what they should. |
| 4 | Stop-hook flusher with lock and backoff | The behavioural change. Watch latency. |
| 5 | PreToolUse guard | Last, because it can block work if the pattern is too broad. |
| 6 | MCP tools in `dev-shell-mcp` | Once the CLI surface has stopped moving. |

## 7. Risks

- **Turn latency.** If flushing is not truly async, every turn ends with a multi-minute
  pause. Mitigation: background + lock + report-next-turn. This is the one that would
  make the whole thing hated.
- **Hook noise.** A detector too eager (e.g. matching all `git push`) queues constantly.
  Mitigation: the flusher is cheap when nothing changed (~2 s no-op push) and the
  time-based floor stops thrash.
- **Guard false positives.** A denied Bash call is disruptive. Mitigation: narrow
  patterns, mutations only, and a documented escape hatch.
- **Journal bloat.** Draft bodies have a size limit and a long journal crowds the
  instructions. Mitigation: render the last N entries on the board, keep the full history
  in the manifest.
- **Two sources of "current task".** `task focus` can go stale and mis-attach PRs.
  Mitigation: focus expires at session end; unattached PRs are logged, never guessed.
