"""A project root that does not exist is a typo, not a request to create one.

Every command starts by joining `.unedit` onto the project root, and the
directory-making was unconditional, so a mistyped `--dir` built the whole
missing tree and snapshotted the empty directory it had just made — and said
`saved`, with a snapshot ID, like any other successful run.  Where the path
happened not to be writable it failed instead, with `Permission denied: '/no'`:
the topmost missing component, which is not a path anybody typed and does not
point at the mistake.

The distinction is the same one agentwatch draws about `HOME`.  A directory
somebody *named* is one they meant, so getting it wrong is worth stopping over
by name.  The default here is the current directory, which exists by
definition, so this can only ever fire on a path that was typed.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

_COMMANDS = ["save", "list", "show", "back", "diff", "drop", "where"]


class TestAProjectRootThatIsNotThere(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="unedit_missing_")
        self.missing = os.path.join(self.tmp, "typoo")
        self.here = os.path.join(self.tmp, "here")
        os.makedirs(self.here)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_unedit(self, *args):
        env = dict(os.environ, PYTHONPATH=_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "unedit"] + list(args),
            capture_output=True, text=True, encoding="utf-8",
            cwd=self.here, env=env, timeout=60)

    def test_it_does_not_create_the_directory(self):
        self.run_unedit("--dir", self.missing, "save")
        self.assertFalse(os.path.exists(self.missing),
                         "a mistyped --dir built the directory it named")

    def test_it_is_an_error_and_not_a_saved_snapshot(self):
        result = self.run_unedit("--dir", self.missing, "save")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertNotIn("saved", result.stdout.lower(), result.stdout)

    def test_the_message_names_the_path_that_was_typed(self):
        # `Permission denied: '/no'` names the topmost missing component, which
        # is not what anybody wrote and does not point at the mistake.
        result = self.run_unedit("--dir", self.missing, "save")
        self.assertIn("typoo", result.stdout + result.stderr,
                      result.stdout + result.stderr)

    def test_every_command_agrees(self):
        # Not just `save`.  A read-only command that answers "no snapshots yet"
        # for a directory that is not there reads as an empty project rather
        # than a wrong path.
        for command in _COMMANDS:
            with self.subTest(command=command):
                result = self.run_unedit("--dir", self.missing, command)
                self.assertEqual(result.returncode, 2,
                                 result.stdout + result.stderr)
                self.assertNotIn("Traceback", result.stderr, result.stderr)

    def test_the_project_spelling_is_checked_too(self):
        result = self.run_unedit("--project", self.missing, "save")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertFalse(os.path.exists(self.missing), result.stdout)

    def test_a_file_where_a_directory_should_be_says_so(self):
        # The other way to be wrong about a path, and it deserves its own
        # words: "no such directory" would be a lie about a file that is there.
        path = os.path.join(self.tmp, "a-file")
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("not a directory\n")
        result = self.run_unedit("--dir", path, "save")
        self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
        self.assertIn("not a directory",
                      (result.stdout + result.stderr).lower(),
                      result.stdout + result.stderr)

    def test_a_directory_that_is_there_still_works(self):
        # The other half: an ordinary run must be untouched.
        with open(os.path.join(self.here, "a.py"), "w",
                  encoding="utf-8") as fh:
            fh.write("value = 1\n")
        result = self.run_unedit("--dir", self.here, "save")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(os.path.isdir(os.path.join(self.here, ".unedit")),
                        result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
