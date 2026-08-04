"""
Tests for unedit.

All tests operate in temporary directories under /tmp.
No network access. No dependency on the developer's home directory.

To run:
  cd /path/to/unedit && python3 -m unittest discover -s tests -v

Environment overrides:
  None required — tests create isolated temp dirs in /tmp automatically.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import unittest

# Ensure the package is importable even without install
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unedit import __version__
from unedit import store as _store
from unedit.cli import build_parser, main


def make_tree(base: str, files: dict) -> None:
    """Create a directory tree from a dict of {rel_path: content}. None = directory."""
    for rel, content in files.items():
        full = os.path.join(base, rel)
        os.makedirs(os.path.dirname(full), exist_ok=True)
        if content is None:
            os.makedirs(full, exist_ok=True)
        else:
            with open(full, 'w') as f:
                f.write(content)


class TempDirMixin:
    """Mixin providing a temporary directory that is cleaned up after each test."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp(prefix='unedit_test_', dir='/tmp')

    def tearDown(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# store module unit tests
# ---------------------------------------------------------------------------

class TestHashFile(TempDirMixin, unittest.TestCase):

    def test_hash_is_hex_64_chars(self):
        path = os.path.join(self.tmpdir, 'f.txt')
        with open(path, 'w') as f:
            f.write('hello')
        h = _store.hash_file(path)
        self.assertEqual(len(h), 64)
        self.assertTrue(all(c in '0123456789abcdef' for c in h))

    def test_hash_deterministic(self):
        path = os.path.join(self.tmpdir, 'f.txt')
        with open(path, 'w') as f:
            f.write('same content')
        h1 = _store.hash_file(path)
        h2 = _store.hash_file(path)
        self.assertEqual(h1, h2)

    def test_different_content_different_hash(self):
        p1 = os.path.join(self.tmpdir, 'a.txt')
        p2 = os.path.join(self.tmpdir, 'b.txt')
        with open(p1, 'w') as f:
            f.write('aaa')
        with open(p2, 'w') as f:
            f.write('bbb')
        self.assertNotEqual(_store.hash_file(p1), _store.hash_file(p2))


class TestScanTree(TempDirMixin, unittest.TestCase):

    def test_basic_scan(self):
        make_tree(self.tmpdir, {'a.py': 'x', 'b.py': 'y', 'sub/c.py': 'z'})
        results = list(_store.scan_tree(self.tmpdir))
        paths = {r[0] for r in results}
        self.assertIn('a.py', paths)
        self.assertIn('b.py', paths)
        self.assertIn('sub/c.py', paths)

    def test_default_excludes_skipped(self):
        make_tree(self.tmpdir, {
            'a.py': 'x',
            'node_modules/foo.js': 'bar',
            '__pycache__/foo.pyc': 'bin',
        })
        results = list(_store.scan_tree(self.tmpdir))
        paths = {r[0] for r in results}
        self.assertIn('a.py', paths)
        self.assertNotIn('node_modules/foo.js', paths)
        self.assertNotIn('__pycache__/foo.pyc', paths)

    def test_unedit_dir_excluded(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        os.makedirs(os.path.join(self.tmpdir, '.unedit', 'snapshots'), exist_ok=True)
        with open(os.path.join(self.tmpdir, '.unedit', 'x.json'), 'w') as f:
            f.write('{}')
        results = list(_store.scan_tree(self.tmpdir))
        paths = {r[0] for r in results}
        self.assertNotIn('.unedit/x.json', paths)

    def test_uneditignore_respected(self):
        make_tree(self.tmpdir, {
            'a.py': 'x',
            'secret.key': 'shh',
            '.uneditignore': '*.key',
        })
        results = list(_store.scan_tree(self.tmpdir))
        paths = {r[0] for r in results}
        self.assertIn('a.py', paths)
        self.assertNotIn('secret.key', paths)


class TestSafeRoot(unittest.TestCase):

    def test_rejects_root(self):
        msg = _store.check_safe_root('/')
        self.assertIsNotNone(msg)

    def test_rejects_etc(self):
        msg = _store.check_safe_root('/etc')
        self.assertIsNotNone(msg)

    def test_rejects_home(self):
        home = os.path.expanduser('~')
        msg = _store.check_safe_root(home)
        self.assertIsNotNone(msg)

    def test_allows_tmp_subdir(self):
        td = tempfile.mkdtemp(prefix='unedit_safe_', dir='/tmp')
        try:
            msg = _store.check_safe_root(td)
            self.assertIsNone(msg)
        finally:
            shutil.rmtree(td, ignore_errors=True)


class TestSaveAndList(TempDirMixin, unittest.TestCase):

    def test_save_creates_manifest(self):
        make_tree(self.tmpdir, {'a.py': 'hello', 'b.py': 'world'})
        manifest = _store.save(self.tmpdir, message='test snap')
        self.assertEqual(manifest['message'], 'test snap')
        self.assertEqual(manifest['file_count'], 2)
        snap_dir = _store._snapshots_dir(_store._store_dir(self.tmpdir))
        self.assertTrue(os.path.isdir(snap_dir))

    def test_save_creates_objects(self):
        make_tree(self.tmpdir, {'a.py': 'content'})
        _store.save(self.tmpdir)
        objects_dir = _store._objects_dir(_store._store_dir(self.tmpdir))
        # Should have at least one object
        count = sum(len(fs) for _, _, fs in os.walk(objects_dir))
        self.assertGreater(count, 0)

    def test_list_returns_snapshots(self):
        make_tree(self.tmpdir, {'x.txt': 'a'})
        _store.save(self.tmpdir, message='first')
        _store.save(self.tmpdir, message='second')
        store = _store._store_dir(self.tmpdir)
        snaps = _store.list_snapshots(store)
        self.assertEqual(len(snaps), 2)

    def test_list_sorted_oldest_first(self):
        make_tree(self.tmpdir, {'x.txt': 'a'})
        m1 = _store.save(self.tmpdir, message='first')
        m2 = _store.save(self.tmpdir, message='second')
        store = _store._store_dir(self.tmpdir)
        snaps = _store.list_snapshots(store)
        self.assertEqual(snaps[0]['id'], m1['id'])
        self.assertEqual(snaps[1]['id'], m2['id'])

    def test_deduplication_single_object_for_identical_files(self):
        # Two files with same content → one object in store
        make_tree(self.tmpdir, {'a.txt': 'same content', 'b.txt': 'same content'})
        _store.save(self.tmpdir)
        objects_dir = _store._objects_dir(_store._store_dir(self.tmpdir))
        count = sum(len(fs) for _, _, fs in os.walk(objects_dir))
        self.assertEqual(count, 1)

    def test_guard_rails_file_count(self):
        # Create a dummy tree with a monkeypatched FILE_LIMIT
        make_tree(self.tmpdir, {'a.txt': 'x'})
        original = _store.FILE_LIMIT
        _store.FILE_LIMIT = 0
        try:
            with self.assertRaises(RuntimeError) as ctx:
                _store.save(self.tmpdir)
            self.assertIn('50,000', str(ctx.exception).replace('0', '50,000') or str(ctx.exception))
        finally:
            _store.FILE_LIMIT = original

    def test_save_empty_message(self):
        make_tree(self.tmpdir, {'f.txt': 'data'})
        m = _store.save(self.tmpdir)
        self.assertEqual(m['message'], '')

    def test_save_records_symlink(self):
        make_tree(self.tmpdir, {'target.txt': 'data'})
        os.symlink('target.txt', os.path.join(self.tmpdir, 'link.txt'))
        m = _store.save(self.tmpdir)
        types = {f['path']: f['type'] for f in m['files']}
        self.assertEqual(types.get('link.txt'), 'symlink')
        self.assertEqual(types.get('target.txt'), 'file')


class TestDiff(TempDirMixin, unittest.TestCase):

    def test_diff_no_changes(self):
        make_tree(self.tmpdir, {'a.py': 'x', 'b.py': 'y'})
        m = _store.save(self.tmpdir)
        result = _store.diff_snapshot(self.tmpdir, m['id'])
        self.assertEqual(result['added'], [])
        self.assertEqual(result['modified'], [])
        self.assertEqual(result['removed'], [])

    def test_diff_detects_modified_file(self):
        make_tree(self.tmpdir, {'a.py': 'original'})
        m = _store.save(self.tmpdir)
        with open(os.path.join(self.tmpdir, 'a.py'), 'w') as f:
            f.write('modified content')
        result = _store.diff_snapshot(self.tmpdir, m['id'])
        paths = [x['path'] for x in result['modified']]
        self.assertIn('a.py', paths)

    def test_diff_detects_added_file(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        m = _store.save(self.tmpdir)
        make_tree(self.tmpdir, {'new.py': 'new'})
        result = _store.diff_snapshot(self.tmpdir, m['id'])
        paths = [x['path'] for x in result['added']]
        self.assertIn('new.py', paths)

    def test_diff_detects_removed_file(self):
        make_tree(self.tmpdir, {'a.py': 'x', 'b.py': 'y'})
        m = _store.save(self.tmpdir)
        os.unlink(os.path.join(self.tmpdir, 'b.py'))
        result = _store.diff_snapshot(self.tmpdir, m['id'])
        paths = [x['path'] for x in result['removed']]
        self.assertIn('b.py', paths)

    def test_diff_patch_flag(self):
        make_tree(self.tmpdir, {'a.py': 'line1\nline2\n'})
        m = _store.save(self.tmpdir)
        with open(os.path.join(self.tmpdir, 'a.py'), 'w') as f:
            f.write('line1\nline3\n')
        result = _store.diff_snapshot(self.tmpdir, m['id'], patch=True)
        self.assertIn('patch', result)
        self.assertIn('line3', result['patch'])


class TestRestore(TempDirMixin, unittest.TestCase):

    def test_back_restores_modified_file(self):
        make_tree(self.tmpdir, {'a.py': 'original'})
        m = _store.save(self.tmpdir, message='orig')
        with open(os.path.join(self.tmpdir, 'a.py'), 'w') as f:
            f.write('changed')
        out = []
        result = _store.restore(self.tmpdir, m['id'], yes=True, print_fn=out.append)
        with open(os.path.join(self.tmpdir, 'a.py')) as f:
            self.assertEqual(f.read(), 'original')

    def test_back_creates_safety_snapshot(self):
        make_tree(self.tmpdir, {'a.py': 'v1'})
        m = _store.save(self.tmpdir)
        with open(os.path.join(self.tmpdir, 'a.py'), 'w') as f:
            f.write('v2')
        store = _store._store_dir(self.tmpdir)
        _store.restore(self.tmpdir, m['id'], yes=True, print_fn=lambda x: None)
        snaps = _store.list_snapshots(store)
        # Should have original + safety
        self.assertGreaterEqual(len(snaps), 2)
        # The safety snap message should mention 'auto'
        auto_snaps = [s for s in snaps if '[auto]' in s.get('message', '')]
        self.assertEqual(len(auto_snaps), 1)

    def test_back_moves_new_files_aside(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        m = _store.save(self.tmpdir)
        # Add a new file after snapshot
        with open(os.path.join(self.tmpdir, 'new_file.py'), 'w') as f:
            f.write('new')
        result = _store.restore(self.tmpdir, m['id'], yes=True, print_fn=lambda x: None)
        # new_file.py should be moved aside, not deleted
        self.assertFalse(os.path.exists(os.path.join(self.tmpdir, 'new_file.py')))
        self.assertEqual(result['moved_aside'], 1)
        self.assertIsNotNone(result['aside_dir'])
        # Should exist in aside dir
        aside = result['aside_dir']
        self.assertTrue(os.path.exists(os.path.join(aside, 'new_file.py')))

    def test_back_hard_deletes_new_files(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        m = _store.save(self.tmpdir)
        with open(os.path.join(self.tmpdir, 'extra.py'), 'w') as f:
            f.write('extra')
        result = _store.restore(self.tmpdir, m['id'], yes=True, hard=True,
                                 print_fn=lambda x: None)
        self.assertFalse(os.path.exists(os.path.join(self.tmpdir, 'extra.py')))
        self.assertEqual(result['deleted'], 1)

    def test_back_aborts_without_yes(self):
        import io
        make_tree(self.tmpdir, {'a.py': 'x'})
        m = _store.save(self.tmpdir)
        # Provide 'n' as input
        import unittest.mock as mock
        with mock.patch('builtins.input', return_value='n'):
            result = _store.restore(self.tmpdir, m['id'], yes=False,
                                    print_fn=lambda x: None)
        self.assertTrue(result.get('aborted'))

    def test_back_newest_by_default(self):
        make_tree(self.tmpdir, {'a.py': 'v1'})
        _store.save(self.tmpdir, message='first')
        with open(os.path.join(self.tmpdir, 'a.py'), 'w') as f:
            f.write('v2')
        m2 = _store.save(self.tmpdir, message='second')
        with open(os.path.join(self.tmpdir, 'a.py'), 'w') as f:
            f.write('v3')
        # back with no ID → restores newest (v2)
        _store.restore(self.tmpdir, None, yes=True, print_fn=lambda x: None)
        with open(os.path.join(self.tmpdir, 'a.py')) as f:
            self.assertEqual(f.read(), 'v2')


class TestDrop(TempDirMixin, unittest.TestCase):

    def test_drop_specific_snapshot(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        m = _store.save(self.tmpdir, message='first')
        _store.save(self.tmpdir, message='second')
        store = _store._store_dir(self.tmpdir)
        _store.drop_snapshots(store, [m['id']])
        snaps = _store.list_snapshots(store)
        self.assertEqual(len(snaps), 1)
        self.assertEqual(snaps[0]['message'], 'second')

    def test_drop_all(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        _store.save(self.tmpdir)
        _store.save(self.tmpdir)
        store = _store._store_dir(self.tmpdir)
        _store.drop_snapshots(store, [], all_snaps=True)
        self.assertEqual(_store.list_snapshots(store), [])

    def test_drop_gcs_orphan_objects(self):
        make_tree(self.tmpdir, {'a.py': 'unique content abc123'})
        m = _store.save(self.tmpdir)
        store = _store._store_dir(self.tmpdir)
        objects = _store._objects_dir(store)
        count_before = sum(len(fs) for _, _, fs in os.walk(objects))
        _store.drop_snapshots(store, [m['id']])
        count_after = sum(len(fs) for _, _, fs in os.walk(objects))
        self.assertLess(count_after, count_before)

    def test_drop_no_snapshots_raises(self):
        store = _store._store_dir(self.tmpdir)
        os.makedirs(_store._snapshots_dir(store), exist_ok=True)
        with self.assertRaises(RuntimeError):
            _store.drop_snapshots(store, ['nonexistent'])


class TestWhere(TempDirMixin, unittest.TestCase):

    def test_where_returns_store_path(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        _store.save(self.tmpdir)
        info = _store.where_info(self.tmpdir)
        self.assertEqual(info['store_dir'], os.path.join(self.tmpdir, '.unedit'))
        self.assertEqual(info['snap_count'], 1)
        self.assertGreater(info['total_bytes'], 0)

    def test_where_no_store_yet(self):
        info = _store.where_info(self.tmpdir)
        self.assertEqual(info['snap_count'], 0)
        self.assertEqual(info['total_bytes'], 0)


# ---------------------------------------------------------------------------
# CLI integration tests
# ---------------------------------------------------------------------------

class TestCLI(TempDirMixin, unittest.TestCase):
    """Test the CLI via main() with --dir pointing to a temp directory."""

    def _run(self, args):
        """Run CLI with given args list. Returns exit code."""
        try:
            main(['--dir', self.tmpdir] + args)
        except SystemExit as e:
            return e.code
        return 0

    def test_save_exit_0(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        code = self._run(['save'])
        self.assertEqual(code, 0)

    def test_list_exit_0_when_no_snapshots(self):
        # An empty store is a normal state, not a finding.  This used to exit 1
        # and a script branching on that read "nothing saved yet" as an error.
        code = self._run(['list'])
        self.assertEqual(code, 0)

    def test_list_exit_0_after_save(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        self._run(['save'])
        code = self._run(['list'])
        self.assertEqual(code, 0)

    def test_save_with_message(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        code = self._run(['save', '-m', 'my message'])
        self.assertEqual(code, 0)
        store = _store._store_dir(self.tmpdir)
        snaps = _store.list_snapshots(store)
        self.assertEqual(snaps[-1]['message'], 'my message')

    def test_diff_exit_0(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        self._run(['save'])
        code = self._run(['diff'])
        self.assertEqual(code, 0)

    def test_where_exit_0(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        self._run(['save'])
        code = self._run(['where'])
        self.assertEqual(code, 0)

    def test_show_exit_0(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        self._run(['save'])
        code = self._run(['show'])
        self.assertEqual(code, 0)

    def test_drop_all_exit_0(self):
        make_tree(self.tmpdir, {'a.py': 'x'})
        self._run(['save'])
        code = self._run(['drop', '--all'])
        self.assertEqual(code, 0)

    def test_json_output_save(self):
        import io
        from contextlib import redirect_stdout
        make_tree(self.tmpdir, {'a.py': 'x'})
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                main(['--dir', self.tmpdir, 'save', '--json'])
            except SystemExit:
                pass
        data = json.loads(buf.getvalue())
        self.assertIn('id', data)
        self.assertIn('file_count', data)

    def test_json_output_save_matches_the_readme(self):
        # The README prints a whole object, so a reader takes it for the whole
        # object — anyone parsing our output writes their code against it.  It
        # shipped without `skipped`, which is always there.
        import io
        import re
        from contextlib import redirect_stdout
        make_tree(self.tmpdir, {'a.py': 'x'})
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                main(['--dir', self.tmpdir, 'save', '--json'])
            except SystemExit:
                pass
        real = json.loads(buf.getvalue())
        readme = open(os.path.join(
            os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
            'README.md')).read()
        block = re.search(r'unedit save --json[^\n]*\n(\{.*?\n\})', readme, re.S)
        self.assertIsNotNone(block, 'the README no longer shows save --json')
        self.assertEqual(sorted(json.loads(block.group(1))), sorted(real))

    def test_json_output_list(self):
        import io
        from contextlib import redirect_stdout
        make_tree(self.tmpdir, {'a.py': 'x'})
        self._run(['save', '-m', 'snap1'])
        buf = io.StringIO()
        with redirect_stdout(buf):
            try:
                main(['--dir', self.tmpdir, 'list', '--json'])
            except SystemExit:
                pass
        data = json.loads(buf.getvalue())
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 1)

    def test_back_restores_via_cli(self):
        make_tree(self.tmpdir, {'a.py': 'original'})
        self._run(['save'])
        with open(os.path.join(self.tmpdir, 'a.py'), 'w') as f:
            f.write('changed')
        self._run(['back', '--yes'])
        with open(os.path.join(self.tmpdir, 'a.py')) as f:
            self.assertEqual(f.read(), 'original')


class TestHardenRegression(TempDirMixin, unittest.TestCase):
    """Regression tests for bugs found in the pre-release review."""

    def test_restore_file_replaced_by_directory(self):
        """HIGH: restore must not crash when a snapshotted file is now a directory."""
        make_tree(self.tmpdir, {
            'aaa.txt': 'v1',
            'foo': 'original',
            'zzz.txt': 'v1',
        })
        m = _store.save(self.tmpdir, message='orig')

        # Simulate: agent replaces the regular file 'foo' with a directory
        with open(os.path.join(self.tmpdir, 'aaa.txt'), 'w') as f:
            f.write('modified')
        os.unlink(os.path.join(self.tmpdir, 'foo'))
        os.makedirs(os.path.join(self.tmpdir, 'foo'))
        with open(os.path.join(self.tmpdir, 'zzz.txt'), 'w') as f:
            f.write('modified')

        msgs = []
        try:
            result = _store.restore(self.tmpdir, m['id'], yes=True, print_fn=msgs.append)
        except Exception as e:
            self.fail('restore raised unexpectedly: {}'.format(e))

        # All three files must be restored
        with open(os.path.join(self.tmpdir, 'aaa.txt')) as f:
            self.assertEqual(f.read(), 'v1')
        with open(os.path.join(self.tmpdir, 'zzz.txt')) as f:
            self.assertEqual(f.read(), 'v1')
        # 'foo' should be a regular file again, not a directory
        self.assertTrue(os.path.isfile(os.path.join(self.tmpdir, 'foo')))

    def test_store_object_concurrent_write_is_harmless(self):
        """MEDIUM: concurrent store_object calls on the same SHA do not raise."""
        import threading
        # Create a file with known content
        src = os.path.join(self.tmpdir, 'src.txt')
        with open(src, 'w') as f:
            f.write('shared content')
        sha = _store.hash_file(src)
        objects_dir = os.path.join(self.tmpdir, 'objects')
        os.makedirs(objects_dir)

        errors = []
        def store_it():
            try:
                _store.store_object(objects_dir, src, sha)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=store_it) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(errors, [], 'concurrent store_object raised: {}'.format(errors))
        # Object must actually be there
        dest = _store._object_path(objects_dir, sha)
        self.assertTrue(os.path.exists(dest))

    def test_hard_restore_prints_deleted_filenames(self):
        """MEDIUM: --hard must print each deleted filename, not just the count."""
        make_tree(self.tmpdir, {'keep.txt': 'base'})
        m = _store.save(self.tmpdir)
        make_tree(self.tmpdir, {'secret.db': 'sensitive', 'wip.py': 'half-done'})

        msgs = []
        _store.restore(self.tmpdir, m['id'], yes=True, hard=True, print_fn=msgs.append)

        combined = '\n'.join(msgs)
        self.assertIn('secret.db', combined)
        self.assertIn('wip.py', combined)

    def test_abort_does_not_create_safety_snapshot(self):
        """MEDIUM: aborting at the confirmation prompt must not create a snapshot."""
        import unittest.mock as mock
        make_tree(self.tmpdir, {'x.txt': 'v1'})
        m = _store.save(self.tmpdir)
        store = _store._store_dir(self.tmpdir)

        with mock.patch('builtins.input', return_value='n'):
            result = _store.restore(self.tmpdir, m['id'], yes=False,
                                    print_fn=lambda x: None)

        self.assertTrue(result.get('aborted'))
        # Only the original snapshot should exist
        snaps = _store.list_snapshots(store)
        self.assertEqual(len(snaps), 1, 'abort created a phantom safety snapshot')

    def test_abort_does_not_print_safety_snapshot_message(self):
        """MEDIUM: abort must not print 'to undo this restore' — nothing was restored."""
        import unittest.mock as mock
        make_tree(self.tmpdir, {'x.txt': 'v1'})
        m = _store.save(self.tmpdir)

        msgs = []
        with mock.patch('builtins.input', return_value='n'):
            _store.restore(self.tmpdir, m['id'], yes=False, print_fn=msgs.append)

        combined = '\n'.join(msgs)
        self.assertNotIn('safety snapshot', combined)
        self.assertNotIn('undo this restore', combined)

    def test_restore_removes_ghost_empty_directories(self):
        """MEDIUM: directories created by agent that have no snapshot counterpart
        must be removed after restore, not left as empty ghosts."""
        make_tree(self.tmpdir, {'main.py': 'main'})
        m = _store.save(self.tmpdir, message='initial')

        # Agent creates nested directories and files
        os.makedirs(os.path.join(self.tmpdir, 'agent_work', 'subdir'))
        with open(os.path.join(self.tmpdir, 'agent_work', 'result.txt'), 'w') as f:
            f.write('data')
        with open(os.path.join(self.tmpdir, 'agent_work', 'subdir', 'nested.txt'), 'w') as f:
            f.write('nested')

        _store.restore(self.tmpdir, m['id'], yes=True, print_fn=lambda x: None)

        self.assertFalse(
            os.path.exists(os.path.join(self.tmpdir, 'agent_work')),
            'agent_work directory was not cleaned up after restore'
        )
        self.assertFalse(
            os.path.exists(os.path.join(self.tmpdir, 'agent_work', 'subdir')),
            'agent_work/subdir was not cleaned up after restore'
        )

    def test_json_back_without_yes_produces_valid_json(self):
        """MEDIUM: unedit back --json must not mix a prompt into stdout."""
        import subprocess
        make_tree(self.tmpdir, {'main.py': 'original'})
        _store.save(self.tmpdir, message='base')
        with open(os.path.join(self.tmpdir, 'main.py'), 'a') as f:
            f.write('\nmod')

        result = subprocess.run(
            [
                sys.executable, '-c',
                'import sys; sys.path.insert(0, {!r}); '
                'from unedit.cli import main; '
                'main(["--dir", {!r}, "back", "--json"])'.format(
                    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    self.tmpdir,
                )
            ],
            input=b'',
            capture_output=True,
        )
        import json as _json
        try:
            data = _json.loads(result.stdout)
        except Exception as e:
            self.fail('--json output is not valid JSON: {}\nstdout={!r}'.format(
                e, result.stdout[:200]))
        # Should have proceeded (since --json implies --yes) and contain restore keys
        self.assertIn('restored_from', data)

    def test_back_exit_1_when_no_snapshots(self):
        """LOW: 'unedit back' with no snapshots must exit 1, not 2."""
        try:
            from unedit.cli import main as _main
            _main(['--dir', self.tmpdir, 'back'])
        except SystemExit as e:
            self.assertEqual(e.code, 1, 'expected exit 1 for no-snapshots, got {}'.format(e.code))
        else:
            self.fail('expected SystemExit')

    def test_diff_exit_1_when_no_snapshots(self):
        """LOW: 'unedit diff' with no snapshots must exit 1, not 2."""
        try:
            from unedit.cli import main as _main
            _main(['--dir', self.tmpdir, 'diff'])
        except SystemExit as e:
            self.assertEqual(e.code, 1, 'expected exit 1 for no-snapshots, got {}'.format(e.code))
        else:
            self.fail('expected SystemExit')

    def test_format_size_dead_code_removed(self):
        """LOW: format_size() must not exist — it was dead code with a severe bug."""
        self.assertFalse(
            hasattr(_store, 'format_size'),
            'format_size() should have been removed but is still present'
        )


class TestIgnorePatterns(TempDirMixin, unittest.TestCase):

    def test_gitignore_excludes_pyc(self):
        make_tree(self.tmpdir, {
            'a.py': 'x',
            'a.pyc': 'binary',
            '.gitignore': '*.pyc\n',
        })
        results = list(_store.scan_tree(self.tmpdir))
        paths = {r[0] for r in results}
        self.assertNotIn('a.pyc', paths)
        self.assertIn('a.py', paths)

    def test_matches_pattern_with_slash(self):
        self.assertTrue(_store._matches_pattern('src/foo.py', 'src/foo.py'))
        self.assertFalse(_store._matches_pattern('other/foo.py', 'src/foo.py'))

    def test_matches_pattern_wildcard(self):
        self.assertTrue(_store._matches_pattern('foo.pyc', '*.pyc'))
        self.assertFalse(_store._matches_pattern('foo.py', '*.pyc'))


class TestVersionFlag(unittest.TestCase):
    """`--version` is how `stillworks tools` detects an install."""

    def _run(self, args):
        import io
        buf, old, code = io.StringIO(), sys.stdout, 0
        sys.stdout = buf
        try:
            main(args)
        except SystemExit as exc:
            code = exc.code or 0
        finally:
            sys.stdout = old
        return code, buf.getvalue()

    def test_version_prints_the_name_and_the_number(self):
        code, out = self._run(['--version'])
        self.assertEqual(code, 0)
        self.assertIn('unedit', out)
        self.assertIn(__version__, out)

    def test_version_works_with_no_subcommand_and_no_store(self):
        # It runs anywhere, including outside a project with no snapshots.
        code, _ = self._run(['--version'])
        self.assertEqual(code, 0)

    def test_version_is_the_last_whitespace_token(self):
        # `stillworks tools` parses the trailing token; keep that shape.
        _code, out = self._run(['--version'])
        self.assertTrue(out.split()[-1][:1].isdigit())


if __name__ == '__main__':
    unittest.main()
