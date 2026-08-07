"""One moment, one clock, in every view that prints one.

Two faults, both of them a wrong statement about when something happened
rather than a crash, which is the kind that gets believed.

The first.  `save` writes the moment with its offset, and says why in a comment
next to the line that writes it: a stamp without one means a different instant
on every machine.  The reader then cut the offset off the end of the string and
printed the rest — which is that different instant, spelled as if it were
yours.  A store written in a container running UTC, or synced from a laptop
three zones over, listed at the wall clock of the machine that wrote it, and
nothing on the row said so.  The stamp was being read as a shape rather than as
a moment: the code was asking whether a `-` six characters from the end was an
offset or part of a date, a question a parser does not have to ask.

The second.  `unedit show` prints a `when:` row and then a row per file, and
the two were written by different hands: the first to the second, the second to
the minute.  So the same command printed two shapes of clock, and — because the
files' rows are resolved against the reader's clock while the `when:` row was
not — a snapshot could read as having happened before the files it holds.  Two
displays of one thing that disagree do not look like a display bug.  They look
like the tool got the order wrong.

So there is one spelling now, `store._SHOWN`, and two ways in: `fmt_time` for a
stamp out of a manifest and `fmt_mtime` for a POSIX time off the disk.  Both
land on the reader's clock, which is the only clock the reader can check.

One class moves the clock the tests run on.  Every conversion here lands a
moment on the reader's, and on a box already running UTC each of those is the
identity — so the code can stop doing them and every assertion over the output
still passes.  Three mutants proved exactly that.  The reader's zone is the
fixture in that class, and the assertions it repeats are the ones that cannot
see anything without it.

The last class is structural.  Nothing it asserts is visible in any command's
output — a call site that goes back to trimming the string prints exactly what
the one rule prints, on the machine the test runs on, and only differs on
somebody else's.  That is the whole fault, so it has to be caught by reading
the code rather than by reading the output.
"""

from __future__ import annotations

import datetime
import io
import json
import os
import re
import shutil
import sys
import tempfile
import time
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unedit.cli import main
from unedit import store as _store

#: A clock as this tool writes one, to the second.  Spelled out here rather
#: than imported from `store`: a test that builds its expectation out of the
#: constant the code formats with agrees with any format string there is.
SHOWN = re.compile(r"^\d{4}-\d\d-\d\d \d\d:\d\d:\d\d$")


class ClockCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="unedit-clock-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        with open(os.path.join(self.root, "a.txt"), "w") as fh:
            fh.write("hi\n")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--dir", self.root] + list(argv))
        return code, out.getvalue(), err.getvalue()

    def snapshot_path(self):
        store = _store._store_dir(self.root)
        snap_id = _store.list_snapshots(store)[0]["id"]
        return os.path.join(store, "snapshots", snap_id + ".json")

    def rewrite_manifest(self, **fields):
        """Edit the snapshot on disk, the way another machine's store arrives."""
        path = self.snapshot_path()
        with open(path) as fh:
            manifest = json.load(fh)
        manifest.update(fields)
        with open(path, "w") as fh:
            json.dump(manifest, fh)


def somewhere_else(moment: datetime.datetime, hours: int) -> str:
    """`moment`, written down by a machine `hours` from the reader's zone.

    Derived from the reader's own offset rather than pinned to a zone, because
    a fixture pinned in UTC says nothing on a box that is already in UTC — the
    conversion under test becomes a no-op and every assertion over it passes
    while measuring nothing.  Plus a fixed offset, the two sides differ by a
    known amount on every machine there is.
    """
    here = moment.astimezone()
    there = datetime.timezone(here.utcoffset() + datetime.timedelta(hours=hours))
    return here.astimezone(there).isoformat(timespec="seconds")


