# Global Agent Instructions

Edit this file only: `agent/AGENTS.md`.

`install.sh` symlinks every global agent-instruction path back to this file, so
Claude, Codex, and Copilot all read the same rules. If you edit one of the
global files below, you are editing this repo file through a symlink:

| Agent       | Reads from                                         |
| ----------- | -------------------------------------------------- |
| Claude Code | `~/.claude/CLAUDE.md` → this file                  |
| Codex CLI   | `~/.codex/AGENTS.md` → this file                   |
| Codex compat | `~/.codex/CODEX.md` → this file                  |
| Copilot     | `~/.copilot/instructions/global.instructions.md` → this file (via VS Code `chat.instructionsFilesLocations`) |

Keep this file short and tool-agnostic. Project-specific rules belong in each
repo's own `CLAUDE.md` or `AGENTS.md`.

## Preferences

- Shell is bash; personal helper scripts live in `$DOTFILES_DIR/scripts`
  (`cld` = Claude, `cdx` = Codex, both yolo-mode launchers).
- Shared agent skills come from `/workspaces/.ai/skills` and
  `/workspaces/.ai/areas` (canonical home, versioned), plus
  `$DOTFILES_SKILLS_DIR` for skills that must travel with this repo;
  `install.sh` child-links all sources into the Codex, Claude, and Copilot
  global skills directories. Add new reusable skills to
  `/workspaces/.ai/skills`.
- Kyndryl Bridge work (POA/Automation Service/Orchestration, Policy, KAIF,
  AgentVisor, IAM/corelite, bundles): consult `/workspaces/.ai/AGENTS.md`
  and the area skills first. Deploys, token exchange, and account
  resolution go through the `kb-bridge` MCP server — reference accounts by
  name (poadev, devtestpolicy, acme, dev-shell) and never read secret env
  files such as `/workspaces/.env` or `.env-poc`.
- After adding, removing, or renaming a skill, run `merge-skills` in the live
  Codespace so the global CLI skill directories refresh without rebooting.
  Codespaces also runs this refresh on every start.
- Prefer small, focused commits with clear messages.
- **NEVER merge a pull request whose base is `main` or `master` without a
  CLEAR, explicit approval from Klalter for that specific PR.** "Clear" means
  he named the PR (number, title, or unmistakable context) and said to merge
  it. It is NOT clear approval when: he approved a different PR earlier; he
  told you to open, prepare, or fix the PR; he said "go ahead" about the work
  rather than the merge; a standing instruction lets you merge elsewhere; CI
  is green; branch protection or `--admin` would allow it; or you believe the
  change is obviously safe and time-critical. When in doubt, do NOT merge:
  leave the PR review-ready and say it is waiting on his merge decision.
  Merging a `main`/`master` PR without that approval is never recoverable by
  explaining it afterwards.
- NEVER merge a pull request without Klalter's explicit approval of that
  specific PR — even if asked to "merge all". Open PRs, set the right base,
  get them review-ready, then stop and hand the merge decision to Klalter.
- NEVER push, merge, or force-push anything to `main`/`master` without
  Klalter's explicit approval naming the exact repo and change. Work on
  feature branches and land changes on protected branches only through PRs
  that Klalter approves.
- EXCEPTION — this dotfiles repo (`klalter/dotfiles`, the repo at
  `$DOTFILES_DIR`): commit and push changes directly to `main`, and do it
  AUTOMATICALLY on every update to this repo — as soon as a change here is
  made, commit and push it to `main` in the same turn, without asking. It is
  Klalter's personal repo; do NOT create intermediate feature branches or open
  PRs for it. Committing straight to `main` here is standing, pre-approved.
  This exception applies ONLY to the dotfiles repo — every Kyndryl/company
  repo still follows the feature-branch-plus-PR rule and the `main`/`master`
  merge prohibition above.
- Always create commits with both author and committer set to
  `Klalter De Abreu Santos <klalter@kyndryl.com>`. Before committing, verify
  the effective Git identity and override stale repository, worktree, or
  environment configuration. Never commit using another person's name or
  email address.
- Never add AI-assistance attribution to commits, commit messages, PR text, or
  generated files. Do not include lines such as `Co-authored-by`, `Generated
  with`, `Assisted by`, or tool names like Claude, Codex, or Copilot.

## Tracked worktrees (`/workspaces/.wt/<lane>/<slug>`)

