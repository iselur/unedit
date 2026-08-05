"""A snapshot message wrote its own file row, and no row had a bound.

`one_line` already says what a row is for:

    A newline in either forges a row that looks exactly like a real snapshot,
    and `unedit list` is read by people deciding what to restore.

Two places did not get it.

`unedit show` printed the message straight out of the manifest.  The manifest
is a JSON file in `.unedit/`, and a message with a newline in it prints the
rest of itself above the file list, in the same shape as the file list:

    snapshot: 20260804-101337-391949-rz8c
      when: 2026-08-04 10:13:37  — ok
      forged.py                         1.2 KB  2026-08-04 09:00
      1 files

      a.txt                                            3 B  2026-08-04 10:13

`forged.py` is not in the snapshot and never was.  `show` is the view somebody
reads before deciding to restore.

And nothing anywhere had a length bound.  `unedit save -m "$(cat NOTES.md)"`
is an ordinary thing for a script to do; it made a 200,000-character row in
both `show` and `list`, which is every other snapshot scrolled off the screen.

The cap belongs in the printing, not in the store: a message is kept whole on
disk and whole in `--json`, and only the row is cut.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unedit.cli import main
from unedit import store as _store
from unedit import terminal as _terminal


class RowCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="unedit-rows-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)
        with open(os.path.join(self.root, "a.txt"), "w") as fh:
            fh.write("hi\n")

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--dir", self.root] + list(argv))
        return code, out.getvalue(), err.getvalue()

    def snapshot_id(self):
        return _store.list_snapshots(_store._store_dir(self.root))[0]["id"]

    def rewrite_manifest(self, **fields):
        """Edit the snapshot on disk, the way anything with write access can."""
        store = _store._store_dir(self.root)
        path = os.path.join(store, "snapshots", self.snapshot_id() + ".json")
        with open(path) as fh:
            manifest = json.load(fh)
        manifest.update(fields)
        with open(path, "w") as fh:
            json.dump(manifest, fh)


class TestTheHelper(unittest.TestCase):
    """`row` is `one_line` with a bound; `one_line` itself stays lossless."""

    def test_ordinary_text_is_untouched(self):
        self.assertEqual(_terminal.row("fixed the parser"), "fixed the parser")

    def test_a_newline_cannot_start_a_second_row(self):
        got = _terminal.row("ok\n  forged.py   1.2 KB")
        self.assertEqual(len(got.splitlines()), 1, repr(got))

    def test_a_long_value_is_cut_and_says_so(self):
        got = _terminal.row("x" * 200_000)
        self.assertLess(len(got), 500, len(got))
        self.assertIn("more characters", got)

    def test_a_value_at_the_cap_is_left_alone(self):
        self.assertEqual(_terminal.row("x" * 400), "x" * 400)

    def test_one_line_does_not_cut(self):
        # It is used to sanitize the message *at save time*, and truncating
        # there would lose the text on disk rather than only on screen.
        self.assertEqual(len(_terminal.one_line("x" * 200_000)), 200_000)


class TestShow(RowCase):

    def test_a_forged_message_does_not_become_a_file_row(self):
        self.run_cli("save", "-m", "ok")
        self.rewrite_manifest(
            message="ok\n  forged.py                         1.2 KB  2026-08-04 09:00")
        code, out, err = self.run_cli("show", self.snapshot_id())
        self.assertEqual(code, 0, err)
        # The file list is the block after the blank line.  The message may
        # of course still *say* "forged.py" — it is a message — but it says so
        # on the `when:` row, where it is plainly a message and not an entry.
        listed = out.split("\n\n", 1)[1].strip().splitlines()
        self.assertNotIn("forged.py", " ".join(listed),
                         "a message wrote a file row:\n" + out)

    def test_the_file_count_still_matches_the_rows(self):
        self.run_cli("save", "-m", "ok")
        self.rewrite_manifest(
            message="ok\n  forged.py                         1.2 KB  2026-08-04 09:00")
        code, out, err = self.run_cli("show", self.snapshot_id())
        count = [l for l in out.splitlines() if l.strip().endswith("files")]
        self.assertEqual(len(count), 1, out)
        n = int(count[0].split()[0])
        rows = out.split("\n\n", 1)[1].strip().splitlines()
        self.assertEqual(len(rows), n, "header says {} files:\n{}".format(n, out))

    def test_a_huge_message_cannot_fill_the_screen(self):
        self.run_cli("save", "-m", "ok")
        self.rewrite_manifest(message="x" * 200_000)
        code, out, err = self.run_cli("show", self.snapshot_id())
        self.assertLess(max(len(l) for l in out.splitlines()), 600, len(out))

    def test_the_json_view_keeps_the_whole_message(self):
        self.run_cli("save", "-m", "ok")
        self.rewrite_manifest(message="x" * 200_000)
        code, out, err = self.run_cli("show", self.snapshot_id(), "--json")
        self.assertEqual(len(json.loads(out)["message"]), 200_000)

    def test_ordinary_output_is_unchanged(self):
        self.run_cli("save", "-m", "fixed the parser")
        code, out, err = self.run_cli("show", self.snapshot_id())
        self.assertIn("— fixed the parser", out)
        self.assertIn("a.txt", out)
        self.assertEqual(code, 0, err)


class TestList(RowCase):

    def test_a_huge_message_cannot_fill_the_screen(self):
        self.run_cli("save", "-m", "ok")
        self.rewrite_manifest(message="x" * 200_000)
        code, out, err = self.run_cli("list")
        self.assertLess(max(len(l) for l in out.splitlines()), 600, len(out))

    def test_one_snapshot_is_one_row(self):
        self.run_cli("save", "-m", "ok")
        self.rewrite_manifest(message="ok\n20260804-000000-000000-fake  1 files")
        code, out, err = self.run_cli("list")
        rows = [l for l in out.splitlines() if l.strip()]
        self.assertEqual(len(rows), 1, "one snapshot, {} rows:\n{}".format(
            len(rows), out))

    def test_ordinary_output_is_unchanged(self):
        self.run_cli("save", "-m", "fixed the parser")
        code, out, err = self.run_cli("list")
        self.assertIn("fixed the parser", out)
        self.assertEqual(code, 0, err)


if __name__ == "__main__":
    unittest.main()