class TestOneMomentIsOneString(ClockCase):
    def test_the_same_instant_spelled_four_ways_shows_one_clock(self):
        # The four spellings a manifest can arrive in: this machine's offset,
        # a machine east, a machine west, and UTC written with a Z.  They are
        # one moment, and a person reading `unedit list` on this machine has
        # one question — when did that happen, by my clock — with one answer.
        moment = datetime.datetime(2026, 8, 7, 9, 36, 8).astimezone()
        here = _store.fmt_time(moment.isoformat(timespec="seconds"))
        for hours in (-7, 0, 5):
            self.assertEqual(_store.fmt_time(somewhere_else(moment, hours)),
                             here, "offset {:+d}h".format(hours))
        as_utc = moment.astimezone(datetime.timezone.utc)
        with_a_z = as_utc.isoformat(timespec="seconds").replace("+00:00", "Z")
        self.assertEqual(_store.fmt_time(with_a_z), here)

    def test_a_stamp_from_another_machine_moves_to_the_readers_clock(self):
        # Not just "the same as each other" -- the same as the clock on the
        # wall of whoever is reading.  Both halves matter: trimming the offset
        # off the string also makes every spelling agree with every other, and
        # agrees with none of them about what time it is here.
        moment = datetime.datetime(2026, 8, 7, 9, 36, 8).astimezone()
        self.assertEqual(_store.fmt_time(somewhere_else(moment, 6)),
                         moment.strftime("%Y-%m-%d %H:%M:%S"))

    def test_a_stamp_with_no_offset_is_read_as_this_machines(self):
        # What stores written before the stamp carried an offset hold.  It was
        # local when it was written, on this machine, and moving it would be
        # inventing a fact the file does not have.
        self.assertEqual(_store.fmt_time("2026-08-07T09:36:08"),
                         "2026-08-07 09:36:08")

    def test_utc_is_understood_however_it_is_spelled(self):
        # `Z` and `z` are one character to everything that writes a stamp, and
        # two to `fromisoformat`: it learned the capital in 3.11 and has never
        # taken the small one, which raises to this day.  A store written by
        # something that spells it small is not an unreadable store.
        capital = _store.fmt_time("2026-08-07T09:36:08Z")
        small = _store.fmt_time("2026-08-07T09:36:08z")
        self.assertTrue(SHOWN.match(capital), capital)
        self.assertEqual(small, capital)
        self.assertEqual(capital, _store.fmt_time("2026-08-07T09:36:08+00:00"))

    def test_the_second_is_kept(self):
        # Snapshot ids are unique to the second and two saves a few seconds
        # apart are a normal afternoon, so a listing that rounds to the minute
        # shows two rows claiming the same time.
        one = _store.fmt_time("2026-08-07T09:36:08")
        another = _store.fmt_time("2026-08-07T09:36:09")
        self.assertTrue(SHOWN.match(one), one)
        self.assertNotEqual(one, another)
        self.assertTrue(one.endswith(":08") and another.endswith(":09"),
                        (one, another))


class TestWhatItCannotRead(ClockCase):
    def test_a_stamp_it_cannot_read_comes_back_as_it_was(self):
        # Somebody else's file in `snapshots/`, or one this tool wrote in a
        # version that has not happened yet.  Worth noticing on the row, not
        # worth `unedit list` stopping over -- the rest of the store is fine
        # and the whole reason to run `list` is to find out what is in it.
        for junk in ("not-a-stamp", "2026-13-45T99:99:99", "yesterday"):
            self.assertEqual(_store.fmt_time(junk), junk)

    def test_a_missing_stamp_is_blank_rather_than_a_word(self):
        # An empty cell reads as "this row does not have one"; the word `None`
        # in a time column reads as a time this tool thinks it recorded.
        self.assertEqual(_store.fmt_time(""), "")

    def test_a_listing_of_a_manifest_with_a_bad_stamp_still_lists(self):
        self.run_cli("save", "-m", "ok")
        self.rewrite_manifest(timestamp="whenever")
        code, out, _ = self.run_cli("list")
        self.assertIn("whenever", out)
        self.assertEqual(code, 0)

    def test_an_mtime_the_platform_cannot_read_leaves_the_row_standing(self):
        # A filesystem storing something else in the field, or a clock set to
        # the year 200000.  The name and the size are still worth printing.
        self.assertEqual(_store.fmt_mtime(1e30), "")