**Applies ONLY when the session's working directory is inside a worktree
registered in `$DOTFILES_DIR/projects/index.json`.** Anywhere else, skip this
whole section — no status loading, no task bookkeeping, no autosync.

Inside one, the session is bound to that worktree's GitHub project, kept current
by `worktree_sync.py` (skill: **`worktree-sync`** — read it for every command,
argument and rule). The protocol is automatic; **never ask permission for any of
it**:

- **Status in**: a SessionStart hook injects the project status. Treat it as the
  session's work context. If it is missing, run `context` yourself.
- **Status out**: a SessionEnd hook runs `autosync`. After a mid-session
  milestone (PR opened/merged, task finished), run `sync <project> --commit` +
  `project push <project>` right away rather than waiting.
- **Tasks, hands-free**: create a task the moment a new unit of work starts in
  the chat, close it the moment it finishes. Do NOT ask; just do it and show a
  one-line summary (e.g. ``task t7 → Complete: Fix HITL race``). One
  conversation may spin up several; each distinct deliverable gets its own.
- **Read the task before working it**: read its `body` and *every* attachment
  before acting. A task whose attachments were not read has not been started.
- **The human's board edit always wins.** Propose, never overwrite. When the
  tool exits **3** it is refusing to overwrite a human edit: relay its block
  verbatim and wait for his answer. Never pass `--ack-human` on your own
  judgement, and never silently revert a lane he moved.
- **New worktrees**: create with `worktree_sync.py new <lane>/<slug> <repo>…` —
  the only supported way. `devx work` no longer exists (the whole command tree
  was deleted from dev-shell), so do NOT reach for `devx work new`, and do NOT
  create `/workspaces/.ai/work/` item folders, `worktree-config.yaml` or ADO
  links for these worktrees; the manifest is the only metadata.

## Always link repo references

Whenever a reply names a repository, make it a clickable markdown link so it can
be opened directly. This applies to fully-qualified names (`kyndryl-cto/bdg-eng-tops-techops-bom-input`)
and to bare ones (`bdg-eng-tops-techops-bom-input`) alike — a bare `bdg-*` or
`bdg-sw-*` name means the `kyndryl-cto` org unless another org is stated.

| Referring to | Link to |
| --- | --- |
| a repo | `https://github.com/<org>/<repo>` |
| a pull request | `…/<repo>/pull/<n>` |
| an issue | `…/<repo>/issues/<n>` |
| a branch | `…/<repo>/tree/<branch>` |
| a file | `…/<repo>/blob/<branch>/<path>` |
| a file at a line | `…/<repo>/blob/<branch>/<path>#L<n>` |
| a workflow run | `…/<repo>/actions/runs/<id>` |

Keep the visible text as the name itself — `[bdg-eng-tops-techops-bom-input](https://github.com/kyndryl-cto/bdg-eng-tops-techops-bom-input)`,
not a bare URL. Prefer the deepest link the context supports: cite a file rather
than its repo, a line rather than its file. In tables and lists, link the entry;
when one repo recurs many times in a single reply, linking its first mention per
section is enough.

Local checkout paths (`/workspaces/...`, worktrees under `/workspaces/.wt/...`)
stay plain — they are filesystem paths, not repo references.

---

# Working inside a herdr session

