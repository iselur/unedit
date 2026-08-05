"""Lines the suite ran but did not actually pin down.

A mutation sweep changes one operator or one constant at a time and reruns the
whole suite.  Every mutant that survives is a line the tests execute without
depending on.  These are the survivors from the sweep over `unedit/store.py`,
each turned into the test that kills it.

  * `exist_ok=True` in `store_object`.  The object store is sharded by the
    first two hex characters of the hash, so the shard directory already exists
    for the *second* file that lands in it.  Every test so far stored so few
    files that no two ever shared a shard — with 256 shards you need about
    twenty files before a collision is likely, and a real project has
    thousands.  Drop the flag and `unedit save` raises FileExistsError partway
    through, leaving a half-written snapshot.

  * `total_files > FILE_LIMIT` and `total_size > SIZE_LIMIT`.  Both boundaries
    were untested: a tree of exactly the limit is allowed, one file more is
    refused, and the message has to say `--force`.

  * `if not rel_path or os.path.isabs(rel_path): return True` in `_climbs_out`.
    This is the text-level half of the containment check.  Both operands were
    unpinned, which means an absolute path in a manifest — the plainest way to
    aim a restore at `/etc` — was reaching the filesystem check with nothing
    behind it in the layer that is supposed to catch it first.

  * `yes=False` and `force=False` in `restore`'s signature.  A default that
    flips to True turns the undo button into an unprompted destructive write.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
import unittest
from unittest import mock

from unedit import store


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return path


def _same_shard_pair():
    """Two contents whose hashes land in the same object-store shard.

    Searched rather than hard-coded so it stays true if the sharding width
    changes.  Deterministic: the same two strings every run.
    """
    seen = {}
    for i in range(10_000):
        text = f"content-{i}\n"
        shard = hashlib.sha256(text.encode()).hexdigest()[:2]
        if shard in seen:
            return seen[shard], text
        seen[shard] = text
    raise AssertionError("no shard collision found — sharding changed?")


class StoreCase(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="unedit_mut_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def limit(self, name, value):
        """Lower a guard rail for the length of one test."""
        old = getattr(store, name)
        setattr(store, name, value)
        self.addCleanup(setattr, store, name, old)


class TestTwoObjectsInOneShard(StoreCase):
    """The second file to land in a shard must not blow up the save."""

    def test_store_object_twice_into_the_same_shard(self):
        objects = os.path.join(self.root, "objects")
        a = _write(os.path.join(self.root, "a"), "a\n")
        b = _write(os.path.join(self.root, "b"), "b\n")
        store.store_object(objects, a, "aa" + "0" * 62)
        # Same shard directory, different object.  This is the ordinary case
        # once a project has more than a handful of files, not an edge case.
        store.store_object(objects, b, "aa" + "1" * 62)
        self.assertEqual(sorted(os.listdir(os.path.join(objects, "aa"))),
                         ["0" * 62, "1" * 62])

    def test_a_real_save_of_two_files_that_collide(self):
        first, second = _same_shard_pair()
        _write(os.path.join(self.root, "one.txt"), first)
        _write(os.path.join(self.root, "two.txt"), second)
        snap = store.save(self.root, message="both")
        self.assertEqual(len(snap["files"]), 2, snap)


class TestTheGuardRailBoundaries(StoreCase):
    """Exactly the limit is fine.  One more is refused, and says how to override."""

    def _tree(self, n):
        for i in range(n):
            _write(os.path.join(self.root, f"f{i}.txt"), f"{i}\n")

    def test_a_tree_of_exactly_the_file_limit_is_allowed(self):
        self.limit("FILE_LIMIT", 3)
        self._tree(3)
        self.assertEqual(len(store.save(self.root)["files"]), 3)

    def test_one_file_over_the_limit_is_refused(self):
        self.limit("FILE_LIMIT", 3)
        self._tree(4)
        with self.assertRaises(RuntimeError) as cm:
            store.save(self.root)
        self.assertIn("--force", str(cm.exception))

    def test_force_overrides_the_file_limit(self):
        self.limit("FILE_LIMIT", 3)
        self._tree(4)
        self.assertEqual(len(store.save(self.root, force=True)["files"]), 4)

    def test_a_tree_of_exactly_the_size_limit_is_allowed(self):
        _write(os.path.join(self.root, "big.txt"), "x" * 100)
        self.limit("SIZE_LIMIT", 100)   # the file is exactly this many bytes
        self.assertEqual(len(store.save(self.root)["files"]), 1)

    def test_one_byte_over_the_size_limit_is_refused(self):
        _write(os.path.join(self.root, "big.txt"), "x" * 100)
        self.limit("SIZE_LIMIT", 99)
        with self.assertRaises(RuntimeError) as cm:
            store.save(self.root)
        self.assertIn("--force", str(cm.exception))


class TestAPathThatLeavesTheProject(unittest.TestCase):
    """`_climbs_out` reads the path as text, before anything touches the disk.

    It is the cheap half of the containment check and the half that still works
    when the target does not exist yet, which is exactly when a restore is
    about to create it.
    """

    def test_an_absolute_path_climbs_out(self):
        self.assertTrue(store._climbs_out("/etc/passwd"))

    def test_an_empty_path_climbs_out(self):
        # Empty joins to the root itself, so a manifest entry of "" would have
        # the restore write over the project directory.
        self.assertTrue(store._climbs_out(""))

    def test_a_dotdot_path_climbs_out(self):
        self.assertTrue(store._climbs_out("../outside.txt"))

    def test_a_dotdot_in_the_middle_that_stays_inside_does_not(self):
        self.assertFalse(store._climbs_out("a/../b.txt"))

    def test_an_ordinary_relative_path_does_not(self):
        self.assertFalse(store._climbs_out("src/app.py"))


class TestASymlinkThatChanged(StoreCase):
    """Three ways a symlink stops matching its snapshot, all of them restorable.

    The check is `cur is None or not cur[1] or cur[2] != target` — gone,
    replaced by a real file, or still a symlink but pointing somewhere else.
    Only the first was tested.  The other two are how a symlink actually gets
    broken: something writes through it, or repoints it.
    """

    def setUp(self):
        super().setUp()
        _write(os.path.join(self.root, "real.txt"), "real\n")
        _write(os.path.join(self.root, "other.txt"), "other\n")
        self.link = os.path.join(self.root, "link")
        os.symlink("real.txt", self.link)
        self.snap = store.save(self.root, message="with a link")["id"]

    def back(self):
        store.restore(self.root, self.snap, yes=True, print_fn=lambda *_a: None)

    def test_a_deleted_symlink_comes_back(self):
        os.remove(self.link)
        self.back()
        self.assertTrue(os.path.islink(self.link))
        self.assertEqual(os.readlink(self.link), "real.txt")

    def test_a_symlink_repointed_elsewhere_comes_back(self):
        os.remove(self.link)
        os.symlink("other.txt", self.link)
        self.back()
        self.assertEqual(os.readlink(self.link), "real.txt")

    def test_a_symlink_replaced_by_a_regular_file_comes_back(self):
        os.remove(self.link)
        _write(self.link, "not a link any more\n")
        self.back()
        self.assertTrue(os.path.islink(self.link))
        self.assertEqual(os.readlink(self.link), "real.txt")

    def test_a_symlink_that_is_unchanged_is_left_alone(self):
        # The other direction: nothing to restore means the restore reports
        # nothing restored, not a symlink rewritten for no reason.
        before = os.lstat(self.link).st_ino
        self.back()
        self.assertEqual(os.lstat(self.link).st_ino, before)


class TestTheDirectoriesLeftBehind(StoreCase):
    """A restore that moves new files aside has to take their folders too.

    The cleanup sorts deepest-first so children go before parents; sort it the
    other way and `rmdir` hits a parent that still holds its child, fails
    quietly, and the tree keeps a skeleton of empty directories that were not
    there when the snapshot was taken.  Nothing was broken, so nothing
    complained — which is why it survived.
    """

    def test_a_nested_directory_added_after_the_snapshot_is_gone_afterwards(self):
        _write(os.path.join(self.root, "keep.txt"), "keep\n")
        snap = store.save(self.root, message="before")["id"]
        _write(os.path.join(self.root, "a", "b", "c", "new.txt"), "new\n")
        store.restore(self.root, snap, yes=True, print_fn=lambda *_a: None)
        self.assertFalse(os.path.exists(os.path.join(self.root, "a")),
                         sorted(os.listdir(self.root)))

    def test_a_directory_the_snapshot_knows_about_is_kept(self):
        _write(os.path.join(self.root, "src", "app.py"), "x = 1\n")
        snap = store.save(self.root, message="before")["id"]
        _write(os.path.join(self.root, "src", "extra.py"), "y = 2\n")
        store.restore(self.root, snap, yes=True, print_fn=lambda *_a: None)
        self.assertTrue(os.path.isfile(os.path.join(self.root, "src", "app.py")))


class TestGarbageCollectionWithSymlinks(StoreCase):
    """`drop` walks every manifest entry to decide which objects are still used.

    The guard is `isinstance(f, dict) and f['type'] == 'file' and 'hash' in f`,
    and all three clauses matter: a symlink entry has no `hash`, and a manifest
    that has been hand-edited or truncated can hold entries that are not dicts
    at all.  Loosen it and the garbage collector raises KeyError partway
    through — after it has already deleted snapshots, so the store is left in a
    state nobody asked for.  No test had ever dropped a snapshot from a store
    that contained a symlink.
    """

    def test_dropping_a_snapshot_from_a_store_that_holds_a_symlink(self):
        _write(os.path.join(self.root, "real.txt"), "real\n")
        os.symlink("real.txt", os.path.join(self.root, "link"))
        first = store.save(self.root, message="one")["id"]
        _write(os.path.join(self.root, "real.txt"), "changed\n")
        second = store.save(self.root, message="two")["id"]

        result = store.drop_snapshots(self.root, [first])
        self.assertNotIn(first, [s["id"] for s in
                                 store.list_snapshots(store._store_dir(self.root))])

        # And the surviving snapshot still restores — the GC must not have
        # taken the object the remaining manifest points at.
        _write(os.path.join(self.root, "real.txt"), "trashed\n")
        store.restore(self.root, second, yes=True, print_fn=lambda *_a: None)
        with open(os.path.join(self.root, "real.txt")) as fh:
            self.assertEqual(fh.read(), "changed\n")
        self.assertIsInstance(result, dict)


class TestRestoreAsksFirst(StoreCase):
    """The defaults on the undo button are the conservative ones."""

    def setUp(self):
        super().setUp()
        _write(os.path.join(self.root, "a.txt"), "original\n")
        self.snap = store.save(self.root, message="before")["id"]
        _write(os.path.join(self.root, "a.txt"), "edited\n")

    def read(self):
        with open(os.path.join(self.root, "a.txt")) as fh:
            return fh.read()

    def test_without_yes_it_aborts_and_changes_nothing(self):
        # Pressing return at the prompt is the same as saying no.  A `yes`
        # default of True would make this call restore the file without ever
        # asking — the prompt would not even be reached.
        with mock.patch("builtins.input", return_value="") as prompt:
            result = store.restore(self.root, self.snap,
                                   print_fn=lambda *_a: None)
        self.assertTrue(prompt.called, "the prompt was never shown")
        self.assertEqual(result, {"aborted": True})
        self.assertEqual(self.read(), "edited\n")

    def test_with_yes_it_restores(self):
        store.restore(self.root, self.snap, yes=True, print_fn=lambda *_a: None)
        self.assertEqual(self.read(), "original\n")

    def test_the_safety_snapshot_obeys_the_same_guard_rails(self):
        # restore's first act is a safety snapshot of the current tree, and it
        # passes its own `force` through.  A `force` default of True would let
        # that snapshot ignore the limits the user set.
        self.limit("FILE_LIMIT", 0)
        with self.assertRaises(RuntimeError) as cm:
            store.restore(self.root, self.snap, yes=True, print_fn=lambda *_a: None)
        self.assertIn("--force", str(cm.exception))


if __name__ == "__main__":
    unittest.main()
