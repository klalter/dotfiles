---
name: "reply-like-klalter"
description: "Write chat and comment replies in Klalter's own voice instead of generic assistant prose. Use whenever he asks how do I answer this, reply to the team, draft a reply, what should I say back, or asks to shorten or rewrite a message he is about to send - Teams and Slack replies, PR and code-review comments, GitHub issue comments, and short informal emails. Do NOT use for official deliverables: PowerPoint or decks, Word or docx, formal plans, published documentation, README files, or any customer-facing material - those keep the normal professional register."
---

# Reply like Klalter

Write the reply as Klalter would type it himself, straight into the box. The
output is a message he pastes and sends, not a document.

## Scope guard — read this first

**Use for:** Teams/Slack/chat replies, PR comments, review comments, GitHub
issue comments, short internal emails, quick status pings.

**Never use for:** PowerPoint/decks, Word/docx, formal plans, published
documentation, README files, architecture write-ups, customer-facing material,
anything with a title page or an audience outside the immediate thread. Those
keep the normal professional register — if the request is one of those, ignore
this skill entirely and do not mention it.

Borderline case: a long-form doc that quotes a message is still a doc. Only the
message itself gets this voice.

## How to use the samples

`samples/` holds real messages Klalter wrote, verbatim. More get added over
time and **they will not all sound the same** — a terse status ping and a
detailed reply to reviewers are both him.

1. Read **all** the sample files before drafting.
2. Extract the **shared voice** — the markers below hold across every sample.
3. Pick the **closest-matching register** for the current context: match the
   sample whose audience, length, and purpose most resemble the reply you are
   writing. Blend two when the scenario sits between them.
4. **Never average them into one bland template.** A one-line answer to a
   colleague should not inherit the numbered-plan scaffolding from a reviewer
   thread, and vice versa.

| # | File | Register / scenario |
|---|------|---------------------|
| 01 | `samples/01-techops-argocd-deletion.md` | Teams reply to TechOps reviewers — confirm a finding, hold a merge, propose an ordered plan |

## The voice

### Punctuation and rhythm

- **`..` as a trailing pause.** His most distinctive marker. Double or triple
  dots mid-thought and at line ends, standing in for a comma or a full stop:
  `checked the transformer to make sure.. there's no "deletion path".. it's
  manual either way..`. This is not standard ellipsis punctuation and it is not
  hesitation — it is the beat between thoughts. Use it, but do not sprinkle it
  onto every line.
- **`-->` for flow and for numbered steps.** Plan items are `--> (1)`,
  `--> (2)`, `--> (3)`. Inside a line, `-->` also means *therefore / otherwise*:
  `...templates/policy.yaml out of bdg-eng-tops-techops-argocd-pipeline -->
  else the app-of-apps re-renders it`.
- **`→` inside a line** to show a sequence: `merge #465 + #266 → development
  builds`.
- **Short declarative fragments** over full grammatical sentences. Clauses
  joined with `..` or `-` rather than subordinated.
- **Lowercase, running starts.** Sentences begin mid-thought — `checked the
  transformer...`, `but there are two deletions - not one:`. No formal opener.
  Never `Hi team, hope this finds you well`.

### Stance

- **Explicit hedging.** He labels his confidence instead of asserting flatly:
  `I'm assuming that both are needed`, `i think`, `I guess Monday`,
  `the order would be this`.
- **Direct asks, unhedged, when it matters.** When something must not happen,
  he says so in one imperative line: `Hold the bom-input merge...` — then gives
  the reason immediately after.
- **@-names people inline** to assign work or request a sanity check, dropped
  into a parenthetical: `(check if makes sense Patricia Batista Duarte Esteban
  Jose Herrera Vargas)`.
- **Parenthetical asides** carry commitments and caveats: `(will try to get
  these PR's prepared before Monday)`, `(or any other app`.

### Formatting habits

- **Raw URLs on their own line**, directly under the step they belong to. Never
  markdown link syntax, never inline in a sentence.
- **Mixes list structures freely** — a plain `1.` `2.` list for findings, then
  `--> (n)` for the plan. That is deliberate: findings are observations, the
  arrows are actions.
- **Numbered plan ends warm.** Action lists close with something human —
  `--> (7) be happy!`.
- **A "write it down" step near the end** of any plan that will be repeated:
  `--> (6) document all that, so we can replicate with KAIF`.
- **Technical precision is never sacrificed for informality.** Exact file
  paths, `prune: false`, namespace names, repo names, PR numbers, JSON
  filenames all stay accurate and verbatim. Informal register, precise content.
- **Personal spelling quirks stay.** `PR's` as a plural. Do not correct these,
  and do not correct his typos when reusing his phrasing.

## Anti-patterns

Never produce:

- Corporate filler — `Please find below`, `As per our discussion`, `Just
  circling back`, `Hope this helps`, `Kind regards`, `Best,`.
- Greetings and sign-offs at all, unless the sample register calls for one.
- Polished prose. Do not convert his fragments into complete sentences.
- Over-formatting — headings he would not use, bold labels on every line,
  nested bullets, tables, horizontal rules.
- Bullet-point walls where two lines of text would do.
- Em-dash-heavy assistant cadence and balanced tricolons. He uses an em dash
  occasionally; the LLM default of one per sentence is a tell.
- Rewriting `..` into `...` or `.`, or `-->` into a bullet. Those markers are
  the point.
- Explaining the plan before giving it. He states the finding, then the plan.

## Drafting checklist

1. **Bias short.** Klalter routinely asks to shorten a draft — start shorter
   than feels complete. If the reply is one fact, it is one line.
2. **Keep his ordering:** finding / confirmation first → the ask → the ordered
   plan → loose ends and caveats last.
3. **Keep exact identifiers verbatim** when technical: paths, flags, namespaces,
   PR numbers, branch names, repo names. Never paraphrase an identifier.
4. **Only build a numbered `--> (n)` plan when there is actually a sequence.**
   A three-word answer does not get a plan.
5. **Paste-ready for Teams:** plain text, light markdown at most. Teams renders
   markdown inconsistently — no tables, no nested lists, no code fences unless
   he is pasting code.
6. Give the draft only. No preamble, no "here's a draft you could send", no
   explanation of the choices unless he asks.

## How to add a new sample

1. Drop the raw message into `samples/NN-short-slug.md`, using the next number
   (`02-`, `03-`, …). Keep a short context header above it: channel, audience,
   purpose, register. Paste the message **verbatim** — do not fix typos,
   spacing, or punctuation. The imperfections are the signal.
2. Add one row to the index table above: number, file path, register/scenario.

That is all. No other edits needed — the voice notes only change if a new
sample reveals a marker that is not already described.
