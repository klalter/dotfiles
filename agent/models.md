# Model Roster

Single source of truth for model selection in agent orchestration ("the herd").
Referenced by `agent/AGENTS.md` and the `herd` skill. Edit **this file** to
change scores, add models, or record account changes — nothing else needs to
change.

- **Last verified:** 2026-07-10 (Copilot list read live from the account's
  `/model` picker; prices from official docs; benchmarks from public indexes).
- **Refresh triggers:** new model release, Copilot org-policy change, pricing
  change (Sonnet 5 intro pricing ends 2026-08-31).

## Scoring rubric (0–10)

| Column     | Meaning                                                          |
| ---------- | ---------------------------------------------------------------- |
| **Reason** | Deep reasoning, architecture, ambiguity, planning                |
| **Code**   | Implementation, refactors, tests, debugging (agentic coding)     |
| **Bulk**   | Reliability on mechanical, high-volume, well-specified work      |
| **Design** | Visual/UI/diagrams/dataviz quality                               |
| **Write**  | Prose, docs, naming, storytelling                                |
| **Speed**  | Output throughput + latency (10 = fastest)                       |
| **Cost**   | 10 = cheapest. From blended $/MTok = 0.75·input + 0.25·output    |

Scores marked `~` are estimates (thin public benchmark data). Anchors:
Intelligence Index leader ≈ 10 Reason; ~290 tok/s ≈ 10 Speed; ≤$1 blended ≈ 10 Cost.

## Roster

| Model                  | Access (launcher · slug)                | $ in/out per MTok    | Reason | Code | Bulk | Design | Write | Speed | Cost | Herd role                                                       |
| ---------------------- | --------------------------------------- | -------------------- | :----: | :--: | :--: | :----: | :---: | :---: | :--: | --------------------------------------------------------------- |
| **Opus 4.8**           | `cld --model opus`                      | 5 / 25               |  9.5   |  9   |  6   |   8    |  9.5  |   4   |  6   | Orchestrator. Hardest reasoning, architecture, final review.     |
| Opus 4.8 (fast mode)   | Claude Code `/fast`                     | 10 / 50              |  9.5   |  9   |  5   |   8    |  9.5  |  6.5  |  4   | Orchestrator when latency matters more than cost.                |
| **Fable 5**            | `cld --model fable`                     | 10 / 50              |   10   | 9.5  |  5   |   10   |  10   |  4.5  |  4   | Design & prose specialist; strongest SWE-bench Pro (80%).        |
| **Sonnet 5**           | `cld --model sonnet`                    | 2 / 10 (→3/15 Sep 1) |  8.5   | 8.5  |  8   |   8    |   8   |  6.5  |  8   | **Default arm.** Implementation, refactors, tests, analysis.     |
| **Haiku 4.5**          | `cld --model haiku`                     | 1 / 5                |  6.5   | 6.5  |  9   |   5    |   6   |   8   |  9   | Bulk arm: sweeps, renames, log-scraping, boilerplate.            |
| **GPT-5.6 Sol**        | `cdx` (config default, xhigh)           | 5 / 30               |  9.5   | 9.5  |  6   |   8    |  8.5  |  5.5  | 5.5  | Cross-model peer/adversary. Coding-agent SOTA, token-efficient.  |
| **GPT-5.6 Terra**      | `cdx -m gpt-5.6-terra`                  | 2.50 / 15            |  8.5   |  9   |  8   |  7.5   |   8   |  6.5  | 7.5  | Alt workhorse; ≈GPT-5.5 quality at half price.                   |
| **GPT-5.6 Luna**       | `cdx -m gpt-5.6-luna`                   | 1 / 6                |  7.5   |  8   |  9   |  6.5   |   7   |  8.5  |  9   | Cheap-fast OpenAI arm; best benchmark-points-per-dollar.         |
| GPT-5.5                | `cdx -m gpt-5.5`                        | ~5 / 30              |   9    | 8.5  |  6   |   8    |   8   |   5   | 5.5  | Superseded by Sol/Terra — prefer those.                          |
| Copilot **auto** ✓     | `copilot` (account default)             | plan credits, −10%   |  ~7.5  |  ~8  |  8   |   ~7   |  ~7   |   7   |  9★  | **Cheapest arm overall.** Well-specified impl/analysis tasks.    |
| Copilot Sonnet 5       | `copilot --model claude-sonnet-5`       | credits 200/1000     |  8.5   | 8.5  |  8   |   8    |   8   |  6.5  |  8★  | Pin when the task needs guaranteed Sonnet-quality.               |
| Copilot Haiku 4.5      | `copilot --model claude-haiku-4.5`      | credits 100/500      |  6.5   | 6.5  |  9   |   5    |   6   |   8   |  9★  | Pinned bulk.                                                     |
| Copilot GPT-5.3-Codex  | `copilot --model gpt-5.3-codex`         | credits 175/1400     |  7.5   | 8.5  |  8   |   6    |  6.5  |   7   |  8★  | Pin for coding-heavy arms (code-specialized).                    |
| Copilot GPT-5.4 mini   | `copilot --model gpt-5.4-mini`          | credits 75/450       |   6    | 6.5  | 8.5  |   5    |   6   |   8   | 9.5★ | Cheap bulk / triage.                                             |
| Copilot GPT-5 mini     | `copilot --model gpt-5-mini`            | credits 25/200       |   5    | 5.5  |  8   |  4.5   |  5.5  |  8.5  | 10★  | Cheapest possible arm; trivial mechanical work only.             |
| Copilot Gemini 3.5 Fl. | `copilot --model gemini-3.5-flash`      | credits 150/900      |  7.5   | 7.5  |  9   |   7    |  7.5  |  10   | 8.5★ | Speed king (~290 tok/s), 264K ctx; fast sweeps and summaries.    |
| Copilot MAI-Code-1-Fl. | `copilot --model mai-code-1-flash`      | credits 75/450       |  ~5.5  | ~6.5 |  8   |   ~4   |  ~5   |  8.5  | 9.5★ | Cheap code-focused bulk (little public benchmark data).          |

