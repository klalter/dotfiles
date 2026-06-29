# dotfiles

Personal dotfiles plus **[`devbox/`](devbox/README.md)** — an ephemeral
dev-container-in-a-VM that brings up Docker-in-Docker and a headless browser on
any fresh Ubuntu host, on any cloud.

## Contents

- **`install.sh`** — install the personal scripts in `scripts/` onto a machine
  (adds them to `PATH`, wires up a GitHub token in Codespaces).
- **`scripts/`** — small personal helpers (e.g. `cld`, the Claude launcher).
- **`devbox/`** — the ephemeral dev environment. See **[devbox/README.md](devbox/README.md)**.
- **`tests/`** — a deterministic test suite proving each devbox script delivers
  what it should. Run `./tests/run.sh` (or `make test`).

## Quickstart for the devbox

```bash
sudo ./devbox/bootstrap.sh   # install Docker on a fresh Ubuntu host (idempotent)
./devbox/devbox.sh up        # build + start the ephemeral box
./devbox/devbox.sh doctor    # prove DinD + browser work
./devbox/devbox.sh down      # throw it away
```

See **[devbox/README.md](devbox/README.md)** for the full picture.
