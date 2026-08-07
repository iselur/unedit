"""Whatever the walk leaves out, the same read of the rules says why.

`scan_tree` used to ask twice.  `is_excluded` decided, over the default names
and then the ignore patterns; `what_excludes` decided again, over the default
names and then the ignore patterns, and turned its answer into a sentence.  Two
functions, one rule, written out twice:

    if name in default_excludes:          if name in default_excludes:
        return True                           return BY_DEFAULT
    for pat in patterns:                  for pat in patterns:
        if _matches_pattern(...):             if _matches_pattern(...):
            return True                           return 'excluded by ...'
    return False                          return None

They agreed, and nothing made them.  A rule added to one of them -- a new
default, a pattern form read a new way -- is a file dropped from the snapshot
by the first with the second returning `None` about it, and `None` there was a
branch that quietly declined to record an example.  What the person sees then
is `nothing captured` with no reason attached, in the one command whose entire
job is to have been a safety net.  That is `test_saved_nothing.py`'s failure
arriving by a different door.

The stated reason for the second copy was that the walk runs per file and does
not always need the sentence.  Measured, on the worst case of an entry excluded
by the last pattern in the list: 4.26us to decide, 4.42us to decide and say
why.  0.17us, once per *excluded* entry, against the 1.61us `os.lstat` the walk
spends on every entry it keeps.  The saving was not there.

So there is one function now, and the two checks below are the two halves of
that being true: nothing else in `store.py` reads the rules, and every kind of
exclusion the tool has can still name itself when it empties a tree.  The
second half is what the first is *for* -- a single decider that has lost the
ability to explain one of its cases is the same silence with fewer functions.
"""

from __future__ import annotations

import ast
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unedit.cli import main  # noqa: E402

_STORE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "unedit", "store.py")

#: The one function allowed to know what is left out.
THE_DECIDER = "what_excludes"


def _owned(fn):
    """The nodes in `fn`'s own body, not those of a function nested in it.

    `scan_tree` holds several closures.  Without this, a call made by one of
    them is attributed to `scan_tree` as well, and both checks below pass on
    code where the closure is the second decider.
    """
    out, stack = [], list(fn.body)
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue                    # visited on its own account
        out.append(node)
        stack.extend(ast.iter_child_nodes(node))
    return out


def _functions_where(predicate):
    """The names of the functions in store.py holding a node predicate likes."""
    with open(_STORE, encoding="utf-8") as fh:
        tree = ast.parse(fh.read())
    found = set()
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if any(predicate(node) for node in _owned(fn)):
            found.add(fn.name)
    return found


class TestOnlyOneFunctionDecides(unittest.TestCase):
    """The rules are read in one place, so there is nothing to disagree with."""

    def test_one_function_matches_a_path_against_the_patterns(self):
        callers = _functions_where(
            lambda n: isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == "_matches_pattern")
        self.assertEqual(
            callers, {THE_DECIDER},
            "the ignore patterns are read in {} -- a second reading of the "
            "same rules, which is a file that can be dropped from a snapshot "
            "by one of them and left unexplained by the other"
            .format(sorted(callers)))

    def test_one_function_knows_the_default_exclusions(self):
        # The other half of the rule, and it went missing separately: the old
        # pair agreed on the patterns and could have differed on the defaults.
        deciders = _functions_where(
            lambda n: isinstance(n, ast.Compare)
            and any(isinstance(op, ast.In) for op in n.ops)
            and any(isinstance(c, ast.Name) and c.id == "default_excludes"
                    for c in n.comparators))
        self.assertEqual(
            deciders, {THE_DECIDER},
            "the default exclusions are read in {} -- see above"
            .format(sorted(deciders)))

    def test_the_walk_goes_through_it(self):
        # One decider nobody asks is the same as no decider.
        askers = _functions_where(
            lambda n: isinstance(n, ast.Call)
            and isinstance(n.func, ast.Name)
            and n.func.id == THE_DECIDER)
        self.assertIn(
            "scan_tree", askers,
            "scan_tree stopped asking {}; it is deciding for itself again"
            .format(THE_DECIDER))


class TestEveryKindOfExclusionCanStillSayWhy(unittest.TestCase):
    """One decider that cannot explain a case is the old silence, tidier.

    Each of these makes that kind of exclusion the sole reason a tree comes
    back empty, so the sentence on screen is that kind's own or there is none.
    `test_saved_nothing.py` covers the two ignore *files*; these cover the
    forms of pattern inside them, which are read by different branches.
    """

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="unedit-why-")
        self.addCleanup(shutil.rmtree, self.root, ignore_errors=True)

    def write(self, rel, text="x\n"):
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def save(self):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = main(["--dir", self.root, "save", "-m", "x"])
        return code, out.getvalue() + err.getvalue()

    def _the_reason_names(self, expected, screen, code):
        self.assertNotEqual(code, 0,
                            "the tree is empty and it said so was fine:\n" + screen)
        self.assertIn("nothing captured", screen, screen)
        self.assertIn(expected, screen,
                      "left the tree out without saying what did it:\n" + screen)

    def test_a_basename_pattern(self):
        self.write("app.py")
        # The ignore file is itself a file: without a line covering it the tree
        # is not empty and there is nothing to explain.
        self.write(".gitignore", "*.py\n.gitignore\n")
        code, screen = self.save()
        self._the_reason_names("excluded by *.py", screen, code)

    def test_a_bare_name_reaches_into_subdirectories(self):
        # A line with no slash in it is matched against the *basename*, at any
        # depth, which is how git reads it and how anybody writing one expects
        # it to work.  `*.py` cannot tell the difference -- `fnmatch`'s star
        # crosses a slash, so it matches the whole path too -- so the case that
        # says which branch ran is a bare name and a file that is not at the
        # top.  Get it wrong and `secrets.env` protects the root and nowhere
        # else, in the file somebody wrote to keep a secret out of a snapshot.
        self.write("sub/secret.txt")
        self.write(".gitignore", "secret.txt\n.gitignore\n")
        code, screen = self.save()
        self._the_reason_names("excluded by secret.txt", screen, code)

    def test_a_pattern_with_a_slash_in_it(self):
        self.write("sub/app.py")
        self.write(".gitignore", "sub/*.py\n.gitignore\n")
        code, screen = self.save()
        self._the_reason_names("excluded by sub/*.py", screen, code)

    def test_a_pattern_anchored_to_the_project_root(self):
        # The branch that reads a leading slash the way git does.  It is the
        # one somebody writes to keep a secret out of a snapshot, so it failing
        # to explain itself is the case that matters most.
        self.write("secret.txt")
        self.write(".gitignore", "/secret.txt\n.gitignore\n")
        code, screen = self.save()
        self._the_reason_names("excluded by /secret.txt", screen, code)

    def test_a_default_exclusion_with_no_ignore_file_involved(self):
        self.write("node_modules/x.js")
        self.write(".gitignore", ".gitignore\n")
        code, screen = self.save()
        self._the_reason_names("default exclusions", screen, code)
        self.assertNotIn("by .gitignore", screen, screen)


if __name__ == "__main__":
    unittest.main()
