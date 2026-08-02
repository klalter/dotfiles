#!/usr/bin/env python3
"""Offline tests for worktree_sync.py — no network, no real manifest touched.

    python3 skills/worktree-sync/scripts/test_worktree_sync.py

Focus: the DONE_MARKER round-trip. A task is a DRAFT issue, which has no
open/closed state, so a Complete task is rendered to the board as "✓ <title>".
That decoration must never reach the manifest, and it must never be mistaken for
a human board edit on the way back — the trap the pull test below exists for.

The board is faked at the seam the real code already has: ensure_project /
ensure_fields / ensure_views / list_items / apply_drafts / gql. Everything
between them — ordered_tasks, board_title, task_snapshot, the draft diff, the
whole of pull_project — is the real code under test.
"""
import io
import json
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
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


class MarkerCase(unittest.TestCase):
    """A tmp projects/ dir plus a fake board, wired for push and pull."""

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

    def push(self, manifest, dry_run=False):
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
            ws.push_project(ENTRY, manifest, dry_run=dry_run)
        return written, out.getvalue()

    def pull(self, manifest, dry_run=True):
        out = io.StringIO()
        with mock.patch.object(ws, "find_project", lambda *a, **k: dict(PROJECT)), \
             mock.patch.object(ws, "list_items", self.board.list_items), \
             redirect_stdout(out):
            merged = ws.pull_project(ENTRY, manifest, dry_run=dry_run)
        return merged

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


if __name__ == "__main__":
    unittest.main(verbosity=2)
