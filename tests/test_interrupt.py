"""What happens when somebody presses ctrl-c.

Snapshotting a large tree takes a moment, and a moment is long enough to change
your mind in.  Interrupting is an ordinary thing to do to a command that is
taking longer than you expected — it should not be answered with twenty lines of
interpreter internals ending in ``KeyboardInterrupt``, which reads as a crash,
and reads *especially* badly here: this is the tool people reach for when
something has already gone wrong, so a traceback from it looks like the safety
net tearing.

The exit code carries the other half of it.  `unedit save && rm -rf build` must
not delete anything on the strength of a snapshot that was never finished.  130
is the shell's own way of spelling "stopped by ctrl-c", which is what happened.
"""

import io
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unedit import cli  # noqa: E402

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestCtrlC(unittest.TestCase):

    def setUp(self):
        self.real = {name: getattr(cli, name)
                     for name in ("cmd_save", "cmd_list", "cmd_diff")}

    def tearDown(self):
        for name, fn in self.real.items():
            setattr(cli, name, fn)

    def _interrupt(self, name):
        def boom(*args, **kwargs):
            raise KeyboardInterrupt
        setattr(cli, name, boom)

    def _code_for(self, args):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = cli.main(args)
        return code, out.getvalue() + err.getvalue()

    def test_an_abandoned_save_does_not_report_success(self):
        # `unedit save && rm -rf build` is the shape this protects.
        self._interrupt("cmd_save")
        code, _ = self._code_for(["save"])
        self.assertEqual(code, 130)

    def test_it_does_not_print_a_traceback(self):
        # A traceback out of the undo tool looks like the net tearing.
        self._interrupt("cmd_save")
        _, text = self._code_for(["save"])
        self.assertNotIn("Traceback", text)

    def test_the_other_commands_answer_the_same_way(self):
        for name, args in (("cmd_list", ["list"]), ("cmd_diff", ["diff"])):
            self._interrupt(name)
            code, _ = self._code_for(args)
            self.assertEqual(code, 130, args)

    def test_the_real_command_line_agrees(self):
        # In process is where the assertion is precise; this one runs the module
        # entry point for real, because that is where the guard gets bypassed.
        # `main` hands its code back now instead of raising it, so a
        # `__main__.py` that calls `main()` and drops the answer exits 0 no
        # matter what happened -- and that is not hypothetical, one of the five
        # was written that way.
        env = dict(os.environ, PYTHONPATH=_ROOT)
        proc = subprocess.Popen(
            [sys.executable, "-c",
             "import runpy, sys;"
             "from unedit import cli;"
             "cli.cmd_list = lambda *a, **k: (_ for _ in ()).throw("
             "KeyboardInterrupt());"
             "sys.argv = ['unedit', 'list'];"
             "runpy.run_module('unedit', run_name='__main__')"],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env, cwd=_ROOT)
        _, err = proc.communicate(timeout=60)
        self.assertEqual(proc.returncode, 130, err.decode("utf-8", "replace"))
        self.assertNotIn(b"Traceback", err)


if __name__ == "__main__":
    unittest.main()
