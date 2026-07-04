# dotfiles

Personal dotfiles, built to be a **GitHub Codespaces–ready dev environment**:
point Codespaces at this repo (Settings → Codespaces → *Automatically install
dotfiles*) and every new codespace comes up with your prompt, your scripts,
and your AI agents already wired.

Also includes **[`devbox/`](devbox/README.md)** — an ephemeral
dev-container-in-a-VM that brings up Docker-in-Docker and a headless browser
on any fresh Ubuntu host, on any cloud.

## What a new box gets

`install.sh` runs automatically in Codespaces (and is safe to re-run by hand
anywhere). It sets up:

- **`cld`** — launch Claude Code in yolo mode. Self-sufficient: installs
  Claude Code first if missing. Claude is the default agent on every box.
- **`cdx`** — same thing for OpenAI Codex, opt-in: nothing is installed until
  the first time you run `cdx`, then it runs Codex in yolo mode.
- **`skills/`** — one shared skills folder for all agents, symlinked to
  `~/.claude/skills` **and** `~/.codex/skills`, and exported to bash as
  `$DOTFILES_SKILLS_DIR`. Add a skill once, every agent on every machine has
  it after `git pull`. See [skills/README.md](skills/README.md).
- **`agent/`** — global agent memory (`CLAUDE.md`, `AGENTS.md`), symlinked to
  `~/.claude/CLAUDE.md` and `~/.codex/AGENTS.md`.
- **[Starship](https://starship.rs) prompt** — the modern cross-shell prompt
  (Spaceship's spiritual successor that also works in bash). Config lives in
  [`config/starship.toml`](config/starship.toml).
- **`shell/bashrc.sh`** — all shell config in one repo-managed file;
  `~/.bashrc` gets a single source line, so `git pull` updates every machine.
- **Codespaces token upgrade** — drop a PAT in `/workspaces/.env` and new
  shells export it as `GITHUB_TOKEN`/`GH_TOKEN` instead of the repo-scoped
  codespace token.

## Layout

- **`install.sh`** — idempotent installer (Codespaces entrypoint).
- **`shell/`** — bash config sourced from `~/.bashrc`.
- **`scripts/`** — personal CLIs on PATH (`cld`, `cdx`, ...).
- **`skills/`** — shared agent skills (Claude Code + Codex).
- **`agent/`** — global agent memory files.
- **`config/`** — tool configs (starship).
- **`devbox/`** — ephemeral dev environment. See [devbox/README.md](devbox/README.md).
- **`tests/`** — deterministic test suite. Run `./tests/run.sh` (or `make test`).

## Quickstart

```bash
./install.sh          # set up this machine (Codespaces does this for you)
exec bash             # pick up the new shell config
cld                   # Claude Code, yolo mode (installs it if missing)
cdx                   # Codex, yolo mode (installs it on first use)
```

## Quickstart for the devbox

```bash
sudo ./devbox/bootstrap.sh   # install Docker on a fresh Ubuntu host (idempotent)
./devbox/devbox.sh up        # build + start the ephemeral box
./devbox/devbox.sh doctor    # prove DinD + browser work
./devbox/devbox.sh down      # throw it away
```

See **[devbox/README.md](devbox/README.md)** for the full picture.
