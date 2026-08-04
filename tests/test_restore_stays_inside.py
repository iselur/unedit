"""A restore may only write inside the project it was taken from.

The snapshot store is a directory in the working tree, and a working tree is
exactly the place this tool assumes something else is writing to — that is the
whole reason it exists.  So a manifest is not trusted input.  It gets committed
and cloned along with the repo, it sits in a tree an agent is editing, and it is
plain JSON that anything can rewrite.

A path in a manifest is meant to be relative to the project root.  Nothing was
checking that it stayed there, so a manifest naming ``../../.bashrc`` — or an
absolute path, or a path through a directory symlink pointing out of the tree —
made ``unedit back`` write wherever the user could write, and the plan it
printed first said only "1 files to restore".

The check has to happen before anything is written, not partway through.  A
restore that stops halfway has already taken the safety snapshot and started
overwriting, which leaves the tree in a state nobody asked for.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestARestoreStaysInsideTheProject(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="unedit_escape_")
        self.project = os.path.join(self.tmp, "proj")
        self.outside = os.path.join(self.tmp, "outside")
        os.makedirs(self.project)
        os.makedirs(self.outside)
        self.victim = os.path.join(self.outside, "victim.txt")
        with open(self.victim, "w", encoding="utf-8") as handle:
            handle.write("ORIGINAL")
        with open(os.path.join(self.project, "a.py"), "w",
                  encoding="utf-8") as handle:
            handle.write("safe = 1\n")
        self.run_unedit("save")

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def run_unedit(self, *args):
        env = dict(os.environ, PYTHONPATH=_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "unedit"] + list(args),
            capture_output=True, text=True, encoding="utf-8",
            cwd=self.project, env=env, timeout=60)

    def _manifest_path(self):
        snaps = os.path.join(self.project, ".unedit", "snapshots")
        names = [n for n in os.listdir(snaps) if n.endswith(".json")]
        self.assertEqual(len(names), 1, names)
        return os.path.join(snaps, names[0])

    def _point_the_snapshot_at(self, path):
        """Rewrite the one entry in the manifest to name ``path``."""
        manifest = self._manifest_path()
        with open(manifest, encoding="utf-8") as handle:
            data = json.load(handle)
        data["files"][0]["path"] = path
        with open(manifest, "w", encoding="utf-8") as handle:
            json.dump(data, handle)

    def _victim(self):
        with open(self.victim, encoding="utf-8") as handle:
            return handle.read()

    def test_a_relative_path_cannot_climb_out(self):
        # The plain form: `../` repeated until it is somewhere interesting.
        self._point_the_snapshot_at(os.path.join("..", "outside", "victim.txt"))
        result = self.run_unedit("back", "--yes")
        self.assertEqual(self._victim(), "ORIGINAL",
                         result.stdout + result.stderr)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_an_absolute_path_cannot_be_named_at_all(self):
        # `os.path.join(root, "/etc/passwd")` is `/etc/passwd` — the root is
        # simply discarded, which is easy to not notice.
        self._point_the_snapshot_at(self.victim)
        result = self.run_unedit("back", "--yes")
        self.assertEqual(self._victim(), "ORIGINAL",
                         result.stdout + result.stderr)
        self.assertNotEqual(result.returncode, 0, result.stdout)

    def test_a_directory_symlink_is_not_a_way_out_either(self):
        # Every component is an innocent-looking name; the escape is on disk
        # rather than in the string, so checking the text is not enough.
        os.symlink(self.outside, os.path.join(self.project, "esc"))
        self._point_the_snapshot_at(os.path.join("esc", "victim.txt"))
        result = self.run_unedit("back", "--yes")
        self.assertEqual(self._victim(), "ORIGINAL",
                         result.stdout + result.stderr)

    def test_it_says_which_path_it_refused(self):
        # "refused" with no name is a puzzle.  A corrupt manifest and a hostile
        # one look the same from here, and either way the next thing anybody
        # wants to know is which entry.
        escape = os.path.join("..", "outside", "victim.txt")
        self._point_the_snapshot_at(escape)
        result = self.run_unedit("back", "--yes")
        self.assertIn("victim.txt", result.stdout + result.stderr)

    def test_nothing_is_written_before_it_refuses(self):
        # A restore that stops partway has already taken the safety snapshot
        # and started overwriting.  The check belongs before the first write.
        before = sorted(os.listdir(os.path.join(
            self.project, ".unedit", "snapshots")))
        self._point_the_snapshot_at(os.path.join("..", "outside", "victim.txt"))
        self.run_unedit("back", "--yes")
        after = sorted(os.listdir(os.path.join(
            self.project, ".unedit", "snapshots")))
        self.assertEqual(before, after, "a safety snapshot was taken anyway")

    def test_an_ordinary_snapshot_still_restores(self):
        # The other half: this must not become a tool that refuses to work.
        with open(os.path.join(self.project, "a.py"), "w",
                  encoding="utf-8") as handle:
            handle.write("safe = 2\n")
        result = self.run_unedit("back", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(os.path.join(self.project, "a.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "safe = 1\n")

    def test_a_nested_path_inside_the_project_is_fine(self):
        # `pkg/mod.py` contains a separator too; the check is about where the
        # path lands, not about whether it looks complicated.
        os.makedirs(os.path.join(self.project, "pkg"))
        with open(os.path.join(self.project, "pkg", "mod.py"), "w",
                  encoding="utf-8") as handle:
            handle.write("nested = 1\n")
        self.run_unedit("save")
        os.remove(os.path.join(self.project, "pkg", "mod.py"))
        result = self.run_unedit("back", "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertTrue(os.path.exists(
            os.path.join(self.project, "pkg", "mod.py")), result.stdout)


if __name__ == "__main__":
    unittest.main()