class TestTheViewsAgree(ClockCase):
    def _shown_clocks(self, text):
        return re.findall(r"\d{4}-\d\d-\d\d[ T]\d\d:\d\d(?::\d\d)?", text)

    def test_show_prints_one_shape_of_clock_not_two(self):
        # The `when:` row and the file rows under it, which were written to
        # different precisions by different hands.
        self.run_cli("save", "-m", "ok")
        _, out, _ = self.run_cli("show")
        clocks = self._shown_clocks(out)
        self.assertGreaterEqual(len(clocks), 2, out)
        for clock in clocks:
            self.assertTrue(SHOWN.match(clock), "{!r} in:\n{}".format(clock, out))

    def test_a_snapshot_does_not_read_as_older_than_the_files_it_holds(self):
        # The shape of the first fault as somebody actually met it: the files
        # were stamped against the reader's clock and the snapshot was not, so
        # `show` said the save happened an hour before the files it saved.
        self.run_cli("save", "-m", "ok")
        moment = datetime.datetime.now().astimezone()
        self.rewrite_manifest(timestamp=somewhere_else(moment, -3))
        _, out, _ = self.run_cli("show")
        when = [ln for ln in out.splitlines() if ln.strip().startswith("when:")]
        self.assertEqual(len(when), 1, out)
        rows = [c for ln in out.splitlines() if " B  " in ln
                for c in self._shown_clocks(ln)]
        self.assertTrue(rows, out)
        self.assertLessEqual(max(rows), self._shown_clocks(when[0])[0],
                             "the snapshot reads as older than its own files:\n"
                             + out)

    def test_every_view_that_prints_the_stamp_prints_the_same_one(self):
        # `list`, `show` and `diff` all read the same field off the same file.
        self.run_cli("save", "-m", "ok")
        self.rewrite_manifest(
            timestamp=somewhere_else(datetime.datetime.now().astimezone(), 4))
        seen = set()
        for command in (["list"], ["show"], ["diff"]):
            _, out, _ = self.run_cli(*command)
            found = [c for ln in out.splitlines() if "-" in ln and ":" in ln
                     for c in self._shown_clocks(ln)]
            self.assertTrue(found, "{}: {}".format(command, out))
            seen.add(found[0])
        self.assertEqual(len(seen), 1, seen)


@unittest.skipUnless(hasattr(time, "tzset"), "the clock cannot be moved here")
class TestTheClockIsTheReadersOwn(ClockCase):
    """Read on a machine whose clock is not UTC, because most of them are not.

    These repeat assertions made above, and they are not duplicates of them:
    every one of these is a conversion to the reader's clock, and on a box
    running UTC a conversion to the reader's clock is the identity function.
    The versions above pass whether the code does the work or not.  These are
    the ones that notice.

    The zone is a POSIX offset rather than a named one so it needs no tz
    database, and it is half an hour off the hour so a conversion cannot hide
    behind an hour's rounding.
    """

    #: `-05:30` is POSIX's way of saying local is UTC *plus* five and a half
    #: hours; no rule after it means no daylight saving to drift across.
    ZONE = "XYZ-05:30"
    UTC_STAMP = "2026-08-07T09:36:08+00:00"
    HERE = "2026-08-07 15:06:08"

    def setUp(self) -> None:
        super().setUp()
        was = os.environ.get("TZ")

        def put_it_back():
            if was is None:
                os.environ.pop("TZ", None)
            else:
                os.environ["TZ"] = was
            time.tzset()

        self.addCleanup(put_it_back)
        os.environ["TZ"] = self.ZONE
        time.tzset()

    def test_the_clock_really_moved(self):
        # The fixture's own check.  If this fails, everything below is passing
        # over a conversion it cannot see -- which is the shape the fault took.
        self.assertEqual(datetime.datetime.now().astimezone().utcoffset(),
                         datetime.timedelta(hours=5, minutes=30))

    def test_a_stamp_from_another_zone_is_moved_to_this_clock(self):
        self.assertEqual(_store.fmt_time(self.UTC_STAMP), self.HERE)

    def test_a_z_says_the_same_thing_and_is_moved_too(self):
        self.assertEqual(_store.fmt_time("2026-08-07T09:36:08Z"), self.HERE)
        self.assertEqual(_store.fmt_time("2026-08-07T09:36:08z"), self.HERE)

    def test_a_stamp_with_no_offset_stays_where_it_was_written(self):
        # It was this machine's wall clock when it was written and it is this
        # machine's wall clock now.  Moving it would be inventing a fact the
        # file does not carry.
        self.assertEqual(_store.fmt_time("2026-08-07T09:36:08"),
                         "2026-08-07 09:36:08")

    def test_a_file_time_is_read_on_the_same_clock_as_the_row_above_it(self):
        # A POSIX time has no zone in it at all, so there is nothing to drop
        # and the only way to get this wrong is to resolve it somewhere else.
        epoch = datetime.datetime(2026, 8, 7, 9, 36, 8,
                                  tzinfo=datetime.timezone.utc).timestamp()
        self.assertEqual(_store.fmt_mtime(epoch), self.HERE)

    def test_a_store_written_three_zones_over_reads_on_this_clock(self):
        # End to end, which is where somebody met it: a store synced off a
        # laptop elsewhere, or written in a container running UTC, read here.
        self.run_cli("save", "-m", "ok")
        self.rewrite_manifest(timestamp=self.UTC_STAMP)
        _, out, _ = self.run_cli("show")
        self.assertIn(self.HERE, out)


