# devbox — an ephemeral dev container in a VM, on any cloud

`devbox` turns **any fresh Ubuntu host** (an EC2 / GCE / Azure / Hetzner VM, a
local VM, or a laptop) into a self-contained, throwaway development environment
that can:

- **run Docker-in-Docker (DinD)** — build and run containers *inside* the box,
  fully isolated from the host;
- **drive a real headless browser** (Google Chrome) — for UI / end-to-end
  testing with Playwright, Puppeteer, or plain Chrome headless.

Everything is **ephemeral** (one `devbox down` removes the container *and* its
volumes — the host is left clean) and **reproducible** (pinned base image,
official package repositories, no hidden state).

```
                ┌──────────────────────── Ubuntu VM (any cloud) ────────────────────────┐
                │  bootstrap.sh  ─────────────▶  Docker Engine + compose (idempotent)    │
                │                                        │                                │
                │                                devbox up (compose)                      │
                │                                        ▼                                │
                │            ┌──────────────── devbox container (privileged) ──────────┐  │
                │            │  dockerd (DinD)   ·   google-chrome --headless          │  │
                │            │  /workspace (ephemeral vol)   ·   /var/lib/docker (vol)  │  │
                │            └──────────────────────────────────────────────────────────┘ │
                └────────────────────────────────────────────────────────────────────────┘
```

## Quickstart (on a brand-new Ubuntu VM)

```bash
git clone <this-repo> && cd dotfiles

# 1. Provision the host (installs Docker Engine + compose). Idempotent.
sudo ./devbox/bootstrap.sh

# 2. Build + start the ephemeral dev box.
./devbox/devbox.sh up

# 3. Prove it works: Docker-in-Docker AND the headless browser.
./devbox/devbox.sh doctor
#   PASS browser-render
#   PASS dind-run
#   SELFTEST-OK

# 4. Work inside it.
./devbox/devbox.sh shell

# 5. Throw it away — nothing is left on the host.
./devbox/devbox.sh down
```

Or via `make`: `make bootstrap && make up && make doctor && make down`.

## The workflow scripts

Each script does one job and is independently testable:

| Script | Responsibility |
| --- | --- |
| `devbox/bootstrap.sh` | Provision a fresh Ubuntu host with Docker Engine + compose. **Idempotent** (`--check`, `--dry-run` supported). |
| `devbox/devbox.sh` | Lifecycle CLI: `build · up · shell · doctor · status · logs · down`. Thin wrapper over `docker compose`. |
| `devbox/Dockerfile` | The standard image: Ubuntu 24.04 + Docker engine (DinD) + Google Chrome + tools. |
| `devbox/docker-compose.yml` | Runs the box privileged with ephemeral volumes; health-gated on dockerd. |
| `devbox/entrypoint.sh` | Boots the in-container dockerd, then keeps the box alive. |
| `devbox/selftest.sh` | In-container proof that the browser renders and DinD runs a container. |

## How the pieces deliver the goal

- **"Any cloud / any Ubuntu"** — `bootstrap.sh` uses Docker's *official* apt repo
  pinned to the host's own codename, so the result is identical everywhere. It is
  idempotent: re-running it is a no-op.
- **"DinD"** — the container runs `--privileged` with its own `dockerd`
  (`entrypoint.sh`), and its `/var/lib/docker` lives in a throwaway volume.
- **"Run a browser to test UI"** — Google Chrome is installed in the image; run it
  headless (`--headless=new --no-sandbox`) or point Playwright/Puppeteer at it.
- **"Ephemeral"** — `devbox down` does `compose down -v`, deleting the container
  and both named volumes.
- **"Easy to replicate"** — pinned base, official repos, no machine-specific state,
  and a deterministic test suite (below) that anyone can run.

## Tests — proof each script delivers what's needed

```bash
./tests/run.sh                 # everything (integration self-skips without Docker)
./tests/run.sh --no-integration   # fast, deterministic, Docker-free
./tests/run.sh --require-integration   # fail (don't skip) if Docker is missing
```

| Tier | What it proves | Needs Docker? |
| --- | --- | --- |
| `test_10_static` | every script is valid bash and passes `shellcheck` | no |
| `test_20_bootstrap` | bootstrap is idempotent and plans the right official-repo install (driven with fake binaries + dry-run) | no |
| `test_30_devbox_cli` | each CLI verb maps to exactly the right docker/compose command (dry-run) | no |
| `test_40_compose` | the Dockerfile + compose actually describe DinD + browser + ephemerality; `compose config` validates | no |
| `test_90_integration` | really builds the image and runs the box, asserting `PASS browser-render` and `PASS dind-run`, then tears it down cleanly | yes (self-skips otherwise) |

Tiers 10–40 are fully deterministic and need neither root nor network, so they
run anywhere (and in CI, see `.github/workflows/devbox-ci.yml`). Tier 90 is the
end-to-end proof on a host with Docker.

## Notes

- **Docker-in-Docker vs. host socket.** This box uses *true* DinD (its own
  daemon) for maximum isolation and ephemerality. If you'd rather share the
  host's daemon (Docker-outside-of-Docker), bind-mount `/var/run/docker.sock`
  instead of running privileged — `entrypoint.sh` detects an already-reachable
  daemon and won't start a second one.
- **`devbox/extra-ca/`.** Empty by default. If you build behind a
  TLS-intercepting proxy, drop the proxy CA (`*.crt`) here and it will be trusted
  during the build. Safe to leave empty in production.
- **Air-gapped DinD check.** `selftest.sh` honours `DEVBOX_SELFTEST_IMAGE_TAR`:
  point it at a `docker save`d tar and the DinD run check needs no registry.
