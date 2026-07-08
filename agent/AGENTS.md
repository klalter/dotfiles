# Global agent memory

Single source of truth for every coding agent on this machine. `install.sh`
symlinks this one file into each agent's global-instructions path, so they all
read the exact same rules:

| Agent       | Reads from                                         |
| ----------- | -------------------------------------------------- |
| Claude Code | `~/.claude/CLAUDE.md` → this file                  |
| Codex CLI   | `~/.codex/AGENTS.md` → this file                   |
| Copilot     | `~/.copilot/instructions/global.instructions.md` → this file (via VS Code `chat.instructionsFilesLocations`) |

Keep it short and tool-agnostic. Project-specific rules belong in each repo's
own `CLAUDE.md` / `AGENTS.md`.

## Preferences

- Shell is bash; personal helper scripts live in `$DOTFILES_DIR/scripts`
  (`cld` = Claude, `cdx` = Codex, both yolo-mode launchers).
- Shared agent skills live in `$DOTFILES_SKILLS_DIR` (symlinked to
  `~/.claude/skills` and `~/.codex/skills`). Add new reusable skills there, not
  in one-off repos.
- Prefer small, focused commits with clear messages.

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

## Model roster & how to pick

Ratings are relative heuristics (★ = weak … ★★★★★ = best-in-class). Pick by the
**task**, not by cost alone — cost only breaks ties between models that both fit.

| Model          | Family    | Intelligence | Design/visual | Writing | Cost   | Herd role — pick it for                                            |
| -------------- | --------- | :----------: | :-----------: | :-----: | :----: | ----------------------------------------------------------------- |
| **Opus 4.8**   | Anthropic |    ★★★★★     |     ★★★★      |  ★★★★★  | $$$$   | Orchestrator (you). Hardest reasoning, architecture, ambiguity.   |
| **Sonnet 5**   | Anthropic |    ★★★★      |     ★★★★      |  ★★★★   | $$     | **Default sub-agent.** Implementation, refactors, tests, analysis.|
| **Haiku 4.5**  | Anthropic |    ★★★       |     ★★        |  ★★★    | $      | Bulk/mechanical: file sweeps, renames, log-scraping, boilerplate. |
| **Fable 5**    | Anthropic |    ★★★★      |     ★★★★★     |  ★★★★★  | $$     | Design & prose: docs, UI copy, storyboards, naming, dataviz.      |
| **GPT-5.5**    | OpenAI    |    ★★★★★     |     ★★★★      |  ★★★★   | $$$$   | Cross-model second opinion / adversarial review / alt orchestrator.|
| **GPT-5**      | OpenAI    |    ★★★★      |     ★★★★      |  ★★★★   | $$$    | Strong alt workhorse; independent verification.                   |
| **GPT-5 mini** | OpenAI    |    ★★★       |     ★★        |  ★★★    | $      | Cheap OpenAI bulk work when you want provider diversity.          |

Default ladder on an Anthropic-only box: **orchestrate on Opus → workhorse on
Sonnet 5 → bulk on Haiku 4.5 → creative/prose on Fable 5.**

### Cross-model (OpenAI) sub-agents

Only reach for GPT models when the tool is actually installed in this
environment — check first:

- `command -v codex` (or `cdx`) → you can spawn **Codex/GPT** sub-agents
  (default GPT-5.5). Launch with `cdx` (pass `-m <model>` to pick one).
- `command -v copilot` / `gh copilot` → **Copilot** is available; the *user*
  chooses which model Copilot runs, so ask if it matters.

Use cross-model agents for **independent second opinions, adversarial review,
or tasks that suit the other family's strengths** — not by default. Same-family
Anthropic agents are the normal case; provider diversity is a deliberate choice,
not the baseline.

## Driving herdr (mechanics)

- **Start an agent** in its own pane:
  ```
  herdr agent start <name> --cwd <dir> --tab w1:t1 --split right|down --no-focus -- cld --model sonnet
  ```
  For a GPT sub-agent swap the launcher: `... -- cdx` (add `-m gpt-5` etc.).
- **Dispatch a prompt:** `herdr pane run <pane_id> "<single-line prompt>"`.
  Keep prompts single-line — long/multi-line prompts land as `[Pasted text #1]`
  and may **not** auto-submit. Verify with `herdr agent read <name>`; if it's
  still sitting unsent, press Enter with `herdr pane run <pane_id> ""` (or
  `herdr pane send-keys <pane_id> Enter`).
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
