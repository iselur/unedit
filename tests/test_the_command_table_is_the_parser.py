"""The command table in README.md, against the parser it describes.

    unedit save [-m MESSAGE] [--force]    snapshot the current directory tree
    unedit list [--json]                  snapshots: id, when, message, ...

Seven lines that tell a reader what each command takes.  Nothing compared
them with `build_parser`, and they had drifted: `save`, `back` and `drop` all
accept `--json` and none of the three said so, while an example further down
the same README runs `unedit save --json -m "json test"` and a paragraph above
it explains what `--json` does to `back`.  A reader scanning the table for the
flag that makes a command scriptable would not have found it on the three
commands where the README elsewhere assumes it.

Both directions are checked, because they fail differently.  A flag in the
table that the parser rejects is a promise that errors out the first time
anyone tries it.  A flag the parser takes that the table omits is worse in a
quieter way — the feature exists, works, and nobody knows.

The fix was not to patch three rows.  All seven commands take `--json`, so it
now reads once beneath the table alongside `--project`, which was already
handled that way — the same shape as the thing it is.

That moves the risk rather than removing it, so the flags left off every row
are excluded *by name*, each with its reason, and then two tests keep the
exclusion honest: one that every excluded flag is still promised somewhere in
the README, and one that every command really does still accept it.  Filtering
out "whatever appears on every row" instead would have made both invisible.
"""

from __future__ import annotations

import os
import re
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from unedit.cli import build_parser  # noqa: E402

README = os.path.join(_ROOT, "README.md")

# "unedit back [ID] [--yes] [--hard]     restore a snapshot (auto-saves first)"
_ROW = re.compile(r"^unedit ([a-z]+)((?: [^ ]+)*?)\s{2,}\S")
_FLAG = re.compile(r"(--?[a-z][a-z-]*)")

# Flags left out of every row on purpose, each with the reason it is left out.
# The first three are checked below to really be on every command, so this is
# an exclusion the tests keep honest rather than one they take on trust.
_EVERYWHERE = {
    "--json": "the sentence under the table says every command takes it",
    "--project": "the same sentence",
    "--dir": "the older spelling of --project, covered by the same sentence",
    "--help": "argparse adds it to every parser ever built",
    "-h": "the short spelling of the same one",
}

# The ones argparse does not supply for us, so someone has to keep them true.
_OURS = ("--json", "--project", "--dir")


def readme() -> str:
    with open(README, encoding="utf-8") as handle:
        return handle.read()


def note_under_the_table(text):
    """The paragraph that carries the flags the rows leave out."""
    start = text.find("## Commands")
    if start < 0:
        return ""
    end = text.find("```", text.find("```", start) + 3)
    rest = text[end + 3:]
    return rest[:rest.find("\n#")] if "\n#" in rest else rest


def table_rows(text):
    """{command: {flags}} exactly as the README's command table publishes it."""
    start = text.find("## Commands")
    if start < 0:
        return {}
    end = text.find("```", text.find("```", start) + 3)
    rows = {}
    for line in text[start:end].splitlines():
        found = _ROW.match(line.strip())
        if found:
            rows[found.group(1)] = set(_FLAG.findall(found.group(2)))
    return rows


def parser_commands():
    """{command: [option, ...]} the parser accepts, minus the universal ones.

    An option is its set of spellings, not one string: `--yes` and `-y` are one
    thing to a reader, and a table that names either has named it.  Comparing
    bare flags would demand every row list both.
    """
    return {command: [option for option in options
                      if not option & set(_EVERYWHERE)]
            for command, options in every_option().items()}


def every_option():
    """{command: [option, ...]} including the ones excluded from the table."""
    parser = build_parser()
    subparsers = [action for action in parser._actions
                  if hasattr(action, "choices") and action.choices
                  and hasattr(next(iter(action.choices.values())), "_actions")]
    commands = {}
    for action in subparsers:
        for name, sub in action.choices.items():
            commands[name] = [frozenset(arg.option_strings)
                              for arg in sub._actions if arg.option_strings]
    return commands


class TestTheCommandTableIsTheParser(unittest.TestCase):

    def setUp(self):
        self.rows = table_rows(readme())
        self.parser = parser_commands()

    def test_the_readme_still_has_a_command_table(self):
        # Every comparison below is vacuous against an empty table.
        self.assertGreaterEqual(len(self.rows), 5,
                                "no command table found in README.md")

    def test_the_parser_still_has_subcommands(self):
        self.assertGreaterEqual(len(self.parser), 5,
                                "the parser introspection found nothing — the "
                                "reader below would pass against anything")

    def test_the_table_lists_the_commands_that_exist(self):
        self.assertEqual(sorted(self.rows), sorted(self.parser))

    def test_every_flag_in_the_table_is_one_the_parser_takes(self):
        for command, flags in sorted(self.rows.items()):
            known = set().union(*self.parser.get(command, [set()]) or [set()])
            extra = flags - known - set(_EVERYWHERE)
            self.assertFalse(
                extra,
                "README.md offers `unedit {} {}` and the parser rejects it"
                .format(command, " ".join(sorted(extra))))

    def test_every_flag_the_parser_takes_is_one_the_table_lists(self):
        # Reported together rather than one command at a time: the same flag
        # going missing from three rows is one edit to make, and finding out
        # about it a row per run is three.
        undocumented = []
        for command, options in sorted(self.parser.items()):
            listed = self.rows.get(command, set())
            for option in options:
                if not option & listed:
                    undocumented.append("unedit {} {}"
                                        .format(command, sorted(option)[0]))
        self.assertFalse(
            undocumented,
            "these work and the README's command table does not mention them:"
            "\n  " + "\n  ".join(undocumented))

    def test_the_universal_flags_really_are_universal(self):
        # The table leaves them off every row because one sentence covers them
        # all.  That sentence is only true while every command still takes
        # them, and the day one stops is the day the table starts lying about
        # a command with no row of its own to correct.
        for command, options in sorted(every_option().items()):
            spellings = set().union(*options) if options else set()
            for flag in _OURS:
                self.assertIn(
                    flag, spellings,
                    "`unedit {} {}` is not accepted, but README.md says all "
                    "commands take it".format(command, flag))

    def test_the_universal_flags_are_still_promised_somewhere(self):
        # They are excluded above by name.  Without this, deleting the sentence
        # that documents them would leave them documented nowhere and the
        # comparison would not notice.
        # Scoped to the paragraph under the table, not the whole file.  Both
        # flags turn up elsewhere in the README — in an example, in the note
        # about `back` — so searching the whole thing would go on passing after
        # the one sentence that makes them universal was deleted.
        note = note_under_the_table(readme())
        for flag in _OURS:
            self.assertIn(
                flag, note,
                "the paragraph under the command table no longer names {}, and "
                "the rows leave it out because {}"
                .format(flag, _EVERYWHERE[flag]))


if __name__ == "__main__":
    unittest.main()
