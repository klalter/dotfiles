# skills/

One shared home for agent skills, versioned with the dotfiles.

`install.sh` symlinks this folder into the places each agent looks for
personal skills:

| Agent            | Looks in          | Symlinked by install.sh          |
|------------------|-------------------|----------------------------------|
| Claude Code      | `~/.claude/skills`| `~/.claude/skills -> skills/`    |
| Codex CLI        | `~/.codex/skills` | `~/.codex/skills -> skills/`     |
| plain bash       | `$DOTFILES_SKILLS_DIR` | exported by `shell/bashrc.sh` |

So a skill added here (commit + push, then `git pull` on any machine) is
immediately available to `cld`, `cdx`, and your own scripts everywhere.

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
