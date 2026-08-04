"""One family, one word for "that directory over there".

These five tools install together with a single `pip install 'stillworks[all]'`
and are documented as a family, which sets an expectation that a flag learned
in one of them means the same thing in the next.  `--project DIR` was the word
in stillworks; here the same idea was spelled `--dir DIR`, so `unedit --project
build save` did not point at a directory — it stopped with a usage screen
listing the subcommands, which reads as "you typed a command I don't have"
rather than "I call that flag something else".

`--dir` keeps working; anything already scripted against it is untouched.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestProjectIsAcceptedAsWellAsDir(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="unedit_alias_")
        self.project = os.path.join(self.tmp, "app")
        self.elsewhere = os.path.join(self.tmp, "elsewhere")
        os.makedirs(self.project)
        os.makedirs(self.elsewhere)
        with open(os.path.join(self.project, "a.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("value = 1\n")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_unedit(self, *args):
        """Run from ``elsewhere``, so only the flag can find the project."""
        env = dict(os.environ, PYTHONPATH=_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "unedit"] + list(args),
            capture_output=True, text=True, encoding="utf-8",
            cwd=self.elsewhere, env=env, timeout=60)

    def test_project_saves_into_the_named_directory(self):
        result = self.run_unedit("--project", self.project, "save")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(
            os.path.isdir(os.path.join(self.project, ".unedit")),
            result.stdout + result.stderr)
        self.assertFalse(
            os.path.isdir(os.path.join(self.elsewhere, ".unedit")),
            "it saved next to the shell instead of into the project")

    def test_project_works_after_the_subcommand_too(self):
        result = self.run_unedit("save", "--project", self.project)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.project, ".unedit")),
                        result.stdout + result.stderr)

    def test_list_sees_what_project_saved(self):
        self.run_unedit("--project", self.project, "save")
        result = self.run_unedit("--project", self.project, "list")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("1 files", result.stdout + result.stderr,
                      result.stdout + result.stderr)

    def test_dir_still_means_exactly_the_same_thing(self):
        # The alias is an addition.  Anything already scripted against --dir
        # has to keep working, including in the position it was written in.
        result = self.run_unedit("--dir", self.project, "save")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.project, ".unedit")),
                        result.stdout + result.stderr)

    def test_naming_both_is_not_a_crash(self):
        # Somebody will do it, if only by editing a script halfway.  Whatever
        # it decides, it must not be a traceback.
        result = self.run_unedit("--dir", self.project,
                                 "--project", self.project, "save")
        self.assertNotIn("Traceback", result.stderr, result.stderr)

    def test_a_project_that_does_not_exist_says_which_one(self):
        missing = os.path.join(self.tmp, "no-such-dir")
        result = self.run_unedit("--project", missing, "save")
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        self.assertIn("no-such-dir", result.stdout + result.stderr,
                      result.stdout + result.stderr)

    def test_the_help_mentions_both_spellings(self):
        # A flag nobody can find is not much of an alias.
        result = self.run_unedit("--help")
        self.assertIn("--project", result.stdout, result.stdout)
        self.assertIn("--dir", result.stdout, result.stdout)


if __name__ == "__main__":
    unittest.main()
