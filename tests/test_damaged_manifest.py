"""A snapshot that cannot be read is a damaged snapshot, not a missing one.

`.unedit/` sits in the working tree, which is where an agent is editing, and
the manifests in it are plain JSON on purpose — you are meant to be able to
open one.  So they get damaged the ordinary ways: a disk that filled up during
a save, a merge that left `<<<<<<< HEAD` in a committed store, an editor that
saved over one.

The answer used to be `no snapshots. run: unedit save`, which is what an empty
store says.  For an undo tool that is the worst possible sentence: you conclude
you never saved and stop looking, while the content-addressed blobs the
snapshot points at are almost certainly still sitting in `.unedit/objects/`
waiting to be recovered by hand.

A damaged manifest must never be silently skipped.  It is named, it is counted,
and it does not change a real snapshot's answer — the good ones still list,
still show, and still restore.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class TestADamagedManifest(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="unedit_damaged_")
        self.project = os.path.join(self.tmp, "app")
        os.makedirs(self.project)
        self.write("a.py", "value = 1\n")
        result = self.run_unedit("save", "-m", "first")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write(self, name, body):
        with open(os.path.join(self.project, name), "w",
                  encoding="utf-8") as fh:
            fh.write(body)

    def run_unedit(self, *args):
        env = dict(os.environ, PYTHONPATH=_ROOT)
        return subprocess.run(
            [sys.executable, "-m", "unedit", "--project", self.project]
            + list(args),
            capture_output=True, text=True, encoding="utf-8",
            cwd=self.tmp, env=env, timeout=60)

    @property
    def snapshots_dir(self):
        return os.path.join(self.project, ".unedit", "snapshots")

    def manifests(self):
        return sorted(n for n in os.listdir(self.snapshots_dir)
                      if n.endswith(".json"))

    def damage(self, which=-1):
        """Leave a merge conflict in one manifest.  Returns its filename."""
        name = self.manifests()[which]
        path = os.path.join(self.snapshots_dir, name)
        with open(path, encoding="utf-8") as fh:
            body = fh.read()
        with open(path, "w", encoding="utf-8") as fh:
            fh.write("<<<<<<< HEAD\n" + body + "=======\n" + body
                     + ">>>>>>> feature/tax-api\n")
        return name

    # -- the only snapshot there is, and it is damaged --------------------

    def test_list_does_not_say_you_never_saved(self):
        self.damage()
        result = self.run_unedit("list")
        self.assertNotIn("no snapshots", result.stdout + result.stderr,
                         result.stdout + result.stderr)

    def test_list_says_the_word_damaged(self):
        self.damage()
        result = self.run_unedit("list")
        self.assertIn("damaged", (result.stdout + result.stderr).lower(),
                      result.stdout + result.stderr)

    def test_list_names_the_file_to_go_and_look_at(self):
        name = self.damage()
        result = self.run_unedit("list")
        self.assertIn(name, result.stdout + result.stderr,
                      result.stdout + result.stderr)

    def test_list_is_not_a_success(self):
        # `unedit list` on an empty store exits 0, because nothing-yet is not a
        # finding.  A store with a damaged snapshot in it is a finding.
        self.damage()
        result = self.run_unedit("list")
        self.assertNotEqual(result.returncode, 0,
                            result.stdout + result.stderr)

    def test_the_commands_that_restore_do_not_say_no_snapshots_found(self):
        self.damage()
        for command, extra in (("show", []), ("diff", []),
                               ("back", ["--yes"])):
            with self.subTest(command=command):
                result = self.run_unedit(command, *extra)
                blob = result.stdout + result.stderr
                self.assertNotIn("no snapshots found", blob, blob)
                self.assertNotIn("Traceback", result.stderr, result.stderr)

    def test_it_says_the_objects_are_probably_still_there(self):
        # The recovery path is the point: the manifest is an index into
        # `.unedit/objects/`, and losing the index does not lose the content.
        self.damage()
        result = self.run_unedit("list")
        self.assertIn("objects", (result.stdout + result.stderr).lower(),
                      result.stdout + result.stderr)

    def test_it_names_the_directory_the_file_is_in(self):
        # The filename alone is not somewhere to go: manifests live inside
        # `.unedit/snapshots`, which is a directory the person has never had
        # to know about until this moment.  Naming the project directory
        # instead sends them somewhere the file is not.
        self.damage()
        result = self.run_unedit("list")
        blob = result.stdout + result.stderr
        self.assertIn(os.path.join(".unedit", "snapshots"), blob, blob)

    def test_json_reports_it_too(self):
        # A wrapper reading `--json` must not see an empty list and conclude
        # the same wrong thing a person would.
        self.damage()
        result = self.run_unedit("list", "--json")
        blob = result.stdout + result.stderr
        self.assertNotIn("Traceback", result.stderr, result.stderr)
        self.assertNotEqual(result.stdout.strip(), "[]", blob)

    # -- a damaged one alongside a good one -------------------------------

    def test_a_good_snapshot_still_lists(self):
        self.write("b.py", "value = 2\n")
        self.assertEqual(self.run_unedit("save", "-m", "second").returncode, 0)
        self.damage(-1)                 # damage the newer one
        result = self.run_unedit("list")
        self.assertIn("first", result.stdout, result.stdout + result.stderr)

    def test_a_good_snapshot_still_restores(self):
        # The damaged one must not become a reason to refuse the working one.
        self.write("b.py", "value = 2\n")
        self.assertEqual(self.run_unedit("save", "-m", "second").returncode, 0)
        with open(os.path.join(self.snapshots_dir, self.manifests()[0]),
                  encoding="utf-8") as fh:
            good = json.load(fh)["id"]
        self.damage(-1)
        self.write("a.py", "value = 999\n")
        result = self.run_unedit("back", good, "--yes")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        with open(os.path.join(self.project, "a.py"), encoding="utf-8") as fh:
            self.assertEqual(fh.read(), "value = 1\n")

    def test_the_newest_is_not_silently_the_older_good_one(self):
        # `unedit back` with no id means "the newest".  If the newest is
        # damaged, quietly restoring the one before it is a wrong restore
        # reported as a right one.
        self.write("b.py", "value = 2\n")
        self.assertEqual(self.run_unedit("save", "-m", "second").returncode, 0)
        self.damage(-1)
        result = self.run_unedit("back", "--yes")
        blob = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, blob)
        self.assertIn("damaged", blob.lower(), blob)

    # -- the other half: nothing wrong, nothing said ----------------------

    def test_an_empty_store_still_says_no_snapshots(self):
        shutil.rmtree(os.path.join(self.project, ".unedit"))
        result = self.run_unedit("list")
        self.assertIn("no snapshots", result.stdout, result.stdout)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_a_healthy_store_says_nothing_about_damage(self):
        result = self.run_unedit("list")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("damaged", (result.stdout + result.stderr).lower(),
                         result.stdout)

    def test_someone_elses_json_in_there_is_not_a_damaged_snapshot(self):
        # A file that never claimed to be a manifest is not damage; it is
        # somebody else's file, and saying otherwise cries wolf forever.
        with open(os.path.join(self.snapshots_dir, "notes.json"), "w",
                  encoding="utf-8") as fh:
            json.dump({"unrelated": True}, fh)
        result = self.run_unedit("list")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertNotIn("damaged", (result.stdout + result.stderr).lower(),
                         result.stdout)


if __name__ == "__main__":
    unittest.main()
