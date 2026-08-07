"""`--json` has to hold when the answer is bad news.

A script that passes `--json` reads stdout and calls `json.loads` on it.  Every
failure used to write a sentence to stderr and nothing at all to stdout, so the
script got `''` and raised `JSONDecodeError: Expecting value: line 1 column 1` --
a traceback naming our output rather than our error, at the one moment a program
most needs to be told what went wrong.

So the checks here are the two halves of one promise:

  * asked in JSON, every failure answers in JSON -- on stdout, parseable, with
    `error` in it and the exit code it always had; and
  * asked in words, every failure still answers in words on stderr, and leaves
    stdout empty, so `unedit list > snapshots.json` does not quietly collect a
    sentence.

Run as real commands rather than through `main()`.  Which stream a line goes to
is the whole subject, and a test holding one buffer for both cannot see it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import shutil
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Every way a command can stop, with the code it carries and whether it needs a
# store with something in it.  1 is "nothing to report on", which `show`, `back`
# and `diff` all say about an empty store; 2 is "you typed something wrong".
#
# The bad-id cases need a snapshot saved first: asked for `nosuchid` in an empty
# store, unedit answers the larger truth -- there is nothing here at all -- and
# the id was never looked at.
THE_FAILURES = [
    ("no snapshots to show", ["show"], 1, False),
    ("no snapshots to go back to", ["back", "--yes"], 1, False),
    ("no snapshots to diff against", ["diff"], 1, False),
    ("drop with neither an id nor --all", ["drop"], 2, False),
    ("show an id that is not there", ["show", "nosuchid"], 2, True),
    ("drop an id that is not there", ["drop", "nosuchid"], 2, True),
    ("back to an id that is not there", ["back", "nosuchid", "--yes"], 2, True),
]

# The seventh caller, and the likeliest of all of them: a mistyped directory.
# It is checked separately because it needs a path that is not there.
A_MISSING_DIRECTORY = ["save"]


class _RunsUnedit(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, True)

    def run_unedit(self, *argv, directory=None):
        result = subprocess.run(
            [sys.executable, "-m", "unedit", "--project",
             self.tmp if directory is None else directory] + list(argv),
            cwd=_ROOT, capture_output=True, text=True, timeout=60,
            env=dict(os.environ, PYTHONPATH=_ROOT))
        return result

    def given_one_snapshot(self):
        """A store with something in it, so a bad id is the thing that fails."""
        with open(os.path.join(self.tmp, "a.txt"), "w") as fh:
            fh.write("hi\n")
        saved = self.run_unedit("save", "-m", "one")
        self.assertEqual(saved.returncode, 0, saved.stdout + saved.stderr)

    def failing(self, argv, populated):
        if populated:
            self.given_one_snapshot()
        return self.run_unedit(*argv)

    def failing_in_json(self, argv, populated):
        if populated:
            self.given_one_snapshot()
        return self.run_unedit(*argv, "--json")


class TestAskedInJsonItAnswersInJson(_RunsUnedit):

    def test_every_failure_puts_a_document_on_stdout(self):
        for name, argv, code, populated in THE_FAILURES:
            with self.subTest(name):
                result = self.failing_in_json(argv, populated)
                self.assertEqual(result.returncode, code,
                                 result.stdout + result.stderr)
                # The assertion the bug was: `json.loads('')`.
                document = json.loads(result.stdout)
                self.assertIn("error", document)
                self.assertTrue(document["error"].strip(),
                                "the error document says nothing")

    def test_a_directory_that_is_not_there_answers_in_json_too(self):
        missing = os.path.join(self.tmp, "nope")
        result = self.run_unedit(*A_MISSING_DIRECTORY, "--json",
                                 directory=missing)
        self.assertEqual(result.returncode, 2)
        document = json.loads(result.stdout)
        self.assertIn("no such directory", document["error"])
        self.assertIn(missing, document["error"])

    def test_the_json_failure_says_the_same_sentence_the_words_do(self):
        """One message, in two shapes -- not two messages."""
        for name, argv, _, populated in THE_FAILURES:
            with self.subTest(name):
                spoken = self.failing(argv, populated).stderr.strip()
                written = json.loads(
                    self.failing_in_json(argv, populated).stdout)["error"]
                self.assertEqual(spoken, "unedit: {}".format(written))

    def test_nothing_but_the_document_lands_on_stdout(self):
        # A stray print alongside it and `json.loads` raises again, with the
        # error document sitting right there in the string it could not read.
        for name, argv, _, populated in THE_FAILURES:
            with self.subTest(name):
                out = self.failing_in_json(argv, populated).stdout
                self.assertEqual(out.strip(), json.dumps(
                    json.loads(out), indent=2).strip())


class TestAskedInWordsItStillAnswersInWords(_RunsUnedit):

    def test_every_failure_names_the_tool_on_stderr(self):
        for name, argv, code, populated in THE_FAILURES:
            with self.subTest(name):
                result = self.failing(argv, populated)
                self.assertEqual(result.returncode, code)
                # `unedit:` and not `error:`.  Five commands install together,
                # and in a log with several of them running a line beginning
                # `error:` does not say who is talking.
                self.assertTrue(result.stderr.startswith("unedit: "),
                                result.stderr)

    def test_stdout_stays_empty_so_a_redirect_collects_nothing(self):
        for name, argv, _, populated in THE_FAILURES:
            with self.subTest(name):
                # `save` prints when it succeeds, so what is checked is what the
                # *failing* command added to stdout, not the whole run.
                if populated:
                    self.given_one_snapshot()
                self.assertEqual(self.run_unedit(*argv).stdout, "")


class TestTheTwoShapesAreOneDecision(_RunsUnedit):
    """There is one place that knows how unedit says it stopped."""

    #: The one function allowed to say unedit stopped, being the one that
    #: decides which shape it says it in.
    THE_ONE_PLACE = "_failed"

    #: The word it puts in front.  Written anywhere else, somebody is doing
    #: `_failed`'s job by hand -- and doing the `--json` half of it wrong.
    THE_PREFIX = "unedit: "

    def test_only_one_function_writes_the_prefix(self):
        """The prefix is the tell, and stderr on its own is not.

        `unedit list` prints a note about damaged snapshots to stderr and it is
        right to: the answer went to stdout, the JSON one carries `damaged` on
        every entry it applies to, and the note is a human's copy of a fact the
        document already holds.  Nothing was lost by a caller reading stdout,
        which is what `_failed` exists to prevent.

        A line starting `unedit: ` is different.  That is the shape of stopping,
        and there is one function that gets to decide whether it goes out as a
        sentence or as a document.  The regression this catches is the cheap
        one: a new command, and the line above it copied.
        """
        import ast
        with open(os.path.join(_ROOT, "unedit", "cli.py"),
                  encoding="utf-8") as fh:
            tree = ast.parse(fh.read())
        elsewhere = [node for node in tree.body
                     if not (isinstance(node, ast.FunctionDef)
                             and node.name == self.THE_ONE_PLACE)]
        self.assertLess(len(elsewhere), len(tree.body),
                        "cli.py has no {}() -- it was renamed or removed, and "
                        "this check has been passing over nothing"
                        .format(self.THE_ONE_PLACE))
        for top in elsewhere:
            for node in ast.walk(top):
                if isinstance(node, ast.Constant) and isinstance(node.value, str):
                    self.assertNotIn(
                        self.THE_PREFIX, node.value,
                        "cli.py line {} writes {!r} itself -- call {}() so a "
                        "caller that asked for --json is told too"
                        .format(node.lineno, self.THE_PREFIX,
                                self.THE_ONE_PLACE))

    def test_every_command_takes_the_flag_this_reads(self):
        """What lets `_failed` say `args.json` and not guess at a default.

        A subcommand added without `--json` would give `_failed` a namespace
        with no such attribute, and the failure it was called about would be
        replaced by an `AttributeError` -- so the flag being on all of them is
        not a nicety, it is the thing that makes one line of `_failed` safe.

        Written as a default (`getattr(args, 'json', False)`) it was a branch
        nothing could reach, which is a worse place to keep the fact: no test
        can tell you when it stops being true.
        """
        import argparse
        sys.path.insert(0, _ROOT)
        from unedit.cli import build_parser
        parser = build_parser()
        commands = [action.choices for action in parser._actions
                    if isinstance(action, argparse._SubParsersAction)][0]
        self.assertTrue(commands, "unedit has no subcommands any more")
        for name, subparser in sorted(commands.items()):
            with self.subTest(name):
                flags = {option for action in subparser._actions
                         for option in action.option_strings}
                self.assertIn("--json", flags,
                              "`unedit {}` does not take --json, so _failed() "
                              "reading args.json would raise on it"
                              .format(name))

    def test_the_one_place_really_does_write_it(self):
        """Else the check above is a grep for a string nothing produces."""
        result = self.run_unedit("show")
        self.assertTrue(result.stderr.startswith(self.THE_PREFIX),
                        "nothing writes {!r} any more"
                        .format(self.THE_PREFIX))


if __name__ == "__main__":
    unittest.main()
