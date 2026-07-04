---
name: example-skill
description: Template skill proving the shared skills folder is wired up. Ask the agent to "use the example skill" to verify Claude/Codex can see skills from the dotfiles repo.
---

# Example skill

When invoked, reply with:

> Skills are wired up! This skill was loaded from the dotfiles repo
> (`skills/example-skill/SKILL.md`).

Then report which path you loaded it from, so the user can confirm the
symlink (`~/.claude/skills` or `~/.codex/skills`) points at the repo.

Copy this folder as a starting point for real skills.