★ Copilot models draw from the plan's prepaid AI-credit pool (100 credits ≈ $1
of API price), so their *marginal* cost to us is the lowest of any provider —
prefer a Copilot arm whenever its quality scores clear the task's bar.

## Copilot account facts (klalter_kyndryl, verified 2026-07-10)

- Billing: **AI credits**; `auto` gets a **10% credit discount** and in this
  account has routed to `gpt-5.3-codex`, `claude-sonnet-5`, `gpt-5.4-mini`.
- **Auto policy:** keep `auto` as the Copilot default (discount + good routing
  for well-specified tasks). Pin explicitly only when the task demands it:
  bulk → `gpt-5-mini`/`claude-haiku-4.5`; coding-heavy → `gpt-5.3-codex` or
  `claude-sonnet-5`; speed/long-context → `gemini-3.5-flash` (264K).
- **Disabled by Kyndryl org policy** (visible but not selectable — do not
  dispatch to these via Copilot): `claude-fable-5`, `claude-opus-4.5…4.8`,
  `claude-opus-4.8-fast`, `claude-sonnet-4.5/4.6`, `gpt-5.6-sol/terra/luna`,
  `gpt-5.5`, `gpt-5.4`, `gemini-3.1-pro-preview`, `kimi-k2.7-code`.
  Fable/Opus quality is reachable only via `cld`; GPT-5.6 only via `cdx`.

## Notes per family

- **Anthropic:** Fable 5 leads Intelligence Index (60) and SWE-bench Pro (80%);
  Opus 4.8 second (56). Sonnet 5 has 1M ctx at standard price; intro pricing
  $2/$10 ends 2026-08-31. Fast mode exists for Opus 4.8 only ($10/$50).
- **OpenAI GPT-5.6** (GA 2026-07-09): three durable tiers. Sol leads the AA
  Coding Agent Index (80) and Agents' Last Exam (53.6), and is unusually
  token-efficient (~85% fewer output tokens than Opus-class on some agentic
  evals). Terra (77.4) edges Fable (77.2) on that index at a quarter of the
  price; Luna ≈ 24 benchmark-points/$ vs 3.2 for Fable.
- **Codex CLI (`cdx`)** default is `gpt-5.6-sol` @ xhigh reasoning — that is an
  *expensive* default; pass `-m gpt-5.6-terra` / `-m gpt-5.6-luna` for arm work.

## Sources

- [Anthropic pricing (platform.claude.com)](https://platform.claude.com/docs/en/about-claude/pricing)
- [OpenAI GPT-5.6 announcement](https://openai.com/index/gpt-5-6/) ·
  [Artificial Analysis: GPT-5.6 landed](https://artificialanalysis.ai/articles/gpt-5-6-has-landed) ·
  [Vellum GPT-5.6 benchmarks](https://www.vellum.ai/blog/gpt-5-6-benchmarks-explained) ·
  [Simon Willison on GPT-5.6](https://simonwillison.net/2026/Jul/9/gpt-5-6/)
- [GPT-5.6 in Copilot changelog](https://github.blog/changelog/2026-07-09-openais-gpt-5-6-sol-terra-and-luna-are-now-available-in-github-copilot/) ·
  [Copilot auto model selection GA](https://github.blog/changelog/2026-04-17-github-copilot-cli-now-supports-copilot-auto-model-selection/) ·
  [Copilot supported models](https://docs.github.com/en/copilot/reference/ai-models/supported-models)
- [AA: Gemini 3.5 Flash](https://artificialanalysis.ai/articles/gemini-3-5-flash-everything-you-need-to-know)
- Copilot credits/model list: read live from `copilot` `/model` picker in this
  account (credits per 1M tokens; 100 credits ≈ $1 API-equivalent).
