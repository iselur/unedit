"""What unedit does when the project directory is not the tidy one in the README.

unedit restores files.  That is a destructive act performed on somebody's work,
so the failure that matters most here is not a crash — it is a command that
reports success while quietly doing less, or more, than it said.

Exit codes are the contract: 0 fine, 1 something to report, 2 usage error.
"""

from __future__ import annotations

import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unedit.cli import main
from unedit import store as _store


class HostileProjectCase(unittest.TestCase):
    def setUp(self) -> None:
        self.root = tempfile.mkdtemp(prefix="unedit-hostile-")
        self.write("keep.txt", "one\n")

    def tearDown(self) -> None:
        for dirpath, dirnames, _ in os.walk(self.root):
            for d in dirnames:
                try:
                    os.chmod(os.path.join(dirpath, d), 0o700)
                except OSError:
                    pass
        shutil.rmtree(self.root, ignore_errors=True)

    def write(self, rel: str, text: str) -> str:
        path = os.path.join(self.root, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(text)
        return path

    def run_cli(self, *argv):
        # --dir is a global option: it goes before the subcommand, not after.
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            try:
                code = main(["--dir", self.root] + list(argv))
            except SystemExit as exit_:
                code = exit_.code if isinstance(exit_.code, int) else 2
        return code, out.getvalue(), err.getvalue()

    def save(self, *extra):
        return self.run_cli("save", *extra)

    def assertNoCrash(self, code, err):
        self.assertIn(code, (0, 1, 2), "exit {}: {}".format(code, err))
        self.assertNotIn("Traceback", err)

    def snapshot_ids(self):
        return [s["id"] for s in _store.list_snapshots(_store._store_dir(self.root))]

    def skip_as_root(self):
        if os.geteuid() == 0:
            self.skipTest("root ignores the permission bits this test relies on")


class TestExitCodes(HostileProjectCase):
    """An empty store is not a finding."""

    def test_list_with_no_snapshots_exits_zero(self):
        code, out, err = self.run_cli("list")
        self.assertNoCrash(code, err)
        self.assertEqual(code, 0, "an empty store is not a finding: {}".format(out))

    def test_list_json_with_no_snapshots_exits_zero(self):
        code, out, err = self.run_cli("list", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(out), [])


class TestOddFileTypes(HostileProjectCase):
    """Not everything in a project directory is a file."""

    def test_a_fifo_does_not_hang_save(self):
        try:
            os.mkfifo(os.path.join(self.root, "pipe"))
        except (AttributeError, OSError) as exc:
            self.skipTest("no FIFO support here: {}".format(exc))
        code, _, err = self.save()
        self.assertNoCrash(code, err)
        self.assertEqual(code, 0)

    def test_a_fifo_is_not_recorded_as_a_file(self):
        try:
            os.mkfifo(os.path.join(self.root, "pipe"))
        except (AttributeError, OSError) as exc:
            self.skipTest("no FIFO support here: {}".format(exc))
        self.save()
        manifest = _store.list_snapshots(_store._store_dir(self.root))[-1]
        self.assertNotIn("pipe", [f["path"] for f in manifest["files"]])

    def test_an_unreadable_file_is_reported_not_silently_dropped(self):
        self.skip_as_root()
        secret = self.write("locked.txt", "content\n")
        os.chmod(secret, 0o000)
        code, out, err = self.save()
        self.assertNoCrash(code, err)
        self.assertIn("locked.txt", out + err,
                      "a file that could not be read must be named, not omitted")

    def test_an_unreadable_subdirectory_is_reported(self):
        self.skip_as_root()
        self.write("sub/deep.txt", "x\n")
        os.chmod(os.path.join(self.root, "sub"), 0o000)
        try:
            code, out, err = self.save()
            self.assertNoCrash(code, err)
            self.assertIn("sub", out + err)
        finally:
            os.chmod(os.path.join(self.root, "sub"), 0o700)


class TestDropIsDestructive(HostileProjectCase):
    """`drop` deletes.  Every ambiguity must resolve towards deleting less."""

    def setUp(self) -> None:
        super().setUp()
        self.save("-m", "first")
        self.write("keep.txt", "two\n")
        self.save("-m", "second")

    def test_drop_with_an_empty_id_is_a_usage_error(self):
        code, _, err = self.run_cli("drop", "")
        self.assertNoCrash(code, err)
        self.assertEqual(code, 2)
        self.assertEqual(len(self.snapshot_ids()), 2, "nothing may be deleted")

    def test_drop_all_with_an_unknown_id_deletes_nothing(self):
        code, _, err = self.run_cli(
            "drop", "definitely-not-an-id", "--all")
        self.assertNoCrash(code, err)
        self.assertEqual(code, 2)
        self.assertEqual(len(self.snapshot_ids()), 2,
                        "--all must not paper over an ID that matches nothing")

    def test_drop_all_alone_still_works(self):
        code, _, err = self.run_cli("drop", "--all")
        self.assertNoCrash(code, err)
        self.assertEqual(code, 0)
        self.assertEqual(self.snapshot_ids(), [])

    def test_drop_all_survives_a_snapshot_vanishing_underneath_it(self):
        store = _store._store_dir(self.root)
        real_unlink = os.unlink
        victim = self.snapshot_ids()[0]

        def racing_unlink(path, *a, **kw):
            # The other half of a `drop --all` running at the same time.
            if path.endswith(".json"):
                real_unlink(_store._snap_path(store, victim)) if os.path.exists(
                    _store._snap_path(store, victim)) else None
            return real_unlink(path)

        os.unlink = racing_unlink
        try:
            code, _, err = self.run_cli("drop", "--all")
        finally:
            os.unlink = real_unlink
        self.assertNoCrash(code, err)


class TestDamagedStore(HostileProjectCase):
    """A snapshot file is JSON somebody else wrote."""

    def _corrupt_with(self, payload) -> None:
        self.save()
        store = _store._store_dir(self.root)
        snaps = _store._snapshots_dir(store)
        target = os.path.join(snaps, sorted(os.listdir(snaps))[0])
        with open(target, "w", encoding="utf-8") as fh:
            json.dump(payload, fh)

    def test_a_manifest_that_is_a_list_is_ignored_not_fatal(self):
        self._corrupt_with([])
        code, _, err = self.run_cli("list")
        self.assertNoCrash(code, err)

    def test_a_manifest_that_is_a_string_is_ignored_not_fatal(self):
        self._corrupt_with("nonsense")
        code, _, err = self.run_cli("list")
        self.assertNoCrash(code, err)

    def test_a_manifest_missing_its_id_is_ignored_not_fatal(self):
        self._corrupt_with({"files": []})
        code, _, err = self.run_cli("list")
        self.assertNoCrash(code, err)

    def test_show_when_the_manifest_disappears_mid_flight(self):
        self.save()
        store = _store._store_dir(self.root)
        snap_id = self.snapshot_ids()[0]
        real_open = _store.load_manifest

        def vanishing(store_dir, sid):
            os.unlink(_store._snap_path(store_dir, sid))
            return real_open(store_dir, sid)

        _store.load_manifest = vanishing
        try:
            code, _, err = self.run_cli("show", snap_id)
        finally:
            _store.load_manifest = real_open
        self.assertNoCrash(code, err)


class TestOutputCannotBeForged(HostileProjectCase):
    """One line per snapshot, one line per file — whatever the text says."""

    def test_a_newline_in_the_message_does_not_forge_a_row(self):
        self.save("-m", "real\nfake-id  2026-01-01  0 files  0 B")
        code, out, err = self.run_cli("list")
        self.assertNoCrash(code, err)
        rows = [line for line in out.splitlines() if line.strip()]
        self.assertEqual(len(rows), 1, "one snapshot, one row:\n{}".format(out))

    def test_a_newline_in_a_filename_does_not_forge_a_row(self):
        try:
            self.write("odd\nname.txt", "x\n")
        except OSError as exc:
            self.skipTest("filesystem refuses newlines in names: {}".format(exc))
        self.save()
        code, out, err = self.run_cli("show")
        self.assertNoCrash(code, err)
        listed = [line for line in out.splitlines() if line.startswith("  ") and ".txt" in line]
        self.assertEqual(len(listed), 2, "two files, two rows:\n{}".format(out))


class TestIgnorePatterns(HostileProjectCase):
    """A pattern the user wrote to keep something out must keep it out."""

    def test_a_rooted_gitignore_pattern_is_honoured(self):
        self.write(".gitignore", "/secret.txt\n")
        self.write("secret.txt", "password\n")
        self.save()
        manifest = _store.list_snapshots(_store._store_dir(self.root))[-1]
        self.assertNotIn("secret.txt", [f["path"] for f in manifest["files"]])

    def test_a_rooted_pattern_still_only_matches_at_the_root(self):
        self.write(".gitignore", "/secret.txt\n")
        self.write("sub/secret.txt", "not the same file\n")
        self.save()
        manifest = _store.list_snapshots(_store._store_dir(self.root))[-1]
        self.assertIn("sub/secret.txt", [f["path"] for f in manifest["files"]])


class TestRestoreCountsHonestly(HostileProjectCase):
    """`back` says how many files it restored.  That number must be true."""

    def test_a_missing_object_is_not_counted_as_restored(self):
        self.write("a.txt", "original\n")
        self.save()
        snap_id = self.snapshot_ids()[0]
        manifest = _store.load_manifest(_store._store_dir(self.root), snap_id)
        target = [f for f in manifest["files"] if f["path"] == "a.txt"][0]
        obj = _store._object_path(_store._objects_dir(_store._store_dir(self.root)),
                                  target["hash"])
        self.write("a.txt", "changed\n")
        os.chmod(os.path.dirname(obj), 0o700)
        os.unlink(obj)

        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            result = _store.restore(self.root, snap_id, yes=True, print_fn=lambda *a: None)
        self.assertEqual(result["restored"], 0,
                         "the only file's object was deleted; nothing was restored")


class TestOutputCannotDriveTheTerminal(HostileProjectCase):
    """Printing a name or a diff is not neutral: a terminal obeys some of it.

    ``unedit`` is read by someone deciding what to restore, and everything they
    read comes from outside — filenames an agent chose, messages, and under
    ``--patch`` the file contents themselves.  An escape sequence in any of them
    clears the screen, retitles the window, or leaves every later line coloured,
    and a right-to-left override makes a path read as something other than the
    file that will be written.
    """

    # Assembled from chr() so this file stays printable: a fixture that can
    # retitle your window when you open it is its own problem.
    ESC, BEL, RLO = chr(27), chr(7), chr(0x202E)
    NASTY = (
        ESC + "[2J" + ESC + "[H",       # clear the screen
        ESC + "]0;pwned" + BEL,         # retitle the window
        ESC + "[31m",                   # colour everything after this
        RLO,                            # right-to-left override
        chr(127),                       # delete
        chr(0x2028),                    # unicode line separator
    )

    def assertPrintable(self, out, nasty, what):
        for char in out:
            if char in "\n\t":
                continue                # the layout's own whitespace
            self.assertFalse(
                ord(char) < 32 or ord(char) == 127,
                "control character {!r} reached the terminal from {!r} via {}"
                .format(char, nasty, what))
        self.assertNotIn(self.RLO, out, what)
        self.assertNotIn(chr(0x2028), out, what)

    def test_no_view_prints_a_control_character_from_a_message(self):
        for nasty in self.NASTY:
            self.save("-m", "note" + nasty + "end")
            for argv in (("list",), ("show",)):
                code, out, err = self.run_cli(*argv)
                self.assertNoCrash(code, err)
                self.assertPrintable(out, nasty, " ".join(argv))

    def test_no_view_prints_a_control_character_from_a_filename(self):
        for nasty in self.NASTY:
            try:
                self.write("odd" + nasty + "name.txt", "x\n")
            except (OSError, ValueError) as exc:
                self.skipTest("filesystem refuses this name: {}".format(exc))
            self.save()
            for argv in (("show",), ("diff",)):
                code, out, err = self.run_cli(*argv)
                self.assertNoCrash(code, err)
                self.assertPrintable(out, nasty, " ".join(argv))

    def test_the_patch_body_cannot_drive_the_terminal_either(self):
        # --patch prints file contents, which is the widest opening of the
        # three.  It is display only — restoring reads the stored object, never
        # this text — so cleaning it costs the reader nothing.
        self.write("app.py", "before\n")
        self.save()
        for nasty in self.NASTY:
            self.write("app.py", "after " + nasty + " tail\n")
            code, out, err = self.run_cli("diff", "--patch")
            self.assertNoCrash(code, err)
            self.assertPrintable(out, nasty, "diff --patch")

    def test_the_text_around_it_survives(self):
        # Stripping must not eat the name, or the view is safe and useless at
        # the same time.
        self.write("keepme.txt", "x\n")
        self.save("-m", "hello" + self.ESC + "[2Jworld")
        code, out, err = self.run_cli("show")
        self.assertNoCrash(code, err)
        self.assertIn("keepme.txt", out)
        self.assertIn("world", out)

    def test_the_stored_message_is_clean_not_just_the_printed_one(self):
        # unedit normalises a message as it is saved rather than as it is shown,
        # so the escape never reaches the manifest on disk.  That is worth
        # holding: anything else reading .unedit/ inherits the guarantee.
        self.save("-m", "note" + self.ESC + "[2J")
        code, out, err = self.run_cli("list", "--json")
        self.assertNoCrash(code, err)
        rows = json.loads(out)                  # still valid JSON
        self.assertNotIn("\\u001b", out)
        self.assertEqual(rows[0]["message"], "note [2J")

    def test_a_patch_in_json_is_escaped_rather_than_stripped(self):
        # A patch is file content and is not normalised on the way in, so --json
        # carries what was really there.  JSON's own escaping is what makes that
        # safe to print, which is why this view is left alone.
        self.write("app.py", "before\n")
        self.save()
        self.write("app.py", "after " + self.ESC + "[2J\n")
        code, out, err = self.run_cli("diff", "--patch", "--json")
        self.assertNoCrash(code, err)
        json.loads(out)                         # still valid JSON
        self.assertIn("\\u001b", out)


if __name__ == "__main__":
    unittest.main()
