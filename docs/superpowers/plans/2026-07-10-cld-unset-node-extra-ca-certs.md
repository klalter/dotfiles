# `cld` NODE_EXTRA_CA_CERTS Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Launch Claude Code through `cld` without passing `NODE_EXTRA_CA_CERTS`, while retaining the variable for optional installer commands.

**Architecture:** Keep the existing installation function unchanged and remove the variable only at the final process boundary with `env -u`. Extend the real launcher test with a stub that reports its inherited environment, proving the behavior through a red-green cycle.

**Tech Stack:** Bash, the repository's shell assertion harness, Git

---

### Task 1: Isolate Claude's Environment

**Files:**
- Modify: `tests/test_15_install.sh:75-80`
- Modify: `scripts/cld:37-38`

- [ ] **Step 1: Write the failing regression test**

Replace the existing Claude stub and invocation with:

```bash
it "cld launches claude in yolo mode without NODE_EXTRA_CA_CERTS (stub binary)"
STUBS="$SANDBOX/stubs"; mkdir -p "$STUBS"
printf '#!/usr/bin/env bash\nprintf "NODE_EXTRA_CA_CERTS:%%s\\n" "${NODE_EXTRA_CA_CERTS-unset}"\necho "ARGS:$*"\n' >"$STUBS/claude"; chmod +x "$STUBS/claude"
out="$(NODE_EXTRA_CA_CERTS=/tmp/broken.pem PATH="$STUBS:$PATH" "$REPO_ROOT/scripts/cld" hello 2>/dev/null)"
assert_contains "$out" "NODE_EXTRA_CA_CERTS:unset"
assert_contains "$out" "ARGS:--dangerously-skip-permissions hello"
```

- [ ] **Step 2: Run the test and verify RED**

Run:

```bash
TESTS_DIR="$PWD/tests" REPO_ROOT="$PWD" bash tests/test_15_install.sh
```

Expected: one failure because output contains `NODE_EXTRA_CA_CERTS:/tmp/broken.pem` instead of `NODE_EXTRA_CA_CERTS:unset`.

- [ ] **Step 3: Implement the minimal launcher change**

Replace the final invocation in `scripts/cld` with:

```bash
ensure_claude
exec env -u NODE_EXTRA_CA_CERTS claude --dangerously-skip-permissions "$@"
```

- [ ] **Step 4: Run the targeted tests and verify GREEN**

Run:

```bash
TESTS_DIR="$PWD/tests" REPO_ROOT="$PWD" bash tests/test_15_install.sh
TESTS_DIR="$PWD/tests" REPO_ROOT="$PWD" DEVBOX_DIR="$PWD/devbox" bash tests/test_10_static.sh
```

Expected: both files report zero failed checks.

- [ ] **Step 5: Re-run the non-integration suite and classify results**

Run:

```bash
./tests/run.sh --no-integration
```

Expected: the changed launcher suites pass. `test_20_bootstrap` may retain the seven baseline failures approved by the user; no new failures are acceptable.

- [ ] **Step 6: Review and commit the focused change**

Run:

```bash
git diff --check
git diff -- scripts/cld tests/test_15_install.sh
git add scripts/cld tests/test_15_install.sh docs/superpowers/plans/2026-07-10-cld-unset-node-extra-ca-certs.md
git commit -m "fix: isolate Claude from invalid extra CA"
```

Expected: one focused commit containing the launcher, regression test, and implementation plan.
