"""Blocked for the right reason, then told the wrong one.

`unedit back` refuses to write outside the project, correctly, in two quite
different situations:

  1. the manifest names a path that climbs out — `../../.ssh/authorized_keys`.
     The snapshot is lying.  A store is a directory in the working tree; it gets
     committed and cloned, so this is reachable input.

  2. the manifest names an ordinary path, and something on disk now redirects
     it — `notes.txt` was replaced by a symlink to `/etc/passwd` since the
     snapshot was taken.  The snapshot is innocent.

Both got:

    unedit: snapshot names 1 path(s) outside the project and was not applied:
      notes.txt
    a snapshot only ever restores files under /home/user/proj

In case 2 that is wrong about the cause and wrong about the fix.  The snapshot
does not name anything outside the project — `notes.txt` is as ordinary as a
path gets — so a person reads that, goes and inspects the snapshot, finds
nothing wrong with it, and is left with a tool refusing to restore for a reason
that is not true.  The thing to look at is the working tree, and the fix is to
remove the symlink someone put in the way.

The refusal itself does not move: nothing is written in either case, exit 2,
whole restore abandoned rather than half-applied.  Only the sentence changes,
and it is the sentence a person reads at the one moment the tool is telling
them something dangerous was stopped.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from unedit import store


class _Restorable(unittest.TestCase):
    """A project with one snapshot in it, ready to be interfered with."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="unedit_escape_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.outside = tempfile.mkdtemp(prefix="unedit_outside_")
        self.addCleanup(shutil.rmtree, self.outside, ignore_errors=True)
        self.target = os.path.join(self.outside, "target.txt")
        with open(self.target, "w") as fh:
            fh.write("DO NOT TOUCH\n")
        with open(os.path.join(self.root, "notes.txt"), "w") as fh:
            fh.write("original\n")
        self.snap_id = store.save(self.root, message="base")["id"]

    def manifest_path(self):
        return os.path.join(store._snapshots_dir(store._store_dir(self.root)),
                            self.snap_id + ".json")

    def rewrite_manifest_path(self, new_rel):
        """Make the snapshot itself name somewhere else — situation 1."""
        path = self.manifest_path()
        with open(path) as fh:
            manifest = json.load(fh)
        manifest["files"][0]["path"] = new_rel
        with open(path, "w") as fh:
            json.dump(manifest, fh)

    def put_a_symlink_in_the_way(self):
        """Leave the snapshot alone and redirect the path on disk — situation 2."""
        victim = os.path.join(self.root, "notes.txt")
        os.remove(victim)
        os.symlink(self.target, victim)

    def back(self):
        p = subprocess.run(
            [sys.executable, "-m", "unedit", "--dir", self.root, "back", "-y"],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT))
        return p.returncode, p.stdout + p.stderr


class TestASymlinkOnDiskIsNotTheSnapshotsFault(_Restorable):

    def test_it_does_not_accuse_the_snapshot(self):
        self.put_a_symlink_in_the_way()
        rc, out = self.back()
        self.assertEqual(rc, 2, out)
        self.assertNotIn("snapshot names", out,
                         "the snapshot names `notes.txt`, which is inside the "
                         "project; the working tree is what redirects it:\n" + out)

    def test_it_says_a_link_is_in_the_way(self):
        self.put_a_symlink_in_the_way()
        rc, out = self.back()
        self.assertEqual(rc, 2, out)
        self.assertIn("symlink", out.lower(), out)

    def test_it_names_the_path_and_where_it_now_leads(self):
        # Both halves, because either alone leaves you searching: the path
        # says which file to look at, the target says why it was refused.
        self.put_a_symlink_in_the_way()
        rc, out = self.back()
        self.assertIn("notes.txt", out, out)
        self.assertIn(self.target, out,
                      "the message does not say where the link leads:\n" + out)

    def test_the_refusal_itself_is_unchanged(self):
        self.put_a_symlink_in_the_way()
        rc, out = self.back()
        self.assertEqual(rc, 2, out)
        with open(self.target) as fh:
            self.assertEqual(fh.read(), "DO NOT TOUCH\n",
                             "the restore wrote through the symlink")
        self.assertTrue(os.path.islink(os.path.join(self.root, "notes.txt")),
                        "something was written in a run that refused to write")

    def test_no_safety_snapshot_is_taken_for_a_restore_that_never_ran(self):
        # Checked before anything is touched, so the store is as it was.
        before = len(store.list_snapshots(store._store_dir(self.root)))
        self.put_a_symlink_in_the_way()
        self.back()
        after = len(store.list_snapshots(store._store_dir(self.root)))
        self.assertEqual(before, after,
                         "a refused restore left a snapshot behind")


