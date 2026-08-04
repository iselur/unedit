"""`unedit diff | head` is a normal thing to do, and it used to be a crash.

A diff against a snapshot of a whole tree is long, so it gets piped: into
`head` for the first few files, into `less` and quit with `q`, into `grep -q`
that stops as soon as it has an answer.  Each of those closes the read end
while we are still writing.  The next write fails with EPIPE, Python raises
`BrokenPipeError`, and unhandled the interpreter prints

    Exception ignored in: <_io.TextIOWrapper name='<stdout>' ...>
    BrokenPipeError: [Errno 32] Broken pipe

over the output and exits 120 — or, when the error escapes `main()` rather
than the shutdown flush, a full Python traceback.  `show`, `diff` and `diff
--patch` all did the traceback.  That reads especially badly out of this tool:
people reach for it when something has already gone wrong, and a crash from
the safety net is the last thing they need to see.

141 is 128 + SIGPIPE, the shell's own spelling of "the reader hung up", the
same way 130 spells ctrl-c — deliberately not one of the answers, because a
listing that got cut off told you nothing about your snapshots.

The read end is closed before the command writes a byte, so none of this
depends on how much output there is or on the size of the pipe buffer.
"""

import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)


def _env():
    return dict(os.environ, PYTHONPATH=_ROOT)


def run_with_no_reader(args):
    """Run the CLI with a stdout pipe whose read end is already closed."""
    read_fd, write_fd = os.pipe()
    os.close(read_fd)                       # the reader went away
    proc = subprocess.Popen(
        [sys.executable, "-m", "unedit"] + list(args),
        stdout=write_fd, stderr=subprocess.PIPE, cwd=_ROOT, env=_env())
    os.close(write_fd)
    _, err = proc.communicate(timeout=180)
    return proc.returncode, err.decode("utf-8", "replace")


def run_normally(args):
    proc = subprocess.Popen(
        [sys.executable, "-m", "unedit"] + list(args),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, cwd=_ROOT, env=_env())
    out, err = proc.communicate(timeout=180)
    return (proc.returncode,
            out.decode("utf-8", "replace"),
            err.decode("utf-8", "replace"))


class TestTheReaderHungUp(unittest.TestCase):

    def setUp(self):
        self.project = tempfile.mkdtemp(prefix="unedit_epipe_")
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        src = os.path.join(self.project, "src")
        os.makedirs(src)
        for i in range(60):
            with open(os.path.join(src, "mod{}.py".format(i)), "w",
                      encoding="utf-8") as fh:
                fh.write("VALUE = {}\n".format(i) * 20)
        code, out, err = run_normally(
            ["--dir", self.project, "save", "-m", "before"])
        self.assertEqual(code, 0, out + err)
        # Something to diff against, so `diff` has real output to be cut off.
        for i in range(0, 60, 2):
            with open(os.path.join(src, "mod{}.py".format(i)), "w",
                      encoding="utf-8") as fh:
                fh.write("VALUE = {}\n".format(i + 1000) * 20)

    def commands(self):
        d = ["--dir", self.project]
        return [
            d + ["list"],
            d + ["where"],
            d + ["show"],
            d + ["diff"],
            d + ["diff", "--patch"],
            ["--version"],
            ["--help"],
        ]

    def test_nothing_is_printed_about_a_broken_pipe(self):
        for args in self.commands():
            with self.subTest(args=args[-2:]):
                _, err = run_with_no_reader(args)
                self.assertNotIn("BrokenPipeError", err, err)
                self.assertNotIn("Exception ignored", err, err)

    def test_it_is_not_a_traceback(self):
        for args in self.commands():
            with self.subTest(args=args[-2:]):
                _, err = run_with_no_reader(args)
                self.assertNotIn("Traceback", err, err)

    def test_the_exit_code_says_the_reader_hung_up(self):
        for args in self.commands():
            with self.subTest(args=args[-2:]):
                code, err = run_with_no_reader(args)
                self.assertEqual(code, 141,
                                 "{} -> {}\n{}".format(args[-2:], code, err))

    def test_help_and_version_are_covered_too(self):
        # argparse prints these and exits before any command body runs.
        for args in (["--version"], ["--help"]):
            with self.subTest(args=args):
                code, err = run_with_no_reader(args)
                self.assertEqual(code, 141, err)
                self.assertEqual(err, "", err)

    def test_a_reader_that_stays_still_gets_the_real_answer(self):
        code, out, err = run_normally(["--dir", self.project, "diff"])
        self.assertEqual(code, 0, err)
        self.assertIn("mod0.py", out, out)

    def test_the_listing_still_lists(self):
        code, out, err = run_normally(["--dir", self.project, "list"])
        self.assertEqual(code, 0, err)
        self.assertIn("before", out, out)


if __name__ == "__main__":
    unittest.main()
