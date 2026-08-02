#!/usr/bin/env python3
"""Offline tests for worktree_sync.py and its hooks — no network, no real
manifest, no real board, no real queue touched.

    python3 skills/worktree-sync/scripts/test_worktree_sync.py

Six things are locked down here:

1. The DONE_MARKER round-trip. A task is a DRAFT issue, which has no open/closed
   state, so a Complete task is rendered to the board as "✓ <title>". That
   decoration must never reach the manifest, and it must never be mistaken for a
   human board edit on the way back — the trap the pull tests exist for.
2. The machine surface agents call: the --json shapes, and the exit-code
   contract (0 ok / 1 error / 3 needs-a-human-decision, nothing else).
3. Blocked/Ready describing unfinished work only.
4. **The human's board edit surviving an automated flush**: `project push`
   pulls first, and `--ack-human` RELEASES a field instead of ratcheting it.
   `commit` naming the branch it really pushed belongs to the same family — an
   agent relays that line verbatim.
5. **The hooks**: the detector's patterns and its cost, and that the Stop hook
   detaches its flush and returns in milliseconds, holds a lock against a
   second session, keeps the queue on failure and parks an exit-3 block instead
   of guessing.
6. **Self-location**: no script hardcodes a dotfiles path, so a copy of the
   tree acts on the checkout it was copied into and not on a stale
   `DOTFILES_DIR`.

The board is faked at the seam the real code already has: ensure_project /
ensure_fields / ensure_views / find_project / list_items / apply_drafts / gql.
Everything between them — ordered_tasks, board_title, task_snapshot, the draft
diff, the whole of pull_project — is the real code under test. The hook tests
run the hook scripts as real subprocesses against a throwaway $WT_SYNC_HOME and
a stub worktree_sync.py, because timing and detachment cannot be faked.
"""
import io
import json
import os
import subprocess
import sys
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from argparse import Namespace
from tempfile import TemporaryDirectory
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import worktree_sync as ws  # noqa: E402

WORKTREE = "/workspaces/.wt/feat/demo"
ENTRY = {"name": "demo", "worktree": WORKTREE, "lane": "feat",
         "status": "active", "github_project": None}
PROJECT = {"id": "PVT_kw1", "number": 9, "title": "feat/demo",
           "url": "https://github.com/users/demo/projects/9"}


class FakeBoard:
    """The draft items a project holds, in board order."""

    def __init__(self):
        self.items = {}          # content_id -> {"id","title","body","values"}
        self.order = []
        self.n = 0

    def add(self, title, body="", values=None):
        self.n += 1
        cid = f"DI_{self.n}"
        self.items[cid] = {"id": f"PVTI_{self.n}", "content_id": cid,
                           "title": title, "body": body,
                           "values": dict(values or {}), "draft": True}
        self.order.append(f"PVTI_{self.n}")
        return cid

    def set_title(self, cid, title):
        """What a human clicking the item on github.com does."""
        self.items[cid]["title"] = title

    def list_items(self, _project_id):
        return ({ws.item_key({"title": i["title"]}): dict(i)
                 for i in self.items.values()}, list(self.order))

    def by_item_id(self, item_id):
        return next(i for i in self.items.values() if i["id"] == item_id)

    def apply_drafts(self, drafts, dry_run=False):
        for cid, title, body in drafts:
            self.items[cid]["title"] = title
            self.items[cid]["body"] = body
        return len(drafts)

    def apply_updates(self, _project_id, updates, dry_run=False):
        for item_id, field, value in updates:
            self.by_item_id(item_id)["values"][field["name"]] = value
        return len(updates)

    def apply_clears(self, _project_id, clears, dry_run=False):
        for item_id, field in clears:
            self.by_item_id(item_id)["values"].pop(field["name"], None)
        return len(clears)


# What ensure_fields returns on a real project, reduced to what the task path
# touches. Names are the contract; ids only have to be unique.
FIELDS = {name: {"id": f"F_{name}", "name": name,
                 "dataType": "SINGLE_SELECT" if name in ("Kind", "Status", "Blocked")
                 else "DATE" if name in ("Start", "Target", "Last sync") else "TEXT",
                 "options": [{"id": f"O_{o}", "name": o}
                             for o in ws.TASK_STATUSES + ws.PR_STATUSES
                             + ws.KINDS + ws.BLOCKED_STATES]}
          for name in ("Kind", "Status", "Group", "Owner", "Depends on", "Blocked",
                       "Start", "Target", "Last sync")}


def base_manifest(tasks):
    return {"name": "demo", "worktree": WORKTREE, "lane": "feat",
            "repos": [], "prs": [], "branches_no_pr": [], "view": {},
            "tasks": tasks, "notes": [], "extra_prs": [], "exclude_prs": [],
            "branches": {}, "since": None, "generated_at": "2026-08-02T00:00:00Z"}


def task(tid="t1", title="Ship the thing", status="Complete", **kw):
    t = {"id": tid, "title": title, "status": status, "created": "2026-08-01"}
    t.update(kw)
    return t


