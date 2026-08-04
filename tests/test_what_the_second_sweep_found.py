"""The second mutation sweep over `unedit/store.py` — what it found in restore.

The first sweep covered saving and the containment checks.  This one ran over
the same file after `restore` had grown, and the survivors were almost all in
the same place: the part of a restore that happens *after* the files are back.
Six of them sat inside one block, the one that removes directories left empty
when new files are moved aside.  That block had no test at all.

What is pinned here:

  * **The directories a restore leaves behind.**  An agent that writes
    `notes/scratch.md` leaves a `notes/` directory that was not in the
    snapshot.  Moving the file aside without removing the directory means
    `unedit back` reports a tree restored to the snapshot and leaves a tree
    that is not it — empty directories change what `find`, a test runner, and
    the next `save` see.  The contract is: gone if the snapshot did not have
    it and nothing else is in it, kept otherwise.

  * **`aside_dir` is only named when something was moved there.**  It is in the
    returned summary and printed to the person running the restore.  A hard
    restore deletes rather than moves, and a restore with no new files moves
    nothing; naming a directory in either case points at a path that was never
    created.

  * **The failure warning only appears on a failure.**  `restored <
    len(to_restore)` off by one boundary prints `0 of 3 planned files could not
    be restored` after a restore in which everything came back.  On an undo
    button, a warning that fires when nothing is wrong is worse than none:
    it is the sentence people learn to skip.

  * **A symlink that still matches the snapshot is not restored again.**  The
    check is three conditions and the middle one was unpinned.  Wrong, it puts
    an unchanged symlink in the plan, so `unedit back` says it restored files
    it did not need to touch.

  * **Garbage collection removes the shard directories it empties.**  The
    object store is sharded two hex characters deep, so dropping every
    snapshot in a busy store leaves up to 256 empty directories behind unless
    the last step actually runs.

  * **A damaged snapshot is reported with the reason, not the traceback.**  The
    listing shows `Permission denied`, not `[Errno 13] Permission denied:
    '/long/path/....json'` — the path is already the first thing on the line.

Four survivors in that cleanup block are equivalent mutants and are left
alone; the reason they cannot be killed is written down at the bottom of this
file, because "no test kills it" and "no test *can* kill it" look the same in a
sweep log and only one of them is a gap.
"""

from __future__ import annotations

import io
import os
import shutil
import stat
import tempfile
import unittest

from unedit import store


