#!/usr/bin/env python3
"""Offline tests for worktree_sync.py — no network, no real manifest touched.

    python3 skills/worktree-sync/scripts/test_worktree_sync.py

Three things are locked down here:

1. The DONE_MARKER round-trip. A task is a DRAFT issue, which has no open/closed
   state, so a Complete task is rendered to the board as "✓ <title>". That
   decoration must never reach the manifest, and it must never be mistaken for a
   human board edit on the way back — the trap the pull tests exist for.
2. The machine surface agents call: the --json shapes, and the exit-code
   contract (0 ok / 1 error / 3 needs-a-human-decision, nothing else).
3. Blocked/Ready describing unfinished work only.

The board is faked at the seam the real code already has: ensure_project /
ensure_fields / ensure_views / list_items / apply_drafts / gql. Everything
between them — ordered_tasks, board_title, task_snapshot, the draft diff, the
whole of pull_project — is the real code under test.
"""
import io
import json
import subprocess
import sys
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

    def push(self, manifest, dry_run=False, as_json=False, ack=False):
        """The real push_project against the fake board. Returns the titles it
        wrote through updateProjectV2DraftIssue, and the printed summary."""
        written = []

        def apply_drafts(drafts, dry=False):
            written.extend(t for _cid, t, _b in drafts)
            return self.board.apply_drafts(drafts, dry)

        out = io.StringIO()
        with mock.patch.object(ws, "ensure_project", lambda *a, **k: dict(PROJECT)), \
             mock.patch.object(ws, "ensure_fields", lambda *a, **k: (FIELDS, [])), \
             mock.patch.object(ws, "ensure_views", lambda *a, **k: []), \
             mock.patch.object(ws, "list_items", self.board.list_items), \
             mock.patch.object(ws, "apply_drafts", apply_drafts), \
             mock.patch.object(ws, "apply_updates", self.board.apply_updates), \
             mock.patch.object(ws, "apply_clears", self.board.apply_clears), \
             mock.patch.object(ws, "gql", self._gql), \
             redirect_stdout(out):
            ws.push_project(ENTRY, manifest, dry_run=dry_run, ack=ack,
                            as_json=as_json)
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

    def test_ack_human_lets_the_push_through(self):
        m = base_manifest([self.conflicted()])
        written, _ = self.push(m, ack=True)
        self.assertEqual(written, [])          # created fresh, nothing to retitle
        self.assertEqual(m["tasks"][0]["human_edited"]["status"]["acked_value"],
                         "Complete")

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
                               env={**__import__("os").environ,
                                    "DOTFILES_DIR": str(self.dir.parent)})
            self.assertIn(r.returncode, (1, 2), f"{argv} -> {r.returncode}")
            self.assertNotEqual(r.returncode, ws.EXIT_HITL, argv)


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
