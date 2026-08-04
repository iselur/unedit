"""The session the README quotes, replayed against the code that prints it.

The README shows a whole transcript — a save, a diff, a restore, a listing:

    saved  20260802-230236-724062-qaxj  (4 files, 166 B)
      src/app.py                                      46 B  2026-08-02 23:02
      ~ src/app.py  (46 B -> 154 B)

Every one of those lines is generated, and none of it was checked.  The
listing's column is padded to a width, the sizes go through a formatter, the
diff sections are counted and labelled, the restore explains itself in a
particular order.  A README quoting output the tool stopped producing is
describing a different program, and that is the first thing anyone reads.

So this rebuilds the project the transcript was recorded in — the same four
files at the same four byte sizes, 27 + 46 + 26 + 67 = the 166 B the README
claims — replays the same commands through `main()`, and asks whether each
line the README shows came back.

Only two things are masked out: snapshot ids and clocks, which are new on
every run.  The sizes are real, because the fixtures are built to the byte, so
the padding, the column widths, the separators and the size formatter are all
still being compared against the README's own text rather than against a
format string rebuilt from the same constants the code uses.  A test that
builds its expectation the way the code builds its output passes for every
layout there is.

Two lines are deliberately not checked, and named below: `unedit where` prints
the absolute store path and the store's total size on disk, neither of which
is the same here as on the machine the transcript was recorded on.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shlex
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)

from unedit.cli import main

README = os.path.join(_ROOT, "README.md")

# New on every run, so they cannot be compared; everything around them can.
_ID = re.compile(r"\b\d{8}-\d{6}-\d{6}-[a-z0-9]+\b")
_STAMP = re.compile(r"\b\d{4}-\d\d-\d\d[ T]\d\d:\d\d(:\d\d)?\b")
_ABS = re.compile(r"(?<![\w.])/[\w./-]+")

# `unedit where` prints where the store is and how big it got.  Both are
# properties of the machine the README was recorded on, not of the layout.
_NOT_CHECKED = ("where",)

# The project the transcript was recorded in, rebuilt to the byte.  The README
# quotes each of these sizes, so filler is padded to length rather than made up.
BEFORE = 'def greet(name):\n    return f"Hello, {name}!"\n'
AFTER = ('def greet(name):\n'
         '    # agent added logging\n'
         '    print(f"Greeting {name}")\n'
         '    return f"Hello, {name}!"\n'
         '\n'
         'def farewell(name):\n'
         '    return f"Goodbye, {name}!"\n')
FIXTURES = {
    "README.md": "# my-project\n\nplaceholder\n".ljust(27, "\n"),
    "src/app.py": BEFORE,
    "src/config.py": "DEBUG = True\n".ljust(26, "\n"),
    "tests/test_app.py": "from src.app import greet\n".ljust(67, "\n"),
}
NEW_FILE = ("src/new_module.py", "VALUE = 1\n".ljust(14, "\n"))

# The commands the README shows, in the order they have to run here.  The
# README quotes `show`, `diff --patch` and `where` after the restore, but they
# were recorded before it — a restore puts the tree back, and a diff against a
# restored tree has nothing in it.  Which commands appear is checked below;
# only the order differs, and it has to.
SESSION = [
    'unedit save -m "before agent refactor"',
    "AGENT EDITS",
    "unedit show",
    "unedit diff",
    "unedit diff --patch",
    "unedit where",
    "unedit back --yes",
    'unedit save --json -m "json test"',
]


def readme() -> str:
    with open(README, encoding="utf-8") as handle:
        return handle.read()


def blocks(text):
    return re.findall(r"```[a-z]*\n(.*?)```", text, re.S)


def skeleton(line: str) -> str:
    """A line with only the parts that cannot be the same twice masked out."""
    line = _ID.sub("<id>", line)
    line = _STAMP.sub("<when>", line)
    line = _ABS.sub("<path>", line)
    return line.rstrip()


def quoted_sections(text):
    """The README's transcript, as (command, output lines) pairs."""
    out = []
    for block in blocks(text):
        current = None
        for line in block.splitlines():
            if line.startswith("$ "):
                current = line[2:].strip()
                if current.startswith("unedit"):
                    out.append((current, []))
                    continue
                current = None
            elif out and current and not line.startswith("#"):
                out[-1][1].append(line)
    return out


def replay():
    """Run the README's session for real; return every line it printed."""
    printed = []
    with tempfile.TemporaryDirectory() as root:
        for name, body in FIXTURES.items():
            path = os.path.join(root, name)
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w") as handle:
                handle.write(body)
        for step in SESSION:
            if step == "AGENT EDITS":
                with open(os.path.join(root, NEW_FILE[0]), "w") as handle:
                    handle.write(NEW_FILE[1])
                with open(os.path.join(root, "src/app.py"), "w") as handle:
                    handle.write(AFTER)
                continue
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                try:
                    main(["--dir", root] + shlex.split(step)[1:])
                except SystemExit:
                    pass
            printed.append((step, buf.getvalue()))
    return printed


class TestTheREADMEShowsWhatItPrints(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = readme()
        cls.sections = quoted_sections(cls.text)
        cls.printed = replay()
        cls.produced = set()
        for _step, output in cls.printed:
            for line in output.splitlines():
                cls.produced.add(skeleton(line))

    def checkable(self):
        return [(cmd, lines) for cmd, lines in self.sections
                if shlex.split(cmd)[1] not in _NOT_CHECKED]

    def test_the_readme_still_quotes_a_session(self):
        # Without this the loops below iterate over nothing and pass, which is
        # exactly what deleting the examples would look like.
        lines = [ln for _cmd, out in self.checkable() for ln in out if ln.strip()]
        self.assertGreaterEqual(len(lines), 20,
                                "no quoted output left in README.md")

    def test_the_readme_shows_the_commands_this_replays(self):
        shown = sorted({cmd for cmd, _ in self.sections})
        ran = sorted({step for step in SESSION if step != "AGENT EDITS"})
        self.assertEqual(shown, ran,
                         "README.md quotes a command this test does not replay, "
                         "so its output is not being checked")

    def test_every_quoted_line_is_one_unedit_prints(self):
        for cmd, lines in self.checkable():
            for line in lines:
                if not line.strip():
                    continue
                if line.startswith("{") or line.startswith("}"):
                    continue  # --json, compared by key below
                if re.match(r'^\s*"', line):
                    continue
                self.assertIn(
                    skeleton(line), self.produced,
                    "README.md shows a line `unedit` no longer prints, under "
                    "`{}`:\n  {}".format(cmd, line))

    def test_the_json_example_has_the_keys_the_code_emits(self):
        shown = None
        for cmd, lines in self.sections:
            if "--json" in cmd:
                shown = json.loads("\n".join(lines))
        self.assertIsNotNone(shown, "no --json example in README")
        produced = None
        for step, output in self.printed:
            if "--json" in step:
                produced = json.loads(output)
        self.assertEqual(sorted(shown), sorted(produced),
                         "README.md shows JSON keys unedit no longer emits")


if __name__ == "__main__":
    unittest.main()
