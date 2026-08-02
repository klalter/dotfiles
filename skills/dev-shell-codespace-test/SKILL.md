---
name: dev-shell-codespace-test
description: Spin up a throwaway GitHub Codespace on a tracked worktree's branch and run the dev-shell clean-environment and services E2E suites inside it. Use ONLY when Klalter explicitly asks for a new/clean Codespace to test in ("spin up a codespace", "test this in a clean env", "test on a fresh codespace"). Never spin one up on your own initiative.
---

# Clean-Codespace testing for dev-shell

A Codespace is the **only** way to prove a change works in a genuinely clean
environment: fresh devcontainer, fresh dotfiles install, no local state that has
been accreting for weeks. This skill owns that flow.

## The rule that matters

**The main session stays where it started.** Local work — the worktree under
`/workspaces/.wt/<lane>/<slug>`, the branches, the commits, the PRs — is done
locally, as always. The Codespace is a **test target only**.

Spin one up **only when Klalter explicitly says so.** It is a paid 8-core
machine; creating one uninstructed is a real cost. Nothing in this skill is
"proactive".

One Codespace per worktree under test. Keep it, reuse it, and keep it clean —
do not accumulate a graveyard of them (`gh codespace list` to check first).

## Every gh call needs the env stripped

`GH_TOKEN`/`GITHUB_TOKEN` outrank the stored gh credential and the Codespaces
API will 403. **Every** codespace command must strip them:

```bash
CS=<codespace-name>
GHCS() { env -u GH_TOKEN -u GITHUB_TOKEN gh "$@"; }

GHCS codespace list
GHCS codespace ssh -c "$CS" -- 'echo hello'
```

The `codespace` scope also has to be on the *stored* token, not the env one:

```bash
env -u GH_TOKEN -u GITHUB_TOKEN gh auth refresh -h github.com -s codespace
```

That is an interactive browser login — **ask Klalter to run it**; an agent
cannot.

## Create

```bash
GHCS codespace create \
  -R <org>/<repo> \
  -b <the worktree's branch> \
  -m premiumLinux \
  --idle-timeout 60m
```

`premiumLinux` (8 cores) is enough; `largePremiumLinux` only if the suite needs
it. Then wait for `state == Available`:

```bash
until [ "$(GHCS codespace view -c "$CS" --json state -q .state)" = Available ]; do sleep 15; done
```

## `Available` does not mean ssh-able — poll, don't panic

`gh codespace ssh` needs an sshd listener, which dev-shell's
`.devcontainer/post-start.sh` starts via `"$SCRIPTS_ROOT/sshd.sh" start`
(`SCRIPTS_ROOT=/workspaces/.scripts`).

That works on the **first** boot — measured from a real creation.log:

```
18:51:30Z  dotfiles installed to /workspaces/.codespaces/.persistedshare/dotfiles
18:55:09Z  Running the postStartCommand from devcontainer.json...
18:55:22Z  [OK] sshd listening on port(s): 22 2222
```

The trap is that the API reports `state == Available` **before**
`postStartCommand` finishes. An ssh issued right after creation lands in that
~4-minute window and fails with a misleading *"Please check if an SSH server is
installed in the container"*. That message is a lie — nothing is wrong; the
listener just does not exist yet.

So poll instead:

```bash
for i in $(seq 1 20); do
  GHCS codespace ssh -c "$CS" -- 'echo ready' 2>/dev/null | grep -q ready && break
  sleep 30
done
GHCS codespace ssh -c "$CS" -- 'pgrep -a sshd'   # confirm the listener
```

A stop/start cycle also clears it, but that is a heavier workaround for a race,
not a required step — do not build it into a routine.

**Do not conclude "the sshd bootstrap is broken" from one early failure.** That
mistake was made once already, on the basis that `/workspaces/.scripts` is a
symlink into the dotfiles persisted share and *might* be installed after
`postStartCommand`. The creation.log above refutes it: dotfiles land ~3.5
minutes **before** postStart runs. Check the log before theorising.

## Copy files in — do NOT use `gh codespace cp`

`gh codespace cp` wraps the destination in literal quotes and scp fails with
`dest open "'/tmp/'": No such file or directory`. Pipe over ssh instead:

```bash
GHCS codespace ssh -c "$CS" -- 'cat > /tmp/01-clean-env.sh' < scripts/01-clean-env.sh
GHCS codespace ssh -c "$CS" -- 'md5sum /tmp/01-clean-env.sh'   # verify against local md5sum
```

## Run the suites

Both scripts live in `scripts/` next to this file, are deterministic, take no
arguments, print `✅`/`❌` per check with a `RESULT: N passed, M failed` footer,
and exit non-zero on any failure.

```bash
GHCS codespace ssh -c "$CS" -- 'cd /workspaces/<repo> && bash /tmp/01-clean-env.sh'
GHCS codespace ssh -c "$CS" -- 'cd /workspaces/<repo> && bash /tmp/02-services-e2e.sh'
```

| script | proves |
|---|---|
| `scripts/01-clean-env.sh` | the environment itself: sshd, global skills wiring, global gitignore, toolchain, branch state, and that the removed `work` feature is really gone |
| `scripts/02-services-e2e.sh` | the product: `devx up`, POA controller + policy services healthy, Flipt, port 33000, the consoles, and Playwright screenshots of the orchestration and policy UIs |

Run them long-form (background + poll) — the services suite pulls images and
takes minutes. ssh buffers output until the command exits.

## Interpreting failures

The discipline that makes this worth anything: **when a check fails, first
prove the check is right.** A wrong assertion looks exactly like a broken
environment. Verify by hand inside the Codespace before reporting a defect, and
say plainly which it was. Classic traps already burned once:

- grepping `--work` also matches `--workspace` (a different, still-supported
  flag) — use a word boundary;
- `devx migrate` needs a `.user` fixture and `--from`, it is not a bare
  init-in-an-empty-dir;
- `accounts` is not a `devx` command and never was.

## Screenshots

Playwright evidence lands in `evidence/` next to this file, named
`<area>-<yyyy-mm-dd>.png`. Pull them out of the Codespace by base64 over ssh
(`cp` is broken, see above):

```bash
GHCS codespace ssh -c "$CS" -- 'base64 -w0 /tmp/shots/orchestration.png' | base64 -d > evidence/orchestration-$(date +%F).png
```

## When you are done

Do **not** delete the Codespace unless Klalter says to — he generally keeps one
per worktree under test. `--idle-timeout 60m` means it stops itself. Leave the
repo working tree inside it clean so the next run starts from a known state.

## Related

- `dev-shell` — the local dev-shell workflow and the devx CLI.
- `worktree-sync` — the tracked worktree the branch under test belongs to.
