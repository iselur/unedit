"""`unedit back` restored the wrong snapshot after the clocks changed.

Snapshot ids are `YYYYMMDD-HHMMSS-uuuuuu-xxxx` and everything downstream
depends on them sorting in the order the snapshots were taken: `scan_snapshots`
sorts the directory listing, `resolve_snap_id(None)` takes the last one, and
`unedit back` with no id restores that.  The id was built from **local** time,
which does not always go forwards.

Take a snapshot, change the machine's zone or let daylight saving end, take
another one a second later:

    20260804-183607-191573-jj8w  2026-08-04 18:36:07  — A: version 1
    20260804-093608-241096-wz9e  2026-08-04 09:36:08  — B: version 2

B is newer and sorts first.  So `unedit back` restored A — an hour or more of
work thrown away — and said:

    done. 1 restored, 0 moved aside, 0 deleted.

which is a wrong restore reported as a right one, the exact failure the comment
in `resolve_snap_id` says that function exists to prevent.

Daylight saving does this to everyone who observes it, twice a year, for a
whole hour.  A laptop carried between zones does it whenever it lands.

So the id is built from UTC, which only ever goes forwards.  The manifest keeps
local time for reading, now with its offset, so the record says which instant it
means rather than leaving it to whoever opens it later.
"""

from __future__ import annotations

import datetime
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


class TestTheIdGoesForwards(unittest.TestCase):
    """An id has to sort by when it was made, whatever the clock on the wall."""

    def _id_in(self, zone: str) -> str:
        out = subprocess.run(
            [sys.executable, "-c",
             "import sys; sys.path.insert(0, %r)\n"
             "from unedit.store import _new_id\n"
             "print(_new_id())" % _ROOT],
            capture_output=True, text=True,
            env=dict(os.environ, TZ=zone, PYTHONPATH=_ROOT))
        self.assertEqual(out.returncode, 0, out.stderr)
        return out.stdout.strip()

    def test_ids_made_in_different_zones_still_sort_by_time(self):
        first = self._id_in("Asia/Tokyo")
        second = self._id_in("America/Los_Angeles")
        third = self._id_in("UTC")
        self.assertEqual([first, second, third],
                         sorted([first, second, third]),
                         "ids taken in this order do not sort in it: {}".format(
                             [first, second, third]))

    def test_the_zone_does_not_change_the_hour_in_the_id(self):
        # The clearest statement of it: the same moment, named the same way
        # everywhere.  Off-by-a-second is fine; off-by-nine-hours is the bug.
        hours = set()
        for zone in ("UTC", "Asia/Tokyo", "America/Los_Angeles"):
            hours.add(self._id_in(zone)[9:11])
        self.assertLessEqual(len(hours), 2, "the id's hour follows the local "
                                            "clock: {}".format(sorted(hours)))

    def test_the_shape_is_unchanged(self):
        # Other code matches this exactly, including the manifest filename
        # check that tells our files apart from anything else in the directory.
        snap_id = store._new_id()
        self.assertTrue(
            store._SNAPSHOT_NAME_RE.match(snap_id + ".json"),
            "id no longer looks like an id: {}".format(snap_id))

    def test_two_ids_in_the_same_second_still_order(self):
        ids = [store._new_id() for _ in range(50)]
        self.assertEqual(len(set(ids)), 50, "ids collided")
        self.assertEqual(ids, sorted(ids), "ids within one second lost order")


class TestTheManifestSaysWhichInstant(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="unedit_clock_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        with open(os.path.join(self.root, "f.txt"), "w") as fh:
            fh.write("one\n")

    def _manifest(self):
        snap_id = store.save(self.root, message="m")["id"]
        path = os.path.join(store._snapshots_dir(store._store_dir(self.root)),
                            snap_id + ".json")
        with open(path) as fh:
            return json.load(fh)

    def test_the_timestamp_carries_an_offset(self):
        stamp = self._manifest()["timestamp"]
        parsed = datetime.datetime.fromisoformat(stamp)
        self.assertIsNotNone(parsed.tzinfo,
                             "a timestamp with no offset is a timestamp that "
                             "means something different on every machine: "
                             + stamp)

    def test_the_timestamp_is_still_local_time(self):
        # It is read by a person, so it stays on the wall clock they have.
        stamp = self._manifest()["timestamp"]
        parsed = datetime.datetime.fromisoformat(stamp)
        now = datetime.datetime.now().astimezone()
        self.assertLess(abs((parsed - now).total_seconds()), 120, stamp)
        self.assertEqual(parsed.utcoffset(), now.utcoffset())


class TestBackRestoresTheNewestOne(unittest.TestCase):
    """End to end, because the wrong restore is what it actually cost."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="unedit_back_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        self.file = os.path.join(self.root, "f.txt")

    def _save(self, text, zone):
        with open(self.file, "w") as fh:
            fh.write(text)
        p = subprocess.run(
            [sys.executable, "-m", "unedit", "--dir", self.root,
             "save", "-m", text.strip()],
            capture_output=True, text=True,
            env=dict(os.environ, TZ=zone, PYTHONPATH=_ROOT))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)

    def test_the_clocks_going_back_does_not_reach_past_the_newest(self):
        self._save("version 1\n", "Asia/Tokyo")
        self._save("version 2\n", "UTC")           # newer, earlier on the wall
        with open(self.file, "w") as fh:
            fh.write("version 3, not saved\n")
        p = subprocess.run(
            [sys.executable, "-m", "unedit", "--dir", self.root, "back", "-y"],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        with open(self.file) as fh:
            got = fh.read()
        self.assertEqual(got, "version 2\n",
                         "`back` restored a snapshot older than the newest "
                         "one and reported success:\n" + p.stdout)

    def test_the_newest_is_still_the_newest_in_one_zone(self):
        self._save("version 1\n", "UTC")
        self._save("version 2\n", "UTC")
        snaps = store.list_snapshots(store._store_dir(self.root))
        self.assertEqual([s["message"] for s in snaps],
                         ["version 1", "version 2"],
                         "ordinary ordering broke")


class TestNothingElseMoves(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="unedit_same_")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        with open(os.path.join(self.root, "f.txt"), "w") as fh:
            fh.write("one\n")

    def test_a_store_is_still_readable_end_to_end(self):
        store.save(self.root, message="first")
        with open(os.path.join(self.root, "f.txt"), "w") as fh:
            fh.write("two\n")
        store.save(self.root, message="second")
        s = store._store_dir(self.root)
        self.assertEqual(len(store.list_snapshots(s)), 2)
        self.assertEqual(store.resolve_snap_id(self.root, None),
                         store.list_snapshots(s)[-1]["id"])

    def test_an_older_manifest_without_an_offset_still_reads(self):
        # Stores written by 0.1.3 have a naive timestamp in them, and a tool
        # that cannot read its own older store is worse than the bug.
        store.save(self.root, message="old one")
        s = store._store_dir(self.root)
        path = os.path.join(store._snapshots_dir(s),
                            store.list_snapshots(s)[0]["id"] + ".json")
        with open(path) as fh:
            manifest = json.load(fh)
        manifest["timestamp"] = "2026-08-04T09:36:08"       # 0.1.3 shape
        with open(path, "w") as fh:
            json.dump(manifest, fh)
        got = store.list_snapshots(s)
        self.assertEqual(len(got), 1)
        self.assertEqual(got[0]["message"], "old one")
        p = subprocess.run(
            [sys.executable, "-m", "unedit", "--dir", self.root, "list"],
            capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT))
        self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
        self.assertIn("2026-08-04 09:36:08", p.stdout, p.stdout)


if __name__ == "__main__":
    unittest.main()
