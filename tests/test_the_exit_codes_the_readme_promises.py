"""The exit codes the README promises, from real runs of the real command.

    Exit codes: `0` fine, `1` the command failed, `2` usage error, `130`
    stopped by ctrl-c, `141` the reader hung up.

Two of those already have tests, because producing them means sending
signals (test_interrupt, test_broken_pipe), and the partial-restore case has
its own (test_restore_that_did_not_restore).  Everything else was prose next
to code: nothing ran the command for each ordinary case, and nothing read
the README's own sentence.

The distinction that matters here is 1 against 2.  `2` is what argparse
returns for a command line that does not parse, so it means *you typed
something wrong* — a script that sees 2 should stop and not retry, and a
person who sees 2 should look at what they typed.  `1` means the command was
well-formed and did not work.  Running out of snapshots is the second thing:
the command line was fine, the store is simply empty.  cli.py says so in as
many words, at the two places that special-case it.

The empty store is checked across every command that can hit it, not once,
because the codes drifted apart exactly there — the special case was written
into `back` and `diff` and never into `show`, so the same condition with the
same message answered 1 twice and 2 once.
"""

from __future__ import annotations

import ast
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

README = os.path.join(_ROOT, "README.md")
CLI_SOURCE = os.path.join(_ROOT, "unedit", "cli.py")

# "Exit codes: `0` fine, `1` the command failed, `2` usage error, `130` ..."
_DOCUMENTED = re.compile(r"`(\d{1,3})`")

# Commands that reach an empty store as a plain empty-store condition rather
# than as a usage error.  `drop` is not here: with no id and no --all it has
# not been told what to remove, which is a usage error whatever the store
# holds.  `list`, `where` and `save` all succeed on an empty store.
EMPTY_STORE_COMMANDS = ("show", "diff", "back")


def readme() -> str:
    with open(README, encoding="utf-8") as handle:
        return handle.read()


def documented_codes(text):
    """The codes the README's exit-code sentence lists."""
    start = text.find("Exit codes:")
    if start < 0:
        return set()
    end = text.find("\n- ", start)
    return {int(code) for code in _DOCUMENTED.findall(text[start:end])}


def source_codes():
    """Every constant exit code cli.py produces."""
    with open(CLI_SOURCE, encoding="utf-8") as handle:
        tree = ast.parse(handle.read())
    codes = set()
    for node in ast.walk(tree):
        value = None
        if isinstance(node, ast.Return):
            value = node.value
        elif (isinstance(node, ast.Call)
              and getattr(node.func, "attr", None) == "exit"):
            value = node.args[0] if node.args else None
        if (isinstance(value, ast.Constant)
                and isinstance(value.value, int)
                and not isinstance(value.value, bool)):
            codes.add(value.value)
        # `_err(msg, code=1)` is the other way a code is chosen.
        if isinstance(node, ast.Call) and getattr(node.func, "id", None) == "_err":
            for keyword in node.keywords:
                if (keyword.arg == "code"
                        and isinstance(keyword.value, ast.Constant)):
                    codes.add(keyword.value.value)
    return codes


class TestTheExitCodesTheREADMEPromises(unittest.TestCase):
    def setUp(self):
        self.project = tempfile.mkdtemp(prefix="ue-exitcode-")
        self.addCleanup(shutil.rmtree, self.project, ignore_errors=True)
        with open(os.path.join(self.project, "a.py"), "w") as handle:
            handle.write("x = 1\n")

    def run_cli(self, *argv, cwd=None):
        return subprocess.run(
            [sys.executable, "-m", "unedit", *argv],
            cwd=cwd or self.project, capture_output=True, text=True,
            env=dict(os.environ, PYTHONPATH=_ROOT))

    def test_the_readme_still_promises_exit_codes(self):
        # Without this the comparison below passes on an empty set, which is
        # what deleting the sentence looks like.
        self.assertGreaterEqual(len(documented_codes(readme())), 4,
                                "no exit-code sentence left in README.md")

    def test_the_documented_codes_are_the_ones_the_code_can_return(self):
        self.assertEqual(
            sorted(documented_codes(readme())), sorted(source_codes()),
            "README.md's exit codes and the ones unedit/cli.py returns "
            "disagree")

    def test_a_save_that_worked_is_zero(self):
        proc = self.run_cli("save", "-m", "first")
        self.assertEqual(proc.returncode, 0,
                         "an ordinary save did not exit 0:\n"
                         + proc.stdout + proc.stderr)

    def test_an_unknown_flag_is_two(self):
        proc = self.run_cli("save", "--not-a-flag")
        self.assertEqual(proc.returncode, 2,
                         "an unknown flag did not exit 2:\n"
                         + proc.stdout + proc.stderr)

    def test_a_snapshot_id_that_does_not_exist_is_two(self):
        # This one really is a usage error: the store is fine and the id
        # given is not in it, so what was wrong was what got typed.
        self.run_cli("save", "-m", "first")
        proc = self.run_cli("show", "no-such-snapshot")
        self.assertEqual(proc.returncode, 2,
                         "an unknown snapshot id did not exit 2:\n"
                         + proc.stdout + proc.stderr)

    def test_an_empty_store_is_one_whichever_command_asked(self):
        # Same condition, same message, so it has to be the same number.  A
        # wrapper doing `unedit diff || bail` and one doing `unedit show ||
        # bail` are asking the store the same question.
        codes = {}
        for command in EMPTY_STORE_COMMANDS:
            argv = [command] + (["--yes"] if command == "back" else [])
            proc = self.run_cli(*argv)
            codes[command] = proc.returncode
            self.assertIn("no snapshots", (proc.stdout + proc.stderr).lower(),
                          "{} on an empty store said something else:\n{}"
                          .format(command, proc.stdout + proc.stderr))
        self.assertEqual(
            codes, {command: 1 for command in EMPTY_STORE_COMMANDS},
            "an empty store is not a usage error — nothing was typed wrong, "
            "there is simply nothing saved yet")

    def test_the_empty_store_is_not_confused_with_a_bad_id(self):
        # The two have to stay apart: one says "save something first" and the
        # other says "that id is not here".  Both on the same command.
        empty = self.run_cli("show")
        self.run_cli("save", "-m", "first")
        bad_id = self.run_cli("show", "no-such-snapshot")
        self.assertNotEqual(empty.returncode, bad_id.returncode,
                            "an empty store and an unknown id answer the same "
                            "code, so a script cannot tell them apart")


if __name__ == "__main__":
    unittest.main()