class TestAManifestThatClimbsOutStillSaysSo(_Restorable):
    """Situation 1 keeps the message it always had — the snapshot is lying."""

    def test_a_climbing_path_still_accuses_the_snapshot(self):
        self.rewrite_manifest_path("../../escaped.txt")
        rc, out = self.back()
        self.assertEqual(rc, 2, out)
        self.assertIn("snapshot names", out, out)
        self.assertIn("../../escaped.txt", out, out)

    def test_an_absolute_path_still_accuses_the_snapshot(self):
        # `os.path.join` discards the root entirely for one of these, which is
        # the quiet way out and the reason the check is not textual.
        self.rewrite_manifest_path(os.path.join(self.outside, "escaped.txt"))
        rc, out = self.back()
        self.assertEqual(rc, 2, out)
        self.assertIn("snapshot names", out, out)

    def test_nothing_is_written_for_a_climbing_path_either(self):
        self.rewrite_manifest_path("../../escaped.txt")
        self.back()
        self.assertFalse(
            os.path.exists(os.path.join(os.path.dirname(os.path.dirname(
                self.root)), "escaped.txt")),
            "a path that climbed out was restored anyway")


class TestBothAtOnce(_Restorable):
    """One of each. Neither may be described as the other."""

    def setUp(self):
        super().setUp()
        with open(os.path.join(self.root, "second.txt"), "w") as fh:
            fh.write("second\n")
        self.snap_id = store.save(self.root, message="two files")["id"]

    def test_each_is_reported_as_what_it_is(self):
        path = self.manifest_path()
        with open(path) as fh:
            manifest = json.load(fh)
        by_path = {f["path"]: f for f in manifest["files"]}
        by_path["second.txt"]["path"] = "../../escaped.txt"
        with open(path, "w") as fh:
            json.dump(manifest, fh)
        self.put_a_symlink_in_the_way()

        rc, out = self.back()
        self.assertEqual(rc, 2, out)
        self.assertIn("../../escaped.txt", out, out)
        self.assertIn("notes.txt", out, out)
        self.assertIn("symlink", out.lower(), out)
        self.assertIn("snapshot names", out, out)


class TestNothingElseMoves(_Restorable):

    def test_an_ordinary_restore_is_untouched(self):
        with open(os.path.join(self.root, "notes.txt"), "w") as fh:
            fh.write("edited\n")
        rc, out = self.back()
        self.assertEqual(rc, 0, out)
        with open(os.path.join(self.root, "notes.txt")) as fh:
            self.assertEqual(fh.read(), "original\n")

    def test_a_symlink_that_stays_inside_the_project_is_fine(self):
        # Only leaving the tree is refused.  A link to a sibling file is an
        # ordinary thing for a project to contain.
        inside = os.path.join(self.root, "sibling.txt")
        with open(inside, "w") as fh:
            fh.write("sibling\n")
        victim = os.path.join(self.root, "notes.txt")
        os.remove(victim)
        os.symlink(inside, victim)
        rc, out = self.back()
        self.assertEqual(rc, 0, out)


if __name__ == "__main__":
    unittest.main()