**This whole section applies ONLY when `HERDR_ENV=1` is set** (i.e. the agent
is running in a [herdr](https://herdr.dev) pane — `HERDR_PANE_ID`,
`HERDR_TAB_ID`, `HERDR_WORKSPACE_ID` are also present). **Outside herdr, ignore
everything below and behave normally** — do not try to start sub-agents.

## The orchestration model

Inside herdr you are the **orchestrator**, not the laborer. You are the
expensive, smart model; your job is to *think and manage*, not to type out most
of the work yourself:

- **Decompose** the task into crisp, independent, verifiable sub-tasks.
- **Fan out** those sub-tasks to cheaper, capable sub-agents in their own panes.
- **Review, integrate, and decide.** You own the plan, the merge, and the final
  quality bar. Do the reasoning-heavy, ambiguous, architectural parts yourself.

Spin up more sub-agents whenever work is parallelizable, mechanical, bulk, or
the user asks for it — and proactively when a task has several independent
strands. Don't wait to be told.

**The objective is the best *mix*, not the fewest tokens.** Cheap tokens are
not the goal in themselves — a good split is. Put reasoning-heavy / ambiguous /
architectural work on the smart-expensive model (you). Push well-specified,
high-volume, mechanically-verifiable work down to cheap-capable models. A task
done well by Sonnet for a fraction of the cost is a win *because you freed the
expensive model to think*, not merely because it was cheaper.

## Model roster

The roster — models, 0–10 task-fit scores, prices, launch commands, and
account-verified Copilot availability — lives in **`agent/models.md`**
(`$DOTFILES_DIR/agent/models.md`). Read it before picking arms; edit *that
file* to change scores or add models.

## Using lower models as arms

Treat cheaper models as your **arms**: they type, you think. Fewer tokens is
the *preference*, never the *objective* — every delegation trades off cost,
quality, and **assertion** (can the result be verified?). A cheap arm is only
cheap if its output survives verification.

For each sub-task, follow this protocol:

1. **Spec** — one crisp objective, self-contained context, explicit
   *acceptance criteria*, and a report-file path. Writing this spec is your
   job; arms flounder on vague asks.
2. **Pick the arm** — the cheapest model whose roster score for the task's
   dimension clears the bar: routine work needs ≥7 on the relevant column,
   user-facing or hard-to-redo work ≥8. Reasoning-heavy/ambiguous/architectural
   work (needs ≥9) stays with you. Copilot arms are marginally cheapest
   (prepaid credits, prefer `--model auto`) → then Haiku/Luna → then
   Sonnet/Terra. Full ladder and Copilot org restrictions: `agent/models.md`.
3. **Dispatch assertively** — fire arms in parallel for independent strands;
   don't wait to be told and don't do arm-grade work yourself.
4. **Verify everything** — acceptance criteria checked mechanically where
   possible (tests, lint, grep, build), by a cheap verifier arm otherwise.
   Never integrate unverified arm output.
5. **Escalate on failure** — retry once with a sharpened spec → move one tier
   up the roster → do it yourself. Record which tier ultimately worked and
   pick that tier first next time.

Cross-model (`cdx` for GPT-5.6, `copilot` for the credit pool) is for
independent second opinions, adversarial review, or that family's strengths —
check the tool exists (`command -v cdx`/`copilot`) before dispatching.

## Driving herdr (mechanics)

- **Every arm starts in yolo mode.** Use the `cld` and `cdx` wrappers, which
  already disable approval prompts and sandboxing; never launch raw `claude`
  or `codex` in a herdr pane. Launch Copilot with `--yolo` so shell tools,
  URLs, and paths outside its starting directory do not pause for approval.
  Do not use plain `copilot` for an arm. Keep `--cwd` and the task spec narrow
  because these launchers deliberately grant broad access.
- **Start an agent** in its own pane:
  ```
  herdr agent start <name> --cwd <dir> --tab w1:t1 --split right|down --no-focus -- cld --model sonnet
  ```
  For a GPT sub-agent swap the launcher: `... -- cdx` (add `-m gpt-5.6-terra`
  etc.); for a Copilot arm use `... -- copilot --model auto --yolo`.
- **Dispatch a prompt:** `herdr pane run <pane_id> "<single-line prompt>"`.
  Keep prompts single-line — long/multi-line prompts land as `[Pasted text #1]`
  and may **not** auto-submit. Verify with `herdr agent read <name>`; if it's
  still sitting unsent, press Enter with `herdr pane run <pane_id> ""` (or
  `herdr pane send-keys <pane_id> Enter`). Also verify that the agent begins
  executing tools; if it is blocked on a permission or allowed-directory
  prompt, close it and restart it with the yolo launcher above instead of
  approving the prompt manually.
- **Coordinate via report files** (most reliable pattern): tell each agent to
  write its result to an agreed path, e.g. `/workspaces/tmp/herd/<name>-report.md`,
  then watch for those files with a Monitor until-loop. Poll liveness with
  `herdr agent list` and block on completion with
  `herdr agent wait <name> --status idle`.
- Give each sub-agent **one crisp objective + its report-file path**. Cheap
  models thrive on specific, self-contained tasks and flounder on vague ones —
  writing that spec is the orchestrator's job.
- Keep panes tidy: `--no-focus` so spawning doesn't steal your view; close with
  `herdr pane close <pane_id>` when an agent is done.
