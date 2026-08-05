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
            code = main(["--dir", self.root] + list(argv))
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


class TestTheReasonIsTheRuleThatActuallyMatched(Case):
    """Which rule left the tree out, rather than which rule files exist.

    The reason used to be worked out a second time, after the walk, by a
    caller that could only see what was on disk: it named every ignore file
    present whether or not that file had anything to do with it, and it had no
    way to name a default exclusion at all when one was there too.  The person
    is being sent to a file to edit a line, so naming the wrong file costs them
    the whole trip.  These four pin the four answers apart.
    """

    def test_it_names_the_ignore_file_the_pattern_came_from(self):
        # Both files exist and only one of them excludes anything.  The old
        # answer named both, in a fixed order, with `or` between them.
        self.write("keep.py")
        self.write(".gitignore", "# unrelated\n")
        self.write(".uneditignore", "*\n")
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertIn(".uneditignore", out + err, out + err)
        self.assertNotIn(".gitignore", out + err, out + err)

    def test_the_other_way_round_names_the_other_file(self):
        # The same fixture with the two contents swapped, because a test of one
        # of them alone passes on code that always names that one.
        self.write("keep.py")
        self.write(".gitignore", "*\n")
        self.write(".uneditignore", "# unrelated\n")
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertIn(".gitignore", out + err, out + err)
        self.assertNotIn(".uneditignore", out + err, out + err)

    def test_it_quotes_the_line_you_have_to_go_and_change(self):
        # "excluded by .gitignore" is a file with n lines in it.  The pattern
        # is the line, and it is quoted the way this family prints anything
        # that came off disk: it is a line out of a file in the tree being
        # snapshotted, which is a file the thing being audited can rewrite.
        self.write("keep.py")
        # The second line is there so the tree really does come back empty —
        # an ignore file is itself a file, and a pattern that does not match it
        # leaves it in the snapshot.
        self.write(".gitignore", "*.py\n.gitignore\n")
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertIn("*.py", out + err, out + err)

    def test_when_both_files_match_it_names_the_one_that_is_read_first(self):
        # Two ignore files can both exclude the same thing, and then there is
        # no true answer to "which one did it" — only a stable one.  The order
        # they are read in is the order they are listed in, and the first match
        # wins, so the sentence is the same on every run and on every machine.
        # Without that, the person is sent to one file today and the other one
        # tomorrow for the same tree.
        self.write("keep.py")
        self.write(".gitignore", "*.py\n.gitignore\n.uneditignore\n")
        self.write(".uneditignore", "*\n")
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertIn("*.py", out + err, out + err)
        self.assertNotIn(".uneditignore", out + err, out + err)

    def test_a_pattern_that_drives_the_terminal_is_escaped_not_obeyed(self):
        # The pattern is a line out of a file in the tree being snapshotted,
        # which is a file whatever is being audited can write.  It is printed
        # the way this family prints anything off disk: escaped and quoted, so
        # it stays findable, rather than blanked into a line that names no line.
        self.write("\x1bboom.txt")
        self.write(".gitignore", "\x1b*\n.gitignore\n")
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertIn("\\x1b*", out + err, repr(out + err))
        self.assertNotIn("\x1b", out + err, repr(out + err))

    def test_the_example_is_never_this_tool_s_own_directory(self):
        # Second save into the same tree: `.unedit` is there now, and it is
        # excluded like everything else.  Held up as the file you lost it is
        # both wrong and alarming — it is the snapshots themselves — and it
        # outranks an ignore file, so it would win.
        self.write(".gitignore", "*\n")
        self.run_cli("save", "-m", "first")
        self.assertTrue(os.path.isdir(os.path.join(self.root, ".unedit")))
        code, out, err = self.run_cli("save", "-m", "second")
        example = [ln for ln in (out + err).splitlines() if "e.g." in ln]
        self.assertEqual(len(example), 1, out + err)
        self.assertNotIn(".unedit", example[0], example[0])
        self.assertIn(".gitignore", example[0], example[0])

    def test_a_default_exclusion_says_so_and_names_no_file(self):
        # `node_modules` is out by this tool's own rules.  An ignore file
        # sitting next to it is not the reason, and sending somebody there to
        # delete a line that is not in it is worse than saying nothing.
        self.write("node_modules/x.js")
        # It excludes only itself, so it is present without being the reason
        # for anything else — which is the state the old answer could not tell
        # apart from being the reason.
        self.write(".gitignore", ".gitignore\n")
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertNotEqual(code, 0, out + err)
        self.assertIn("default", (out + err).lower(), out + err)
        self.assertNotIn("by .gitignore", out + err, out + err)


class TestNothingWasExcludedAndNothingCouldBeRead(Case):
    """The other way to end up with an empty snapshot of a full directory.

    No ignore file, no exclusion — the files are simply unreadable, so every
    one of them lands in `skipped` and none of them lands in the snapshot.  The
    person is in exactly the position this whole file is about: they ran `save`
    to have something to go back to, and there is nothing there.  A check that
    only looks at what was *excluded* misses this one entirely.
    """

    def setUp(self):
        super().setUp()
        if os.geteuid() == 0:
            self.skipTest("root reads files whose mode says it may not")
        self.write("settings.py")
        os.chmod(os.path.join(self.root, "settings.py"), 0)
        self.addCleanup(os.chmod, os.path.join(self.root, "settings.py"), 0o600)

    def test_the_json_view_says_nothing_was_captured(self):
        import json
        code, out, err = self.run_cli("save", "-m", "x", "--json")
        data = json.loads(out)
        self.assertEqual(data["file_count"], 0, data)
        self.assertTrue(data.get("nothing_captured"), data)

    def test_it_names_the_file_it_could_not_read(self):
        code, out, err = self.run_cli("save", "-m", "x")
        self.assertIn("settings.py", out + err, out + err)


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
