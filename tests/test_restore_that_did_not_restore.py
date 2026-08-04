"""A restore that did not restore must not report success.

`unedit back` is the undo button.  Files can refuse to come back — the
directory holding them was made read-only, the file is owned by somebody else,
the disk filled up between the plan and the copy.  The store already counts
these honestly: it knows how many files were `planned` and how many were
`restored`, and it prints `warning: N of M planned files could not be
restored`.

The CLI threw that number away and exited **0**.  So `unedit back --yes && npm
test` ran the tests against a tree that had not been put back, and a script
that checked the exit code was told the undo worked.  The warning was printed
to a human who, by the nature of an undo button, is usually not reading.

A restore that put back fewer files than it planned to is a failed command:
exit 1, which is what this tool already uses for `no snapshots found` and for
an aborted restore.  Nothing back at all is the same answer as something back
and something not — either way the tree is not the tree that was asked for.
"""

import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestARestoreThatCouldNotFinish(unittest.TestCase):

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="unedit_ro_restore_")
        self.addCleanup(self._cleanup)
        self.src = os.path.join(self.root, "src")
        os.makedirs(self.src)
        for name in ("a.txt", "b.txt"):
            self._write(os.path.join(self.src, name), "original\n")
        code, out = self._run(["save", "-m", "before"])
        self.assertEqual(code, 0, out)

    def _cleanup(self):
        try:
            os.chmod(self.src, stat.S_IRWXU)
        except OSError:
            pass
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, path, text):
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)

    def _run(self, args):
        proc = subprocess.run(
            [sys.executable, "-m", "unedit", "--dir", self.root] + list(args),
            cwd=_ROOT, capture_output=True, timeout=120,
            env=dict(os.environ, PYTHONPATH=_ROOT))
        return proc.returncode, (proc.stdout + proc.stderr).decode(
            "utf-8", "replace")

    def _seal(self):
        """Edit both files, then make the directory refuse the write back."""
        for name in ("a.txt", "b.txt"):
            self._write(os.path.join(self.src, name), "edited\n")
        os.chmod(self.src, stat.S_IRUSR | stat.S_IXUSR)

    def test_it_does_not_exit_zero(self):
        self._seal()
        code, out = self._run(["back", "--yes"])
        self.assertNotEqual(code, 0, "a restore that restored nothing said ok")
        self.assertEqual(code, 1, out)

    def test_it_still_says_what_happened(self):
        self._seal()
        _, out = self._run(["back", "--yes"])
        self.assertIn("could not be restored", out, out)
        self.assertNotIn("Traceback", out, out)

    def test_the_undo_id_is_still_offered(self):
        # The safety snapshot is the way out of a half-done restore; failing
        # the command must not stop us telling them where it is.
        self._seal()
        _, out = self._run(["back", "--yes"])
        self.assertIn("to undo: unedit back", out, out)

    def test_json_reports_both_numbers(self):
        self._seal()
        code, out = self._run(["back", "--json"])
        self.assertEqual(code, 1, out)
        payload = json.loads(out[out.index("{"):out.rindex("}") + 1])
        self.assertEqual(payload["restored"], 0, payload)
        self.assertGreater(payload["planned"], 0, payload)

    def test_a_partial_restore_is_also_a_failure(self):
        # One file back, one not.  The tree is still not what was asked for.
        self._write(os.path.join(self.src, "a.txt"), "edited\n")
        self._write(os.path.join(self.src, "b.txt"), "edited\n")
        blocked = os.path.join(self.src, "b.txt")
        os.chmod(blocked, stat.S_IRUSR)
        os.chmod(self.src, stat.S_IRUSR | stat.S_IXUSR)
        code, out = self._run(["back", "--yes"])
        os.chmod(self.src, stat.S_IRWXU)
        self.assertEqual(code, 1, out)

    def test_a_restore_that_works_still_exits_zero(self):
        # The regression guard: the ordinary undo must not start failing.
        self._write(os.path.join(self.src, "a.txt"), "edited\n")
        code, out = self._run(["back", "--yes"])
        self.assertEqual(code, 0, out)
        with open(os.path.join(self.src, "a.txt"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "original\n")

    def test_nothing_to_restore_still_exits_zero(self):
        # Nothing was planned and nothing failed; that is not a failure.
        code, out = self._run(["back", "--yes"])
        self.assertEqual(code, 0, out)


if __name__ == "__main__":
    unittest.main()