class TestItCannotComeBack(ClockCase):
    """Read off the source, because none of this shows up in the output here.

    A call site that trims the string prints the same text as the one rule on
    any machine whose zone matches the store's -- which is every machine a test
    of the output runs on.  The fault is only visible in the code.
    """

    def _source(self, name):
        here = os.path.dirname(os.path.abspath(__file__))
        with open(os.path.join(here, "..", "unedit", name),
                  encoding="utf-8") as fh:
            return fh.read()

    def test_the_string_surgery_is_gone(self):
        cli = self._source("cli.py")
        self.assertNotIn("def _fmt_ts", cli)
        for surgery in ("replace('T', ' ')", "endswith('Z')", "[:-6]"):
            self.assertNotIn(surgery, cli,
                             "{} is back: a stamp is being read as a shape"
                             .format(surgery))

    def test_there_is_one_spelling_of_a_shown_moment(self):
        store = self._source("store.py")
        self.assertIn("_SHOWN = '%Y-%m-%d %H:%M:%S'", store)
        # And no second one written out by hand.  The file rows under `show`
        # had their own, three characters shorter, for exactly as long as
        # nobody put the two views side by side.
        self.assertEqual(store.count("%Y-%m-%d %H:%M"), 1, store.count("%H:%M"))
        self.assertNotIn("%Y-%m-%d %H:%M", self._source("cli.py"))

    #: Every line in the command layer that puts a moment on the screen.  A
    #: list rather than a count: `>= 4` passed while a call site was deleted,
    #: because a count says how many there are and not which ones.
    ROWS_WITH_A_CLOCK = sorted([
        # the listing, a row per snapshot
        "ts = _store.fmt_time(s.get('timestamp', ''))",
        # the `when:` row under `show`
        "ts = _store.fmt_time(manifest.get('timestamp', ''))",
        # the file rows under it
        "shown = _store.fmt_mtime(f['mtime']) if 'mtime' in f else ''",
        # what `diff` and `back` say they are working against
        "ts = _store.fmt_time(result.get('snapshot_timestamp', ''))",
    ])

    def test_every_moment_on_screen_comes_from_the_one_rule(self):
        found = sorted(line.strip() for line in self._source("cli.py").splitlines()
                       if "fmt_time(" in line or "fmt_mtime(" in line)
        self.assertEqual(found, self.ROWS_WITH_A_CLOCK,
                         "a moment is being written down somewhere else")

    def test_the_command_layer_does_not_build_a_clock_of_its_own(self):
        # `datetime` was imported inside a loop in the middle of a print, which
        # is what a second copy of a rule looks like while it is being written.
        self.assertNotIn("datetime", self._source("cli.py"))


if __name__ == "__main__":
    unittest.main()