class BoardHarness(unittest.TestCase):
    """A tmp projects/ dir plus a fake board, wired for push and pull.

    Carries no tests of its own — every case class below inherits it, so the
    suite runs each test exactly once.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.dir = Path(self.tmp.name)
        (self.dir / "index.json").write_text(ws.dump({"projects": [ENTRY]}))
        p = mock.patch.object(ws, "projects_dir", lambda: self.dir)
        p.start()
        self.addCleanup(p.stop)
        self.board = FakeBoard()
        self.gql_calls = []

    def _gql(self, query, allow_error=False):
        self.gql_calls.append(query)
        if "addProjectV2DraftIssue" in query:
            title = json.loads(query.split("title:", 1)[1].split(",body:", 1)[0])
            body = json.loads(query.split(",body:", 1)[1].split("})", 1)[0])
            cid = self.board.add(title, body)
            item = self.board.items[cid]
            return {"addProjectV2DraftIssue":
                    {"projectItem": {"id": item["id"], "content": {"id": cid}}}}
        return {}

    def push(self, manifest, dry_run=False, as_json=False, ack=False, pull=True):
        """The real push_project against the fake board. Returns the titles it
        wrote through updateProjectV2DraftIssue, and the printed summary.

        `pull` defaults to True exactly like the real command: a push pulls
        first, so the fake board is also the pull source here.
        """
        written = []

        def apply_drafts(drafts, dry=False):
            written.extend(t for _cid, t, _b in drafts)
            return self.board.apply_drafts(drafts, dry)

        out = io.StringIO()
        with mock.patch.object(ws, "ensure_project", lambda *a, **k: dict(PROJECT)), \
             mock.patch.object(ws, "ensure_fields", lambda *a, **k: (FIELDS, [])), \
             mock.patch.object(ws, "ensure_views", lambda *a, **k: []), \
             mock.patch.object(ws, "find_project", lambda *a, **k: dict(PROJECT)), \
             mock.patch.object(ws, "list_items", self.board.list_items), \
             mock.patch.object(ws, "apply_drafts", apply_drafts), \
             mock.patch.object(ws, "apply_updates", self.board.apply_updates), \
             mock.patch.object(ws, "apply_clears", self.board.apply_clears), \
             mock.patch.object(ws, "gql", self._gql), \
             redirect_stdout(out):
            ws.push_project(ENTRY, manifest, dry_run=dry_run, ack=ack,
                            as_json=as_json, pull=pull)
        return written, out.getvalue()

    def pull(self, manifest, dry_run=True):
        out = io.StringIO()
        with mock.patch.object(ws, "find_project", lambda *a, **k: dict(PROJECT)), \
             mock.patch.object(ws, "list_items", self.board.list_items), \
             redirect_stdout(out):
            merged = ws.pull_project(ENTRY, manifest, dry_run=dry_run)
        return merged


class MarkerCase(BoardHarness):
    """The ✓ completion marker: rendered on push, stripped on pull, never data."""

    # ------------------------------------------------------------------ render

    def test_board_title_decorates_only_complete(self):
        self.assertEqual(ws.board_title(task(status="Complete")), "✓ Ship the thing")
        self.assertEqual(ws.board_title(task(status="In progress")), "Ship the thing")
        self.assertEqual(ws.board_title(task(status="New")), "Ship the thing")
        # never doubled, whoever typed the first one
        self.assertEqual(ws.board_title(task(title="✓ Ship the thing")),
                         "✓ Ship the thing")
        self.assertEqual(ws.strip_done_marker("✓ Ship the thing"), "Ship the thing")
        self.assertEqual(ws.strip_done_marker("Ship the thing"), "Ship the thing")
        self.assertEqual(ws.strip_done_marker(None), "")

    def test_marker_switches_off(self):
        with mock.patch.object(ws, "DONE_MARKER", ""):
            self.assertEqual(ws.board_title(task()), "Ship the thing")
            self.assertEqual(ws.strip_done_marker("✓ Ship the thing"),
                             "✓ Ship the thing")

    def test_push_writes_the_marker_and_the_manifest_stays_clean(self):
        t = task()
        m = base_manifest([t])
        cid = self.board.add("Ship the thing")
        t["draft_id"] = cid

        written, _ = self.push(m)

        self.assertEqual(written, ["✓ Ship the thing"])
        self.assertEqual(self.board.items[cid]["title"], "✓ Ship the thing")
        # the in-memory task, the file on disk, the dashboard and `task list`
        self.assertEqual(t["title"], "Ship the thing")
        on_disk = json.loads((self.dir / "demo.json").read_text())
        self.assertEqual(on_disk["tasks"][0]["title"], "Ship the thing")
        self.assertNotIn("✓", (self.dir / "demo.json").read_text())
        self.assertNotIn("✓", "\n".join(ws.render_tasks(m["tasks"])))
        out = io.StringIO()
        with redirect_stdout(out):
            ws.list_tasks(ENTRY, m["tasks"])
        self.assertNotIn("✓", out.getvalue())

    def test_snapshot_records_what_the_board_holds(self):
        t = task()
        m = base_manifest([t])
        t["draft_id"] = self.board.add("Ship the thing")
        self.push(m)
        # last_pushed.title is the DECORATED title — the whole point
        self.assertEqual(t["last_pushed"]["title"], "✓ Ship the thing")
        self.assertEqual(t["last_pushed"]["status"], "Complete")

    def test_push_is_idempotent(self):
        t = task()
        m = base_manifest([t])
        t["draft_id"] = self.board.add("Ship the thing")
        first, _ = self.push(m)
        self.assertEqual(first, ["✓ Ship the thing"])      # the one-off retitle
        second, summary = self.push(m)
        self.assertEqual(second, [])
        self.assertIn("0 title/body edit(s)", summary)

    # -------------------------------------------------------------------- pull

    def test_pull_does_not_invent_a_human_edit_from_our_own_marker(self):
        """The trap: push renders ✓, pull reads it back. If the snapshot held the
        clean title (or the pull compared un-stripped), every completed task
        would come back stamped human_edited.title and freeze the board."""
        t = task()
        m = base_manifest([t])
        t["draft_id"] = self.board.add("Ship the thing")
        self.push(m)
        self.assertEqual(self.board.items[t["draft_id"]]["title"], "✓ Ship the thing")

        merged = self.pull(m)

        self.assertEqual(merged, [])
        self.assertNotIn("human_edited", t)
        self.assertEqual(t["title"], "Ship the thing")
        # and the next push still has nothing to say
        again, summary = self.push(m)
        self.assertEqual(again, [])
        self.assertIn("0 title/body edit(s)", summary)

    def test_pull_strips_the_marker_off_a_human_retitle(self):
        t = task()
        m = base_manifest([t])
        cid = self.board.add("Ship the thing")
        t["draft_id"] = cid
        self.push(m)

        self.board.set_title(cid, "✓ Ship the thing, revised")   # human edits the text
        merged = self.pull(m)

        self.assertEqual(len(merged), 1)
        # merged clean, stamped clean, so `conflicts()` compares like with like
        self.assertEqual(t["title"], "Ship the thing, revised")
        self.assertEqual(t["human_edited"]["title"]["value"], "Ship the thing, revised")
        self.assertEqual(t["human_edited"]["title"]["was"], "Ship the thing")
        self.assertEqual(ws.conflicts(t), [])
        # the snapshot keeps the raw board value, so the next push is a no-op
        self.assertEqual(t["last_pushed"]["title"], "✓ Ship the thing, revised")
        written, summary = self.push(m)
        self.assertEqual(written, [])
        self.assertIn("0 title/body edit(s)", summary)

    def test_human_deleting_the_marker_is_not_an_edit_and_is_restored(self):
        t = task()
        m = base_manifest([t])
        cid = self.board.add("Ship the thing")
        t["draft_id"] = cid
        self.push(m)

        self.board.set_title(cid, "Ship the thing")     # human removes the ✓
        self.assertEqual(self.pull(m), [])
        self.assertNotIn("human_edited", t)

        written, _ = self.push(m)                       # the tool puts it back
        self.assertEqual(written, ["✓ Ship the thing"])

    def test_status_pulled_to_complete_earns_the_marker_next_push(self):
        t = task(status="In progress")
        m = base_manifest([t])
        cid = self.board.add("Ship the thing")
        t["draft_id"] = cid
        self.push(m)
        self.assertEqual(self.board.items[cid]["title"], "Ship the thing")

        self.board.items[cid]["values"]["Status"] = "Complete"   # human drags the card
        merged = self.pull(m)

        self.assertEqual(len(merged), 1)
        self.assertEqual(t["status"], "Complete")
        self.assertNotIn("title", t.get("human_edited", {}))
        written, _ = self.push(m)
        self.assertEqual(written, ["✓ Ship the thing"])

    def test_downgrade_removes_the_marker(self):
        t = task()
        m = base_manifest([t])
        cid = self.board.add("Ship the thing")
        t["draft_id"] = cid
        self.push(m)
        self.assertEqual(self.board.items[cid]["title"], "✓ Ship the thing")

        t["status"] = "In progress"                     # `task set demo t1 wip`
        written, _ = self.push(m)

        self.assertEqual(written, ["Ship the thing"])
        self.assertEqual(self.board.items[cid]["title"], "Ship the thing")
        self.assertEqual(t["last_pushed"]["title"], "Ship the thing")
        self.assertEqual(self.pull(m), [])              # and it round-trips clean

    def test_new_task_is_created_with_the_marker(self):
        t = task(tid="t2", title="Already done when added")
        m = base_manifest([t])
        self.push(m)
        cid = t["draft_id"]
        self.assertEqual(self.board.items[cid]["title"], "✓ Already done when added")
        self.assertEqual(t["title"], "Already done when added")
        self.assertEqual(self.pull(m), [])


class BlockedCase(unittest.TestCase):
    """Blocked/Ready describes work still to do — never a finished task."""

    def test_blocked_state_is_blank_once_complete(self):
        done_dep = task("t3", status="Complete")
        open_dep = task("t3", status="New")
        done = task("t9", status="Complete", depends_on=["t3"])
        wip = task("t9", status="In progress", depends_on=["t3"])
        self.assertEqual(ws.blocked_state(done, {"t3": done_dep}), "")   # was Ready
        self.assertEqual(ws.blocked_state(done, {"t3": open_dep}), "")   # was Blocked
        self.assertEqual(ws.blocked_state(wip, {"t3": done_dep}), "Ready")
        self.assertEqual(ws.blocked_state(wip, {"t3": open_dep}), "Blocked")
        # no dependencies at all: unchanged, blank in every status
        self.assertEqual(ws.blocked_state(task("t1", status="New"), {}), "")


class BoardCase(BoardHarness):
    """Push-side behaviour beyond the marker."""

    def test_completing_a_task_clears_blocked_on_the_board(self):
        dep = task(tid="t1", title="Do the thing first", status="Complete")
        t = task(tid="t2", title="Then this", status="In progress",
                 depends_on=["t1"])
        m = base_manifest([dep, t])
        self.push(m)
        item = self.board.items[t["draft_id"]]
        self.assertEqual(item["values"]["Blocked"], "Ready")

        t["status"] = "Complete"
        _written, summary = self.push(m)

        self.assertNotIn("Blocked", item["values"])   # actively cleared, not left
        self.assertIn("1 cleared", summary)
        self.assertEqual(t["last_pushed"]["blocked"], "")
        # and it stays cleared — the next push has nothing to do
        _w, again = self.push(m)
        self.assertIn("0 cleared", again)

    def test_index_title_is_the_board_title_not_the_last_task_title(self):
        """Regression: `title` was rebound per task inside the push loop, so
        index.json's github_project.title (and the dashboard's board link text)
        ended up holding whatever the last task happened to be called."""
        m = base_manifest([task(tid="t1", title="Some unrelated task title")])
        self.push(m)
        index = json.loads((self.dir / "index.json").read_text())
        self.assertEqual(index["projects"][0]["github_project"]["title"], "feat/demo")


class JsonCase(BoardHarness):
    """--json prints exactly one object, with stable keys and no prose."""

    TASK_KEYS = {"id", "title", "status", "created", "group", "owner",
                 "depends_on", "blocked", "start", "target", "has_body",
                 "attachments", "human_edited", "draft_id"}

    def test_task_json_record_is_complete_and_null_filled(self):
        t = task(tid="t2", title="Wire it up", status="New", depends_on=["t1"],
                 group="Phase 1", owner="TechOps (Patricia)", body="read me",
                 attachments=[{"kind": "drawio", "path": "a.drawio", "note": "n"}],
                 start="2026-08-10", target="2026-08-14")
        dep = task(tid="t1", status="New")
        rec = ws.task_json(t, {"t1": dep, "t2": t})
        self.assertEqual(set(rec), self.TASK_KEYS)
        self.assertEqual(rec["blocked"], "Blocked")
        self.assertTrue(rec["has_body"])
        self.assertEqual(rec["attachments"], [{"kind": "drawio", "path": "a.drawio",
                                               "note": "n"}])
        # every optional key is present-but-null on a bare task, never missing
        bare = ws.task_json(task(tid="t1", status="New"), {})
        self.assertEqual(set(bare), self.TASK_KEYS)
        for key in ("group", "owner", "blocked", "start", "target", "draft_id"):
            self.assertIsNone(bare[key], key)

    def test_status_json_shape(self):
        tasks = [task(tid="t1", status="Complete"), task(tid="t2", status="New")]
        (self.dir / "demo.json").write_text(ws.dump(base_manifest(tasks)))
        out = io.StringIO()
        with redirect_stdout(out):
            ws.cmd_status(Namespace(name=None, verbose=False, json=True))
        data = json.loads(out.getvalue())
        p = data["projects"][0]
        self.assertEqual(p["name"], "demo")
        self.assertEqual(p["task_count"], 2)
        self.assertEqual(p["task_open"], 1)
        self.assertEqual(p["task_status"], {"Complete": 1, "New": 1})
        self.assertFalse(p["tracked_only"])
        self.assertEqual([t["id"] for t in p["tasks"]], ["t1", "t2"])

    def test_status_json_marks_a_never_synced_project(self):
        out = io.StringIO()
        with redirect_stdout(out):
            ws.cmd_status(Namespace(name=None, verbose=False, json=True))
        p = json.loads(out.getvalue())["projects"][0]
        self.assertTrue(p["tracked_only"])
        self.assertIsNone(p["synced"])

    def test_context_json_inside_and_outside_a_tracked_worktree(self):
        (self.dir / "demo.json").write_text(
            ws.dump(base_manifest([task(tid="t1", status="New")])))
        out = io.StringIO()
        with redirect_stdout(out):
            ws.cmd_context(Namespace(cwd="/tmp", json=True))
        self.assertEqual(json.loads(out.getvalue())["tracked"], False)

        out = io.StringIO()
        with redirect_stdout(out):
            ws.cmd_context(Namespace(cwd=WORKTREE + "/repo", json=True))
        data = json.loads(out.getvalue())
        self.assertTrue(data["tracked"] and data["synced"])
        self.assertEqual(data["project"], "demo")
        self.assertEqual([t["id"] for t in data["open_tasks"]], ["t1"])
        self.assertIn("propose, never overwrite", data["protocol"])

    def test_push_json_is_one_object_with_the_documented_counters(self):
        m = base_manifest([task(tid="t1", status="New")])
        _written, out = self.push(m, as_json=True)
        data = json.loads(out)            # one object, nothing else on stdout
        self.assertEqual(data["command"], "push")
        self.assertEqual(data["status"], "ok")
        self.assertEqual(data["project"], "demo")
        self.assertEqual(data["board_title"], "feat/demo")
        self.assertEqual(data["board_url"], PROJECT["url"])
        for key in ("added_tasks", "added_prs", "added_branches", "draft_edits",
                    "values_set", "values_cleared", "rows_reordered", "archived"):
            self.assertIsInstance(data[key], int, key)
        self.assertEqual(data["added_tasks"], 1)

    def test_pull_returns_records_not_prose(self):
        t = task(status="In progress")
        m = base_manifest([t])
        cid = self.board.add("Ship the thing")
        t["draft_id"] = cid
        self.push(m)
        self.board.items[cid]["values"]["Status"] = "Complete"

        merged = self.pull(m)

        self.assertEqual(len(merged), 1)
        rec = merged[0]
        self.assertEqual(rec["task"], "t1")
        self.assertEqual(rec["field"], "status")
        self.assertEqual(rec["board"], "Complete")
        self.assertEqual(rec["tool"], "In progress")
        self.assertIn("t1.status", ws.pull_line(rec))


class ExitCodeCase(BoardHarness):
    """0 ok / 1 error / 3 needs-a-human — audited, not assumed."""

    def conflicted(self):
        """A task the human moved to New on the board while the tool wants
        Complete."""
        t = task(status="Complete")
        t["human_edited"] = {"status": {"at": "2026-08-01T10:00:00Z",
                                        "value": "New", "was": "In progress"}}
        return t

    def test_push_over_a_human_edit_exits_3_not_1(self):
        m = base_manifest([self.conflicted()])
        err = io.StringIO()
        with self.assertRaises(SystemExit) as cm, redirect_stderr(err):
            self.push(m)
        self.assertEqual(cm.exception.code, ws.EXIT_HITL)
        self.assertEqual(ws.EXIT_HITL, 3)
        # the block an agent has to relay verbatim goes to stderr, always
        self.assertIn("HUMAN-EDITED ON THE BOARD", err.getvalue())
        self.assertIn("Do not choose for him", err.getvalue())

    def test_push_conflict_json_carries_the_resolution_commands(self):
        m = base_manifest([self.conflicted()])
        out, err = io.StringIO(), io.StringIO()
        with self.assertRaises(SystemExit) as cm, \
             redirect_stdout(out), redirect_stderr(err):
            ws.guard_human_edits(ENTRY, m, ack=False, dry_run=True, as_json=True)
        self.assertEqual(cm.exception.code, ws.EXIT_HITL)
        data = json.loads(out.getvalue())          # stdout stays parseable JSON
        self.assertEqual(data["status"], "needs_human")
        self.assertEqual(data["exit_code"], 3)
        rec = data["conflicts"][0]
        self.assertEqual(rec["task"], "t1")
        self.assertEqual(rec["field"], "status")
        self.assertEqual(rec["human_value"], "New")
        self.assertEqual(rec["tool_value"], "Complete")
        self.assertIn("--ack-human", rec["accept_command"])
        self.assertNotIn("--ack-human", rec["revert_command"])
        # the prose block still goes to stderr, so it can be relayed verbatim
        self.assertIn("HUMAN-EDITED ON THE BOARD", err.getvalue())

    def test_ack_human_lets_the_push_through_and_releases_the_field(self):
        m = base_manifest([self.conflicted()])
        written, _ = self.push(m, ack=True)
        self.assertEqual(written, [])          # created fresh, nothing to retitle
        # ack RELEASES: the stamp is gone, not turned into a one-value whitelist
        self.assertNotIn("human_edited", m["tasks"][0])

    def test_only_the_conflict_path_ever_exits_3(self):
        """Grep the source: every `sys.exit(3)` must be an EXIT_HITL, and every
        EXIT_HITL must be a conflict path. A stray 3 elsewhere would make the
        code meaningless to a calling agent."""
        src = Path(ws.__file__).read_text()
        self.assertNotIn("sys.exit(3)", src)      # always the named constant
        sites = [ln.strip() for ln in src.splitlines() if "sys.exit(EXIT_HITL)" in ln]
        self.assertEqual(len(sites), 3, sites)    # guard_human_edits, guarded, autosync

    def test_errors_exit_1(self):
        """sys.exit("message") is exit 1 — no error path may collide with 3."""
        script = Path(ws.__file__)
        for argv in (["task", "set", "nope", "t1", "done"],
                     ["task", "list", "nope"],
                     ["sync", "nope"],
                     ["scan", "/definitely/not/a/worktree"]):
            r = subprocess.run([sys.executable, str(script), *argv],
                               capture_output=True, text=True,
                               env={**os.environ,
                                    "DOTFILES_DIR": str(self.dir.parent)})
            self.assertIn(r.returncode, (1, 2), f"{argv} -> {r.returncode}")
            self.assertNotEqual(r.returncode, ws.EXIT_HITL, argv)


class PushPullsFirstCase(BoardHarness):
    """A bare `project push` must never destroy a fresh board edit.

    The field test that produced this class: a human set Status on the board,
    a bare push ran, and the edit was gone — 1 field value set, exit 0, no
    stamp, no warning. `sync` was safe only because it pulls first. The guard
    refuses on ALREADY-STAMPED fields, and a fresh edit has no stamp yet, so
    push had nothing to refuse. The fix is that push pulls first by default.
    """

    def pushed_task(self, status="In progress"):
        """A task already on the board, with a matching last_pushed snapshot."""
        t = task(status=status)
        m = base_manifest([t])
        t["draft_id"] = self.board.add("Ship the thing")
        self.push(m)
        return t, m

    def test_bare_push_does_not_revert_a_fresh_board_edit(self):
        t, m = self.pushed_task()
        cid = t["draft_id"]
        self.board.items[cid]["values"]["Status"] = "Complete"   # human, on github.com

        _written, summary = self.push(m)                          # a bare push

        self.assertEqual(self.board.items[cid]["values"]["Status"], "Complete")
        self.assertEqual(t["status"], "Complete")                 # merged, not reverted
        self.assertEqual(t["human_edited"]["status"]["value"], "Complete")
        self.assertIn("HUMAN: t1.status", summary)                # and it says so
        # the manifest on disk carries the merge, so the next run agrees
        on_disk = json.loads((self.dir / "demo.json").read_text())
        self.assertEqual(on_disk["tasks"][0]["status"], "Complete")

    def test_no_pull_is_the_documented_unsafe_opt_out(self):
        """--no-pull is exactly the old behaviour, kept for the caller that has
        just pulled. It reverts — which is why it is not the default."""
        t, m = self.pushed_task()
        cid = t["draft_id"]
        self.board.items[cid]["values"]["Status"] = "Complete"

        self.push(m, pull=False)

        self.assertEqual(self.board.items[cid]["values"]["Status"], "In progress")
        self.assertNotIn("human_edited", t)

    def test_dry_run_push_pulls_but_writes_nothing(self):
        t, m = self.pushed_task()
        self.board.items[t["draft_id"]]["values"]["Status"] = "Complete"
        before = (self.dir / "demo.json").read_text()

        self.push(m, dry_run=True)

        self.assertEqual((self.dir / "demo.json").read_text(), before)

    def test_push_json_reports_what_the_pull_merged(self):
        t, m = self.pushed_task()
        self.board.items[t["draft_id"]]["values"]["Status"] = "Complete"
        _written, out = self.push(m, as_json=True)
        data = json.loads(out)
        self.assertEqual(len(data["merged_from_board"]), 1)
        self.assertEqual(data["merged_from_board"][0]["field"], "status")

    def test_project_push_help_documents_no_pull(self):
        r = subprocess.run([sys.executable, str(Path(ws.__file__)), "project", "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("--no-pull", r.stdout)
        self.assertIn("pull first", r.stdout)


class AckReleaseCase(BoardHarness):
    """--ack-human RELEASES the guard on a field; it does not ratchet it.

    The old ack whitelisted only the value it acked, so the next write of a
    different value exited 3 again quoting the same original board value —
    a field slowly became uneditable without the one flag the skill says never
    to pass on your own judgement.
    """

    def edited_on_the_board(self, board_value="New"):
        """A task the human moved on the board, pulled and stamped."""
        t = task(status="In progress")
        m = base_manifest([t])
        t["draft_id"] = self.board.add("Ship the thing")
        self.push(m)
        self.board.items[t["draft_id"]]["values"]["Status"] = board_value
        self.pull(m, dry_run=False)
        self.assertEqual(t["human_edited"]["status"]["value"], board_value)
        return t, m

    def task_cmd(self, action, *rest, **kw):
        args = Namespace(action=action, name="demo", rest=list(rest), json=False,
                         status="new", group=None, owner=None, note=None, kind=None,
                         file=None, text=None, start_from=None, days=5,
                         overwrite=False, ack_human=kw.get("ack", False),
                         push=False)
        out = io.StringIO()
        with redirect_stdout(out):
            ws.cmd_task(args)
        return out.getvalue()

    def test_ack_then_a_different_value_needs_no_second_ack(self):
        t, _m = self.edited_on_the_board()
        self.task_cmd("set", "t1", "wip", ack=True)          # owner said: go ahead
        reloaded = json.loads((self.dir / "demo.json").read_text())["tasks"][0]
        self.assertNotIn("human_edited", reloaded)
        # a LATER, different value — the ratchet case — now just works
        self.task_cmd("set", "t1", "done")
        reloaded = json.loads((self.dir / "demo.json").read_text())["tasks"][0]
        self.assertEqual(reloaded["status"], "Complete")
        self.assertNotIn("human_edited", reloaded)

    def test_without_ack_it_still_exits_3(self):
        self.edited_on_the_board()
        err = io.StringIO()
        with self.assertRaises(SystemExit) as cm, redirect_stderr(err):
            self.task_cmd("set", "t1", "done")
        self.assertEqual(cm.exception.code, ws.EXIT_HITL)
        self.assertIn("HUMAN-EDITED ON THE BOARD", err.getvalue())

    def test_a_new_human_edit_re_arms_the_released_guard(self):
        t, m = self.edited_on_the_board()
        ws.ack_human(t)
        self.assertNotIn("human_edited", t)
        self.push(m, pull=False)                    # re-snapshot at the tool's value
        self.board.items[t["draft_id"]]["values"]["Status"] = "Complete"  # human again
        self.pull(m, dry_run=False)

        self.assertEqual(t["human_edited"]["status"]["value"], "Complete")
        t["status"] = "New"                         # the tool wants something else
        self.assertEqual([r[0] for r in ws.conflicts(t)], ["status"])

    def test_ack_human_returns_the_fields_it_released(self):
        t = task()
        t["human_edited"] = {"status": {"at": "x", "value": "New", "was": "Complete"},
                             "owner": {"at": "x", "value": "P", "was": ""}}
        self.assertEqual(ws.ack_human(t, ["owner"]), ["owner"])
        self.assertEqual(sorted(t["human_edited"]), ["status"])
        self.assertEqual(ws.ack_human(t), ["status"])
        self.assertNotIn("human_edited", t)

    def test_a_legacy_acked_stamp_no_longer_ratchets(self):
        """Manifests written before this change carry acked_value/acked_at. Such
        a stamp is a RELEASED one and must not block a different value."""
        t = task(status="Complete")
        t["human_edited"] = {"status": {"at": "2026-08-01T10:00:00Z", "value": "New",
                                        "was": "In progress",
                                        "acked_value": "In progress",
                                        "acked_at": "2026-08-01T11:00:00Z"}}
        self.assertEqual(ws.conflicts(t), [])
        self.assertFalse(ws.stamp_blocks(t["human_edited"]["status"], "Complete"))


class CommitCase(unittest.TestCase):
    """`commit` must name the branch it actually pushed.

    It used to print "pushed to origin/main" whatever the target was. An agent
    relays that verbatim, and a false claim of a push to main is the single most
    dangerous sentence this tool can produce.
    """

    def git(self, *args, cwd=None):
        subprocess.run(["git", "-C", str(cwd or self.repo), *args], check=True,
                       capture_output=True, text=True)

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name)
        self.remote, self.repo = root / "remote.git", root / "dotfiles"
        subprocess.run(["git", "init", "--bare", "-q", str(self.remote)], check=True)
        subprocess.run(["git", "init", "-q", "-b", "main", str(self.repo)], check=True)
        self.git("config", "user.email", "t@example.com")
        self.git("config", "user.name", "T")
        # The Codespace installs a global core.hooksPath whose pre-commit refuses
        # commits on main outside a known repo. This throwaway repo is not it.
        self.git("config", "core.hooksPath", str(self.repo / ".no-hooks"))
        self.git("remote", "add", "origin", str(self.remote))
        (self.repo / "projects").mkdir()
        (self.repo / "projects" / "seed.json").write_text("{}\n")
        self.git("add", "-A")
        self.git("commit", "-qm", "seed")
        self.git("push", "-q", "origin", "main")
        p = mock.patch.object(ws, "dotfiles_dir", lambda: self.repo)
        p.start()
        self.addCleanup(p.stop)

    def commit(self, message="chore(projects): test"):
        out = io.StringIO()
        with redirect_stdout(out):
            ws.do_commit(message)
        return out.getvalue()

    def test_it_names_the_feature_branch_it_pushed(self):
        self.git("checkout", "-qb", "feat/task-groups-deps")
        (self.repo / "projects" / "seed.json").write_text('{"a": 1}\n')

        out = self.commit()

        self.assertIn("pushed to origin/feat/task-groups-deps", out)
        self.assertNotIn("origin/main", out)
        # and the push really went to that branch, not to main
        refs = subprocess.run(["git", "-C", str(self.remote), "for-each-ref",
                               "--format=%(refname:short)"],
                              capture_output=True, text=True, check=True).stdout.split()
        self.assertIn("feat/task-groups-deps", refs)

    def test_on_main_it_still_says_main(self):
        (self.repo / "projects" / "seed.json").write_text('{"a": 2}\n')
        self.assertIn("pushed to origin/main", self.commit())

    def test_nothing_to_commit_is_quiet_and_pushes_nothing(self):
        self.assertIn("nothing to commit", self.commit())


SCRIPTS = Path(__file__).resolve().parent

# A stand-in for worktree_sync.py, so a test can drive a REAL detached worker
# without touching a real manifest or the network. It records the step it was
# asked to run, can be made slow, and can be made to fail with any exit code.
FAKE_TOOL = '''#!/usr/bin/env python3
import os, sys, time
step = sys.argv[1]
with open(os.environ["FAKE_MARK"], "a") as fh:
    fh.write(step + "\\n")
time.sleep(float(os.environ.get("FAKE_SLEEP", "0")))
rc = int(os.environ.get("FAKE_RC_" + step.replace("-", "_").upper(), "0"))
if rc == 3:
    print("HUMAN-EDITED ON THE BOARD — needs a decision, not a retry",
          file=sys.stderr)
sys.exit(rc)
'''


class HookHarness(unittest.TestCase):
    """A throwaway $DOTFILES_DIR with one tracked worktree, for the hook scripts.

    The hooks are run as real subprocesses — that is the only way to measure
    what they actually cost and to prove the flush is genuinely detached.
    """

    def setUp(self):
        self.tmp = TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.wt = self.root / "wt" / "feat" / "demo"
        (self.wt / "repo").mkdir(parents=True)
        (self.root / "projects").mkdir()
        (self.root / "projects" / "index.json").write_text(json.dumps(
            {"projects": [{"name": "demo", "worktree": str(self.wt),
                           "lane": "feat", "status": "active",
                           "github_project": None}]}))
        self.queue = self.root / "projects" / ".queue"
        self.fake = self.root / "fake_tool.py"
        self.fake.write_text(FAKE_TOOL)
        self.mark = self.root / "steps.txt"

    def env(self, **extra):
        # WT_SYNC_HOME, not DOTFILES_DIR: the hooks resolve their repo from
        # their own path on purpose, and this is the one override that exists.
        return {**os.environ, "WT_SYNC_HOME": str(self.root),
                "WT_SYNC_TOOL": str(self.fake), "FAKE_MARK": str(self.mark),
                **{k: str(v) for k, v in extra.items()}}

    def run_hook(self, script, payload, *args, **env):
        started = time.time()
        r = subprocess.run([sys.executable, str(SCRIPTS / script), *args],
                           input=json.dumps(payload), capture_output=True,
                           text=True, env=self.env(**env))
        return r, time.time() - started

    def payload(self, command=None, cwd=None):
        p = {"cwd": cwd or str(self.wt / "repo"), "hook_event_name": "PostToolUse"}
        if command is not None:
            p["tool_name"] = "Bash"
            p["tool_input"] = {"command": command}
        return p

    def queue_lines(self):
        path = self.queue / "demo.jsonl"
        if not path.exists():
            return []
        return [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]

    def steps(self):
        return self.mark.read_text().split() if self.mark.exists() else []

    def wait_for(self, predicate, seconds=20):
        deadline = time.time() + seconds
        while time.time() < deadline:
            if predicate():
                return True
            time.sleep(0.05)
        return False


class DetectorCase(HookHarness):
    """PostToolUse[Bash]: notice, queue one line, cost nothing."""

    def test_it_queues_the_commands_that_move_the_board(self):
        wanted = (("gh pr create --fill", "prs-changed"),
                  ("gh pr merge 12 --squash", "prs-changed"),
                  ("gh pr close 12", "prs-changed"),
                  ("gh pr ready 12", "prs-changed"),
                  ("gh pr edit 12 --add-label x", "prs-changed"),
                  ("git push -u origin feat/x", "prs-changed"),
                  ("git -C /workspaces/repo push", "prs-changed"),
                  ("cd /tmp && git push --force-with-lease", "prs-changed"),
                  # both idioms an agent actually types for the tool
                  ("python3 $S task set demo t7 done --push", "tasks-changed"),
                  ("python3 skills/worktree-sync/scripts/worktree_sync.py "
                   "task add demo 'Title'", "tasks-changed"))
        for n, (command, kind) in enumerate(wanted, start=1):
            r, _ = self.run_hook("hook_detect.py", self.payload(command))
            self.assertEqual(r.returncode, 0, command)
            lines = self.queue_lines()
            self.assertEqual(len(lines), n, f"{command!r} queued nothing")
            self.assertEqual(lines[-1]["kind"], kind, command)
            self.assertEqual(lines[-1]["cmd"], command)

    def test_it_ignores_everything_else(self):
        for command in ("ls -la", "gh pr view 12", "gh pr list",
                        "git status", "git log --oneline -5",
                        "python3 $S status --json"):
            self.run_hook("hook_detect.py", self.payload(command))
        self.assertEqual(self.queue_lines(), [])

    def test_outside_a_tracked_worktree_it_does_nothing_and_returns_fast(self):
        r, elapsed = self.run_hook(
            "hook_detect.py", self.payload("gh pr create", cwd="/tmp"))
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertFalse(self.queue.exists())
        self.assertLess(elapsed, 0.5, f"gate took {elapsed * 1000:.0f} ms")

    def test_the_loop_guard_stops_the_flushers_own_commands(self):
        r, _ = self.run_hook("hook_detect.py",
                             self.payload("python3 $S task set demo t7 done"),
                             WT_SYNC_INTERNAL="1")
        self.assertEqual(r.returncode, 0)
        self.assertEqual(self.queue_lines(), [])

    def test_a_junk_payload_never_fails_a_tool_call(self):
        for raw in ("", "not json", "[]", '{"tool_input": null}'):
            r = subprocess.run([sys.executable, str(SCRIPTS / "hook_detect.py")],
                               input=raw, capture_output=True, text=True,
                               env=self.env())
            self.assertEqual(r.returncode, 0, raw)
        self.assertEqual(self.queue_lines(), [])

    def test_concurrent_appends_all_survive_and_stay_parseable(self):
        """Two sessions in the same worktree write the same queue file. Every
        line must still parse — a torn line would poison the whole queue."""
        payload = json.dumps(self.payload("gh pr create --fill"))
        procs = [subprocess.Popen(
            [sys.executable, str(SCRIPTS / "hook_detect.py")],
            stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, text=True, env=self.env())
            for _ in range(24)]
        for p in procs:
            p.communicate(payload)
        self.assertEqual([p.returncode for p in procs], [0] * 24)
        lines = self.queue_lines()                       # parses, or it raises
        self.assertEqual(len(lines), 24)
        self.assertTrue(all(ln["kind"] == "prs-changed" for ln in lines))

    def test_it_stays_under_the_50ms_budget(self):
        """Measured, not assumed. The assertion is loose enough for a loaded
        box; the number it prints is the one that matters."""
        self.run_hook("hook_detect.py", self.payload("ls"))     # warm __pycache__
        runs = 10
        started = time.time()
        for _ in range(runs):
            self.run_hook("hook_detect.py", self.payload("gh pr create --fill"))
        each = (time.time() - started) / runs
        print(f"\n    [detector] {each * 1000:.1f} ms per Bash tool call")
        self.assertLess(each, 0.25, f"{each * 1000:.0f} ms per call")


class FlusherCase(HookHarness):
    """Stop hook: decide, detach, return. The turn never waits on the board."""

    def enqueue(self, n=1):
        self.queue.mkdir(parents=True, exist_ok=True)
        with open(self.queue / "demo.jsonl", "a") as fh:
            for _ in range(n):
                fh.write(json.dumps({"at": "2026-08-02T10:00:00Z",
                                     "kind": "prs-changed", "cmd": "gh pr create"})
                         + "\n")

    def stop(self, *args, **env):
        return self.run_hook("hook_flush.py",
                             {"cwd": str(self.wt / "repo"),
                              "hook_event_name": "Stop"}, *args, **env)

    def test_an_empty_queue_and_a_fresh_flush_do_nothing(self):
        self.queue.mkdir(parents=True)
        (self.queue / "demo.last-flush").touch()
        r, elapsed = self.stop()
        self.assertEqual((r.returncode, r.stdout), (0, ""))
        self.assertEqual(self.steps(), [])
        self.assertLess(elapsed, 0.5)

    def test_a_stale_project_flushes_even_with_an_empty_queue(self):
        self.queue.mkdir(parents=True)
        old = time.time() - 3600
        stamp = self.queue / "demo.last-flush"
        stamp.touch()
        os.utime(stamp, (old, old))
        self.stop()
        self.assertTrue(self.wait_for(lambda: self.steps() == ["sync", "project"]))

    def test_outside_a_tracked_worktree_it_returns_instantly(self):
        r, elapsed = self.run_hook("hook_flush.py",
                                   {"cwd": "/tmp", "hook_event_name": "Stop"})
        self.assertEqual((r.returncode, r.stdout, r.stderr), (0, "", ""))
        self.assertLess(elapsed, 0.5, f"gate took {elapsed * 1000:.0f} ms")

    def test_the_hook_returns_while_the_work_is_still_running(self):
        """The whole point. The flush sleeps for seconds; the hook must be back
        in milliseconds, and the work must finish afterwards, unattended."""
        self.enqueue()
        _r, elapsed = self.stop(FAKE_SLEEP="3")
        print(f"\n    [Stop hook] {elapsed * 1000:.0f} ms to detach a flush "
              f"that then ran for ~6 s")
        self.assertLess(elapsed, 0.6, f"Stop hook blocked for {elapsed:.2f}s")
        self.assertLess(len(self.steps()), 2)            # still running
        self.assertTrue(self.wait_for(lambda: self.steps() == ["sync", "project"]),
                        "the detached worker never finished")
        self.assertTrue(self.wait_for(lambda: self.queue_lines() == []),
                        "the queue was not drained after a clean run")

    def test_the_worker_survives_its_parent(self):
        """setsid/start_new_session: the worker is in its own session, so it is
        not killed when the session that started it goes away."""
        self.enqueue()
        self.stop(FAKE_SLEEP="2")
        self.assertTrue(self.wait_for(lambda: self.steps()[:1] == ["sync"]))
        pids = subprocess.run(["pgrep", "-f", "hook_flush.py --run demo"],
                              capture_output=True, text=True).stdout.split()
        self.assertTrue(pids, "no detached worker process found")
        sid = subprocess.run(["ps", "-o", "sess=", "-p", pids[0]],
                             capture_output=True, text=True).stdout.strip()
        self.assertEqual(sid, pids[0], "worker is not a session leader")
        self.assertTrue(self.wait_for(lambda: self.steps() == ["sync", "project"]))

    def test_a_failed_run_keeps_the_queue_for_the_next_turn(self):
        self.enqueue(3)
        self.stop(FAKE_RC_SYNC="1")
        self.assertTrue(self.wait_for(lambda: self.steps() == ["sync"]))
        time.sleep(0.3)
        self.assertEqual(self.steps(), ["sync"])         # push never ran
        self.assertEqual(len(self.queue_lines()), 3)     # nothing dropped
        self.assertIn("queue kept", (self.queue / "flush.log").read_text())

    def test_exit_3_parks_the_conflict_and_stops(self):
        self.enqueue()
        self.stop(FAKE_RC_PROJECT="3")
        self.assertTrue(self.wait_for(
            lambda: (self.queue / "demo.conflict").exists()))
        text = (self.queue / "demo.conflict").read_text()
        self.assertIn("HUMAN-EDITED ON THE BOARD", text)
        self.assertIn("Do not pass --ack-human", text)
        self.assertEqual(len(self.queue_lines()), 1)     # retried next turn
        log = (self.queue / "flush.log").read_text()
        self.assertIn("NEEDS-HUMAN", log)
        self.assertNotIn("--ack-human", log.split("Do not")[0])

    def test_session_start_surfaces_a_parked_conflict_once(self):
        self.queue.mkdir(parents=True)
        (self.queue / "demo.conflict").write_text("HUMAN-EDITED ON THE BOARD — t1\n")
        (self.queue / "demo.last-flush").touch()
        r, _ = self.run_hook("hook_flush.py",
                             {"cwd": str(self.wt), "hook_event_name": "SessionStart"},
                             "--session-start")
        self.assertIn("HUMAN-EDITED ON THE BOARD", r.stdout)
        self.assertFalse((self.queue / "demo.conflict").exists())
        # and a second session start does not repeat a block nobody resolved
        r2, _ = self.run_hook("hook_flush.py",
                              {"cwd": str(self.wt), "hook_event_name": "SessionStart"},
                              "--session-start")
        self.assertEqual(r2.stdout, "")

    def test_session_start_drains_a_queue_a_killed_session_left_behind(self):
        self.enqueue(2)
        (self.queue / "demo.last-flush").touch()         # not stale, only queued
        self.run_hook("hook_flush.py",
                      {"cwd": str(self.wt), "hook_event_name": "SessionStart"},
                      "--session-start")
        self.assertTrue(self.wait_for(lambda: self.steps() == ["sync", "project"]))
        self.assertTrue(self.wait_for(lambda: self.queue_lines() == []))

    def test_the_loop_guard_stops_a_flush_inside_a_flush(self):
        self.enqueue()
        r, _ = self.stop(WT_SYNC_INTERNAL="1")
        self.assertEqual(r.returncode, 0)
        time.sleep(0.3)
        self.assertEqual(self.steps(), [])

    def test_a_second_worker_skips_while_the_first_holds_the_lock(self):
        """Two sessions in different worktrees hit this for real. The loser must
        exit without doing the work and without queueing more of it."""
        self.enqueue()
        first = subprocess.Popen(
            [sys.executable, str(SCRIPTS / "hook_flush.py"), "--run", "demo",
             "--reason", "test"], env=self.env(FAKE_SLEEP="2"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.addCleanup(first.wait)
        self.assertTrue(self.wait_for(lambda: self.steps()[:1] == ["sync"]))
        second = subprocess.run(
            [sys.executable, str(SCRIPTS / "hook_flush.py"), "--run", "demo",
             "--reason", "test2"], env=self.env(), capture_output=True, text=True)
        self.assertEqual(second.returncode, 0)
        self.assertIn("skip=lock-held", (self.queue / "flush.log").read_text())
        self.assertEqual(self.steps(), ["sync"])         # the loser ran nothing
        first.wait(timeout=30)
        self.assertEqual(self.steps(), ["sync", "project"])

    def test_only_the_consumed_prefix_of_the_queue_is_dropped(self):
        """A hint queued while the flush was running must survive it."""
        self.enqueue(2)
        self.stop(FAKE_SLEEP="1.5")
        self.assertTrue(self.wait_for(lambda: self.steps()[:1] == ["sync"]))
        self.enqueue(1)                                  # arrives mid-flush
        self.assertTrue(self.wait_for(lambda: self.steps() == ["sync", "project"]))
        self.assertTrue(self.wait_for(lambda: len(self.queue_lines()) == 1))

    def test_status_reports_the_queue_without_changing_anything(self):
        self.enqueue(2)
        r = subprocess.run([sys.executable, str(SCRIPTS / "hook_flush.py"),
                            "--status"], capture_output=True, text=True,
                           cwd=str(self.wt / "repo"), env=self.env())
        self.assertIn("project        : demo", r.stdout)
        self.assertIn("flush due      : queued", r.stdout)
        self.assertEqual(len(self.queue_lines()), 2)
        self.assertEqual(self.steps(), [])


class SelfLocatingCase(unittest.TestCase):
    """The tree must work from whatever checkout it was copied into.

    This machinery has already been copied between two dotfiles checkouts, and
    a stale `DOTFILES_DIR` pointing at the retired one is exactly how a hook in
    one repo ends up writing the other repo's `projects/`.
    """

    FILES = ("worktree_sync.py", "hook_common.py", "hook_detect.py",
             "hook_flush.py")

    def test_no_absolute_repo_path_is_baked_into_any_script(self):
        for name in self.FILES:
            src = (SCRIPTS / name).read_text()
            for token in ("/workspaces/my-dotfiles", "/workspaces/kas-dotfiles"):
                self.assertNotIn(token, src, f"{name} hardcodes {token}")

    def test_worktree_sync_defaults_to_the_repo_it_lives_in(self):
        env = {k: v for k, v in os.environ.items() if k != "DOTFILES_DIR"}
        r = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, sys.argv[1]);"
             "import worktree_sync as ws; print(ws.dotfiles_dir())",
             str(SCRIPTS)], capture_output=True, text=True, env=env)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), str(SCRIPTS.parents[2]))

    def test_a_copied_hook_ignores_a_stale_DOTFILES_DIR(self):
        with TemporaryDirectory() as tmp:
            home = Path(tmp) / "other-dotfiles"
            dest = home / "skills" / "worktree-sync" / "scripts"
            dest.mkdir(parents=True)
            for name in ("hook_common.py", "hook_detect.py"):
                (dest / name).write_text((SCRIPTS / name).read_text())
            wt = home / "wt" / "feat" / "demo"
            wt.mkdir(parents=True)
            (home / "projects").mkdir()
            (home / "projects" / "index.json").write_text(json.dumps(
                {"projects": [{"name": "demo", "worktree": str(wt)}]}))

            r = subprocess.run(
                [sys.executable, str(dest / "hook_detect.py")],
                input=json.dumps({"cwd": str(wt), "tool_name": "Bash",
                                  "tool_input": {"command": "gh pr create"}}),
                capture_output=True, text=True,
                env={**os.environ, "DOTFILES_DIR": "/definitely/not/here"})

            self.assertEqual(r.returncode, 0, r.stderr)
            queued = home / "projects" / ".queue" / "demo.jsonl"
            self.assertTrue(queued.exists(), "the copy wrote outside its own repo")
            self.assertEqual(json.loads(queued.read_text())["kind"], "prs-changed")


class HelpCase(unittest.TestCase):
    """--help alone has to be enough to get the command right."""

    def run_help(self, *argv):
        r = subprocess.run([sys.executable, str(Path(ws.__file__)), *argv, "--help"],
                           capture_output=True, text=True)
        self.assertEqual(r.returncode, 0, r.stderr)
        return r.stdout

    def test_top_level_help_states_the_argument_order_and_exit_codes(self):
        out = self.run_help()
        self.assertIn("task set <project> t7 done", out)
        self.assertIn("task <project> set t7 done      WRONG", out)
        self.assertIn("3  a human edited that field", out)

    def test_task_help_lists_every_action_with_its_arguments(self):
        out = self.run_help("task")
        self.assertIn("task <action> <project>", out)
        for action in ("add", "set", "list", "dep", "dates", "body", "attach",
                       "detach", "schedule"):
            self.assertIn(f"  task {action}", out, action)
        self.assertIn("--ack-human", out)

    def test_project_help_states_the_order_and_the_scope_command(self):
        out = self.run_help("project")
        self.assertIn("project <push|pull> <project>", out)
        self.assertIn("gh auth refresh", out)


if __name__ == "__main__":
    unittest.main(verbosity=2)