def _write(path, text="x\n"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(text)
    return path


class _Project(unittest.TestCase):
    """A saved project to restore back to."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="unedit_sweep2_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.printed = []
        _write(os.path.join(self.root, "keep.txt"), "original\n")

    def path(self, *parts):
        return os.path.join(self.root, *parts)

    def save(self, message="before"):
        return store.save(self.root, message=message)

    def restore(self, snap_id=None, **kw):
        kw.setdefault("yes", True)
        return store.restore(self.root, snap_id, print_fn=self.printed.append, **kw)

    @property
    def output(self):
        return "\n".join(self.printed)


class TestTheDirectoriesARestoreLeavesBehind(_Project):

    def test_the_directory_a_new_file_lived_in_goes_with_the_file(self):
        self.save()
        _write(self.path("notes", "scratch.md"))
        self.restore()
        self.assertFalse(os.path.exists(self.path("notes")),
                         "an empty directory the snapshot never had was left behind")

    def test_the_whole_nest_goes_not_just_the_bottom_of_it(self):
        # An agent that writes one file writes every directory above it, and
        # removing only the innermost leaves the rest standing.
        self.save()
        _write(self.path("a", "b", "c", "new.txt"))
        self.restore()
        self.assertFalse(os.path.exists(self.path("a")), self.output)

    def test_a_directory_that_still_holds_something_stays(self):
        _write(self.path("src", "tracked.py"), "print(1)\n")
        self.save()
        _write(self.path("src", "scratch.py"))
        self.restore()
        self.assertTrue(os.path.isfile(self.path("src", "tracked.py")),
                        "the restore removed a directory that was in the snapshot")

    def test_a_hard_restore_cleans_up_after_itself_too(self):
        # --hard deletes instead of moving aside; the directory is just as empty
        # either way.
        self.save()
        _write(self.path("notes", "scratch.md"))
        self.restore(hard=True)
        self.assertFalse(os.path.exists(self.path("notes")), self.output)


class TestWhatTheSummarySays(_Project):

    def test_a_hard_restore_names_no_aside_directory(self):
        self.save()
        _write(self.path("notes", "scratch.md"))
        result = self.restore(hard=True)
        self.assertIsNone(result["aside_dir"],
                          "--hard deleted the new files and still named a directory "
                          "to find them in")
        self.assertEqual(result["deleted"], 1)

    def test_a_restore_with_nothing_new_names_no_aside_directory(self):
        self.save()
        _write(self.path("keep.txt"), "edited\n")
        result = self.restore()
        self.assertIsNone(result["aside_dir"], self.output)
        self.assertEqual(result["moved_aside"], 0)

    def test_a_restore_that_restored_everything_warns_about_nothing(self):
        _write(self.path("src", "a.py"), "one\n")
        _write(self.path("src", "b.py"), "two\n")
        self.save()
        _write(self.path("src", "a.py"), "changed\n")
        _write(self.path("src", "b.py"), "changed\n")
        result = self.restore()
        self.assertEqual(result["restored"], result["planned"])
        self.assertNotIn("could not be restored", self.output,
                         "a restore in which everything came back warned that "
                         "something had not")

    def test_a_restore_of_an_empty_snapshot_warns_about_nothing_either(self):
        # Nothing planned and nothing restored is the boundary the mutant sits
        # on: 0 of 0 files could not be restored is not a warning, it is noise.
        os.remove(self.path("keep.txt"))
        empty = self.save("empty")
        _write(self.path("keep.txt"), "back again\n")
        self.restore(empty["id"])
        self.assertNotIn("could not be restored", self.output)


class TestSymlinksThatDidNotChange(_Project):

    def setUp(self):
        super().setUp()
        _write(self.path("target.txt"), "pointed at\n")
        os.symlink("target.txt", self.path("link"))

    def test_a_symlink_that_still_matches_is_not_in_the_plan(self):
        self.save()
        _write(self.path("keep.txt"), "edited\n")
        result = self.restore()
        self.assertEqual(result["planned"], 1,
                         "an unchanged symlink was planned for restore: " + self.output)

    def test_a_symlink_pointing_somewhere_else_now_is_in_the_plan(self):
        self.save()
        os.remove(self.path("link"))
        os.symlink("keep.txt", self.path("link"))
        result = self.restore()
        self.assertEqual(result["planned"], 1)
        self.assertEqual(os.readlink(self.path("link")), "target.txt")

    def test_a_symlink_replaced_by_a_regular_file_is_put_back(self):
        self.save()
        os.remove(self.path("link"))
        _write(self.path("link"), "not a symlink any more\n")
        self.restore()
        self.assertTrue(os.path.islink(self.path("link")), self.output)


class TestWhatGarbageCollectionLeaves(_Project):

    def test_dropping_every_snapshot_leaves_no_empty_shard_directories(self):
        # Sharded two hex characters deep, so a store that held a real project
        # leaves a directory per shard behind if the last step is skipped.
        for i in range(40):
            _write(self.path("src", "f{}.txt".format(i)), "content {}\n".format(i))
        snap = self.save()
        objects = store._objects_dir(store._store_dir(self.root))
        self.assertTrue(os.listdir(objects), "nothing was stored to collect")

        store.drop_snapshots(store._store_dir(self.root), [snap["id"]])

        leftover = [name for name in os.listdir(objects)
                    if os.path.isdir(os.path.join(objects, name))
                    and not os.listdir(os.path.join(objects, name))]
        self.assertEqual(leftover, [],
                         "garbage collection emptied these shards and left them there")


class TestHowADamagedSnapshotIsExplained(_Project):

    @unittest.skipIf(hasattr(os, "geteuid") and os.geteuid() == 0,
                     "root can read a file with no read bit")
    def test_the_reason_is_the_reason_not_the_traceback(self):
        snap = self.save()
        store_dir = store._store_dir(self.root)
        manifest = store._snap_path(store_dir, snap["id"])
        os.chmod(manifest, 0)
        self.addCleanup(os.chmod, manifest, stat.S_IRUSR | stat.S_IWUSR)

        good, damaged = store.scan_snapshots(store_dir)
        self.assertEqual(good, [])
        self.assertEqual([d["why"] for d in damaged], ["Permission denied"],
                         "the listing shows the exception instead of the reason")


class TestWhatTheSymlinkRefusalSays(_Project):

    def _refuse(self, paths):
        out = io.StringIO()
        with self.assertRaises(RuntimeError) as raised:
            store._refuse_to_write_outside(self.root, {"files": [{"path": p} for p in paths]})
        del out
        return str(raised.exception)

    def test_when_the_file_itself_is_the_symlink_it_is_not_named_twice(self):
        outside = tempfile.mkdtemp(prefix="unedit_outside_")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        os.symlink(os.path.join(outside, "notes.txt"), self.path("notes.txt"))
        message = self._refuse(["notes.txt"])
        self.assertIn("notes.txt (symlink -> ", message)
        self.assertNotIn("notes.txt (symlink notes.txt -> ", message,
                         "the message names the same path as both the file and the link")

    def test_when_a_parent_is_the_symlink_the_message_names_which_one(self):
        outside = tempfile.mkdtemp(prefix="unedit_outside_")
        self.addCleanup(shutil.rmtree, outside, ignore_errors=True)
        os.symlink(outside, self.path("sub"))
        message = self._refuse(["sub/notes.txt"])
        self.assertIn("sub/notes.txt (symlink sub -> ", message,
                      "the message does not say which symlink to remove")


# Equivalent mutants in the empty-directory cleanup, left alive on purpose:
#
#   `sorted(..., reverse=True)`      Deepest-first only matters if the upward
#                                    walk did not exist.  It does: removing
#                                    `a/b` then walks up and removes `a`, so
#                                    either order reaches the same tree.
#   `isdir(d) and not listdir(d)`    Both halves are inside `except OSError:
#   `parent != root and ...`         pass`.  Flipped to `or`, the extra calls
#                                    raise — rmdir on a non-empty directory,
#                                    listdir on one that is gone — and the
#                                    handler swallows it.  Same tree, longer
#                                    path to it.
#   `startswith(rel + '/') or ==`    Flipped to `and`, a directory that is in
#                                    the snapshot can be removed here — and is
#                                    then recreated by the `makedirs` in the
#                                    restore loop three lines further down,
#                                    before anything looks at the tree again.
#
# All four are redundancy rather than dead code, and the tests above pin the
# tree that block is supposed to produce.  Simplifying it is a separate change
# with its own reason to be made, not something to do while chasing a sweep.


if __name__ == "__main__":
    unittest.main()
