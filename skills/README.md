# skills/

The portable, dotfiles-owned half of the shared skill collection.

> **Canonical home moved:** personal skills (`herd`, `kyndryl-drawio-deck`,
> `example-skill`, …) now live in `/workspaces/.ai/skills` (versioned in the
> persistedshare dotfiles repo) alongside the area skills in
> `/workspaces/.ai/areas`. This directory remains a valid source for skills
> that must travel with this repo to machines without the `.ai` workspace.

`install.sh` exposes both of these source roots to every supported CLI:

| Source | Purpose | Exists when |
|--------|---------|-------------|
| `/workspaces/.ai/skills` | Codespace-wide skills shared by sibling repos | That workspace provides it |
| `skills/` in this repo | Versioned personal skills that travel with the dotfiles | Always |

Each immediate child containing `SKILL.md` is symlinked into the CLI's global
skills directory. This preserves any skills the CLI already installed. Skill
directory names must be unique across the two sources; existing directories and
symlinks are never overwritten.

The installer resolves this repository from its own location, not from
`/workspaces`, so it works after cloning the dotfiles anywhere. Override the
workspace source for a nonstandard layout with `DOTFILES_SHARED_SKILLS_DIR`.

| Agent | Global discovery directory | Installer behavior |
|-------|----------------------------|--------------------|
| Codex CLI | `~/.agents/skills` | Child symlinks from both sources |
| Claude Code | `~/.claude/skills` | Child symlinks from both sources |
| Copilot CLI | `~/.agents/skills`, `~/.copilot/skills` | Child symlinks from both sources |
| Codex compatibility | `~/.codex/skills` | Child symlinks from both sources; existing/bundled skills preserved |
| plain bash | `$DOTFILES_SKILLS_DIRS` | Colon-delimited source paths |

Adding a skill here (commit + push, then `git pull` on another machine) makes
it available after `install.sh` runs. For the common live-Codespace case, run
`merge-skills`; it refreshes the same child links with `DOTFILES_NO_NETWORK=1`,
so it does not reinstall tools or require a reboot. Codespaces also runs
`merge-skills` on every start.

## Skill format

Each skill is a directory containing a `SKILL.md` with YAML frontmatter
(the open Agent Skills format both Claude Code and Codex understand):

```
skills/
  my-skill/
    SKILL.md        # frontmatter: name + description, then instructions
    ...             # optional helper scripts/templates the skill references
```

Minimal `SKILL.md`:

```markdown
---
name: my-skill
description: One sentence on when the agent should reach for this skill.
---

Instructions the agent follows when the skill is invoked...
```

See `example-skill/` for a working template.
