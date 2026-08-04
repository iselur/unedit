"""What unedit does on a machine whose locale says ASCII.

A container with no locale set is the ordinary case, not the exotic one: it is
what CI runs on, what a Dockerfile without `ENV LANG` gives you, and what cron
hands a hook.  Python takes the locale at its word there — stdout encodes as
ASCII, and `open()` without an encoding reads and writes as ASCII too.

Both of those raise rather than degrade.  Printing an em dash — one of ours, in
a listing that has nothing to do with the project — dies halfway through with a
traceback and half a screen.  Reading back a snapshot of a project containing a
file named in anything but English dies on the manifest.  The second is the
worse one: it is a backup you cannot restore, and it was written on a machine
where it worked.

Everything here runs the real command in a real subprocess with that
environment, because the codec is chosen when the process starts and cannot be
faked from inside one.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _ascii_env():
    """The environment of a container nobody gave a locale to."""
    env = dict(os.environ)
    env.update(LC_ALL="C", LANG="C", LANGUAGE="C",
               PYTHONCOERCECLOCALE="0",   # or Python quietly upgrades C to C.UTF-8
               PYTHONUTF8="0",            # or UTF-8 mode overrides the locale
               PYTHONPATH=_ROOT)
    env.pop("PYTHONIOENCODING", None)
    return env


class TestAnAsciiMachine(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='unedit_locale_', dir='/tmp')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def run_unedit(self, *args):
        result = subprocess.run(
            [sys.executable, "-m", "unedit", "--dir", self.tmpdir] + list(args),
            capture_output=True, text=True, env=_ascii_env(), cwd=_ROOT)
        self.assertNotIn("Traceback", result.stderr,
                         "{}: {}".format(args, result.stderr))
        return result

    def write(self, name, content="x"):
        with open(os.path.join(self.tmpdir, name), "w",
                  encoding="utf-8") as fh:
            fh.write(content)

    def test_an_ordinary_project_saves_and_lists(self):
        # Nothing about this project is unusual.  The em dash is ours.
        self.write("a.py")
        self.run_unedit("save", "-m", "first")
        result = self.run_unedit("list")
        self.assertIn("first", result.stdout)

    def test_a_file_named_in_japanese_survives_a_round_trip(self):
        self.write("設定.py", "x = 1\n")
        self.run_unedit("save")
        self.assertIn("設定", self.run_unedit("show").stdout)

    def test_a_message_with_an_accent_comes_back(self):
        self.write("a.py")
        self.run_unedit("save", "-m", "café")
        self.assertIn("caf", self.run_unedit("list").stdout)

    def test_the_diff_of_a_japanese_file_does_not_stop_the_command(self):
        self.write("設定.py", "x = 1\n")
        self.run_unedit("save")
        self.write("設定.py", "x = 2\n")
        self.assertIn("設定", self.run_unedit("diff").stdout)

    def test_the_patch_shows_the_line_that_is_there(self):
        # A diff is read to decide whether to restore.  Decoding a UTF-8 source
        # file with whatever codec the locale named turns every accented word
        # in it into question marks, and the reader is then deciding about a
        # file that does not exist.
        self.write("notes.py", "# a comment\n")
        self.run_unedit("save")
        self.write("notes.py", "# naïve — and an em dash\n")
        out = self.run_unedit("diff", "--patch").stdout
        self.assertIn("naïve — and an em dash", out, out)

    def test_the_json_stays_json(self):
        self.write("設定.py")
        self.run_unedit("save")
        for args in (("list", "--json"), ("show", "--json")):
            json.loads(self.run_unedit(*args).stdout)

    def test_a_snapshot_of_a_japanese_file_restores(self):
        # The one that would be found in the worst way: at restore time.
        self.write("設定.py", "x = 1\n")
        self.run_unedit("save")
        os.remove(os.path.join(self.tmpdir, "設定.py"))
        self.run_unedit("back", "--yes")
        self.assertTrue(os.path.exists(os.path.join(self.tmpdir, "設定.py")))


if __name__ == "__main__":
    unittest.main()
