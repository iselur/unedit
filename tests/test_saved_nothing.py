"""`saved` was the word for a snapshot with nothing in it.

The whole arc, in a project whose `.gitignore` happens to exclude everything:

    $ ls -R
    settings.py  src/app.py

    $ unedit save -m "before the agent runs"
    saved  20260804-103420-954292-24dj  (0 files, 0 B)
           before the agent runs

    ...the agent deletes the files...

    $ unedit back 20260804-103420-954292-24dj --yes
    done. 0 restored, 0 moved aside, 0 deleted.

    $ ls -R
    src/

Both steps said they had worked, and `settings.py` and `src/app.py` are gone
for good.  This is the one failure this tool exists to prevent: the person
ran `save` precisely so that they would have something to go back to, saw
`saved`, and had nothing.

The count was on screen the whole time — `(0 files, 0 B)` — which is exactly
the kind of true detail nobody reads next to a success word.

`scan_tree` already argues the case in its own docstring, about a different
kind of skip: *"A snapshot that quietly contains less than the project is
worse than one that refuses: it is discovered at restore time."*  Ignore
patterns were the one way of containing less than the project that said
nothing at all, because pruning `node_modules` silently is the right
behaviour and pruning everything goes down the same path.

An empty snapshot of a directory that really is empty stays legal and stays
exit 0: `back` to it is a real thing to want, meaning "put this directory
back to having nothing in it".  What is not legal is calling it a save when
the directory plainly has files in it and every one of them was excluded.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unedit.cli import main


class Case(unittest.TestCase):
    def setUp(self) -> None:
        # Not "…-empty-": the temp path shows up in restore output, and a test
        # looking for the word "empty" there passed on the directory name.
        self.root = tempfile.mkdtemp(prefix="unedit-vac-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel, text="x\n"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def run_cli(self, *argv):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(["--dir", self.root] + list(argv))
            except SystemExit as exit_:
                code = exit_.code if isinstance(exit_.code, int) else 2
        return code, out.getvalue(), err.getvalue()


class TestEverythingWasExcluded(Case):
    """Files are there; the snapshot got none of them."""

    def setUp(self):
        super().setUp()
        self.write("settings.py")
        self.write("src/app.py")
        self.write(".gitignore", "*\n")

    def test_it_is_not_reported_as_a_save(self):
        code, out, err = self.run_cli("save", "-m", "before the agent runs")
        self.assertNotIn("saved ", out,
                         "captured nothing and called it saved:\n" + out + err)

    def test_it_says_the_snapshot_is_empty(self):
        code, out, err = self.run_cli("save", "-m", "before the agent runs")
        self.assertIn("nothing", (out + err).lower(), out + err)

    def test_it_names_the_reason_it_got_nothing(self):
        # The person has to be able to fix it, and the fix is in a file they
        # already have.  "ignore" alone is not enough of an assertion: the
        # existing `hint: add .unedit/ to your .gitignore` line contains that
        # word and says nothing about why the snapshot came back empty.
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertIn("excluded", (out + err).lower(), out + err)
        self.assertIn("ignore", (out + err).lower(), out + err)

    def test_the_command_does_not_report_success(self):
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertNotEqual(code, 0,
                            "exit 0 — a script would carry on:\n" + out + err)

    def test_a_uneditignore_gets_the_same_treatment(self):
        os.remove(os.path.join(self.root, ".gitignore"))
        self.write(".uneditignore", "*\n")
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertNotEqual(code, 0, out + err)

    def test_the_example_it_names_is_a_file_you_would_miss(self):
        # Not `.gitignore`: it is the cause, and holding it up as the file you
        # lost reads as circular.  os.walk hits the root first, so it was.
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertIn("settings.py", out + err, out + err)

    def test_the_json_view_says_so_too(self):
        import json
        code, out, err = self.run_cli("save", "-m", "x", "--json")
        data = json.loads(out)
        self.assertEqual(data["file_count"], 0)
        self.assertTrue(data.get("empty"), data)
        self.assertTrue(data.get("nothing_captured"), data)


class TestAGenuinelyEmptyDirectory(Case):
    """Nothing was excluded — there was nothing.  This stays legal."""

    def test_it_is_allowed(self):
        code, out, err = self.run_cli("save", "-m", "baseline: empty")
        self.assertEqual(code, 0, out + err)

    def test_it_still_says_the_snapshot_is_empty(self):
        # Honest either way: `back` to this one deletes whatever is there now.
        code, out, err = self.run_cli("save", "-m", "baseline: empty")
        self.assertIn("0 files", out, out)

    def test_the_json_view_separates_it_from_the_other_case(self):
        # Both are empty snapshots; only one of them is a problem, and a script
        # deciding whether to carry on has to be able to tell which it got.
        import json
        code, out, err = self.run_cli("save", "-m", "baseline: empty", "--json")
        data = json.loads(out)
        self.assertTrue(data["empty"], data)
        self.assertFalse(data["nothing_captured"], data)

    def test_going_back_to_it_still_works(self):
        self.run_cli("save", "-m", "baseline: empty")
        self.write("generated.txt")
        code, out, err = self.run_cli("back", "--yes")
        self.assertEqual(code, 0, out + err)


class TestBackToAnEmptySnapshot(Case):
    """Older versions wrote these, so `back` has to describe one honestly."""

    def test_it_does_not_just_say_done(self):
        # Reached via a genuinely-empty directory, which is still allowed, so
        # this stays reachable no matter what `save` refuses.
        self.run_cli("save", "-m", "baseline: empty")
        self.write("generated.txt")
        code, out, err = self.run_cli("back", "--yes")
        self.assertIn("empty", (out + err).lower(),
                      "a snapshot with no files restored silently:\n" + out)


class TestARealSaveIsUnaffected(Case):

    def test_an_ordinary_save_still_says_saved(self):
        self.write("a.txt")
        code, out, err = self.run_cli("save", "-m", "fixed the parser")
        self.assertIn("saved ", out, out)
        self.assertEqual(code, 0, out + err)

    def test_a_partial_exclude_is_still_a_save(self):
        # The common, correct case: some things ignored, most things captured.
        self.write("a.txt")
        self.write("node_modules/x.js")
        self.write(".gitignore", "node_modules/\n")
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertIn("saved ", out, out)
        self.assertEqual(code, 0, out + err)

    def test_back_still_reports_what_it_restored(self):
        self.write("a.txt", "one\n")
        self.run_cli("save", "-m", "x")
        self.write("a.txt", "two\n")
        code, out, err = self.run_cli("back", "--yes")
        self.assertIn("1 restored", out, out)
        self.assertEqual(code, 0, out + err)


if __name__ == "__main__":
    unittest.main()
