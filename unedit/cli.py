"""
unedit command-line interface.

Commands:
  unedit save [-m MESSAGE] [--force]
  unedit list [--json]
  unedit show [ID] [--json]
  unedit back [ID] [--yes] [--hard] [--force]
  unedit diff [ID] [--patch] [--json]
  unedit drop ID [ID ...] | --all
  unedit where [--json]
"""

from __future__ import annotations

import argparse
import codecs
import json
import os
import sys

from . import __version__
from . import store as _store


def _err(msg: str, code: int = 2) -> int:
    print('unedit: {}'.format(msg), file=sys.stderr)
    return code


def _fmt_ts(ts: str) -> str:
    """Shorten ISO timestamp for display."""
    return ts.replace('T', ' ')


def _print_json(obj) -> None:
    print(json.dumps(obj, indent=2))


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

def cmd_save(args) -> int:
    root = os.path.abspath(args.dir)
    try:
        manifest = _store.save(root, message=args.message or '', force=args.force)
    except RuntimeError as e:
        return _err(str(e))
    except OSError as e:
        return _err('could not save snapshot: {}'.format(e))

    snap_id = manifest['id']
    fc = manifest['file_count']
    sz = _store._fmt_size(manifest['total_size'])
    store_dir = _store._store_dir(root)

    skipped = manifest.get('skipped') or []

    if args.json:
        _print_json({'id': snap_id, 'file_count': fc, 'total_size': manifest['total_size'],
                     'message': manifest['message'], 'timestamp': manifest['timestamp'],
                     'skipped': skipped})
    else:
        print('saved  {}  ({} files, {})'.format(snap_id, fc, sz))
        if args.message:
            print('       {}'.format(_store.one_line(args.message)))
        for entry in skipped[:10]:
            # Named, not counted: "3 files skipped" is not something you can
            # act on, and the whole point is deciding whether it mattered.
            print('       not captured: {}  ({})'.format(
                _store.one_line(entry.get('path', '')), entry.get('reason', '')))
        if len(skipped) > 10:
            print('       ... and {} more not captured'.format(len(skipped) - 10))
        gitignore_hint = os.path.join(root, '.gitignore')
        if os.path.isfile(gitignore_hint):
            # Check if .unedit is already in .gitignore
            try:
                with open(gitignore_hint, encoding='utf-8',
                          errors='replace') as f:
                    content = f.read()
                if '.unedit' not in content:
                    print('hint: add .unedit/ to your .gitignore')
            except OSError:
                pass
        elif os.path.isdir(os.path.join(root, '.git')):
            print('hint: add .unedit/ to your .gitignore')
    return 0


def cmd_list(args) -> int:
    root = os.path.abspath(args.dir)
    store = _store._store_dir(root)
    snaps = _store.list_snapshots(store)

    if not snaps:
        if args.json:
            _print_json([])
        else:
            print('no snapshots. run: unedit save')
        # An empty store is not a finding.  Exit 1 means "something to report",
        # and a script that branches on it should not see "nothing here yet"
        # and conclude that something went wrong.
        return 0

    if args.json:
        out = []
        for s in reversed(snaps):
            out.append({
                'id': s['id'],
                'timestamp': s.get('timestamp', ''),
                'message': _store.one_line(s.get('message', '')),
                'file_count': s.get('file_count', 0),
                'total_size': s.get('total_size', 0),
            })
        _print_json(out)
        return 0

    # Human-readable table
    # newest first
    for s in reversed(snaps):
        ts = _fmt_ts(s.get('timestamp', ''))
        msg = _store.one_line(s.get('message', ''))
        fc = s.get('file_count', 0)
        sz = _store._fmt_size(s.get('total_size', 0))
        line = '{}  {}  {} files  {}'.format(s['id'], ts, fc, sz)
        if msg:
            line += '  — {}'.format(msg)
        print(line)
    return 0


def cmd_show(args) -> int:
    root = os.path.abspath(args.dir)
    store = _store._store_dir(root)
    try:
        manifest, files = _store.show_snapshot(store, args.id)
    except RuntimeError as e:
        return _err(str(e))
    except (OSError, ValueError) as e:
        # The manifest was there a moment ago when it was listed.  Something
        # else moved it, or it is not the JSON it claims to be.
        return _err('could not read that snapshot: {}'.format(e))

    if args.json:
        _print_json({
            'id': manifest['id'],
            'timestamp': manifest.get('timestamp', ''),
            'message': manifest.get('message', ''),
            'files': files,
        })
        return 0

    print('snapshot: {}'.format(manifest['id']))
    ts = _fmt_ts(manifest.get('timestamp', ''))
    msg = manifest.get('message', '')
    print('  when: {}{}'.format(ts, '  — ' + msg if msg else ''))
    print('  {} files'.format(manifest.get('file_count', len(files))))
    print('')
    for f in sorted(files, key=lambda x: x['path']):
        path = _store.one_line(f['path'])
        if f['type'] == 'symlink':
            print('  {} -> {}'.format(path, _store.one_line(f.get('target', ''))))
        else:
            sz = _store._fmt_size(f.get('size', 0))
            ts_str = ''
            if 'mtime' in f:
                import datetime
                try:
                    ts_str = '  ' + datetime.datetime.fromtimestamp(f['mtime']).strftime('%Y-%m-%d %H:%M')
                except (OSError, OverflowError, ValueError):
                    pass
            # Padded in cells, not characters: a CJK filename is drawn twice as
            # wide as it is long, and `ljust` would put the size column two
            # places right of where it is on every other row.
            print('  {}  {:>10s}{}'.format(_store.pad(path, 40), sz, ts_str))
    return 0


def cmd_back(args) -> int:
    root = os.path.abspath(args.dir)

    lines = []
    def out(msg=''):
        if not args.json:
            print(msg)
        lines.append(msg)

    # --json implies non-interactive: skip the confirmation prompt so agents
    # that parse structured output do not see a prompt mixed into their JSON.
    yes = args.yes or args.json

    try:
        result = _store.restore(
            root=root,
            snap_id=args.id,
            yes=yes,
            hard=args.hard,
            force=args.force,
            print_fn=out,
        )
    except RuntimeError as e:
        msg = str(e)
        # "no snapshots found" is a normal empty-store condition, not a usage error.
        if msg == 'no snapshots found':
            return _err(msg, code=1)
        return _err(msg)
    except OSError as e:
        return _err('restore failed: {}'.format(e))

    if args.json:
        _print_json(result)

    if result.get('aborted'):
        return 1
    return 0


def cmd_diff(args) -> int:
    root = os.path.abspath(args.dir)
    try:
        result = _store.diff_snapshot(root, args.id, patch=args.patch)
    except RuntimeError as e:
        msg = str(e)
        if msg == 'no snapshots found':
            return _err(msg, code=1)
        return _err(msg)

    added = result['added']
    modified = result['modified']
    removed = result['removed']
    snap_id = result['snapshot_id']

    if args.json:
        _print_json(result)
        return 0

    ts = _fmt_ts(result.get('snapshot_timestamp', ''))
    msg = result.get('snapshot_message', '')
    header = 'diff vs {}  {}'.format(snap_id, ts)
    if msg:
        header += '  — {}'.format(_store.one_line(msg))
    print(header)
    print('')

    if not added and not modified and not removed:
        print('no changes')
        return 0

    if added:
        print('added ({})'.format(len(added)))
        for f in added:
            sz = _store._fmt_size(f.get('size', 0)) if f['type'] == 'file' else 'symlink'
            print('  + {}  ({})'.format(_store.one_line(f['path']), sz))

    if modified:
        print('modified ({})'.format(len(modified)))
        for f in modified:
            if f['type'] == 'symlink':
                print('  ~ {}  (symlink: {} -> {})'.format(
                    _store.one_line(f['path']),
                    _store.one_line(f.get('old_target', '?')),
                    _store.one_line(f.get('new_target', '?'))))
            else:
                old = _store._fmt_size(f.get('old_size', 0))
                new = _store._fmt_size(f.get('new_size', 0))
                print('  ~ {}  ({} -> {})'.format(_store.one_line(f['path']), old, new))

    if removed:
        print('removed ({})'.format(len(removed)))
        for f in removed:
            sz = _store._fmt_size(f.get('size', 0)) if f['type'] == 'file' else 'symlink'
            print('  - {}  ({})'.format(_store.one_line(f['path']), sz))

    if args.patch and 'patch' in result and result['patch']:
        print('')
        print(_store.block(result['patch']))

    return 0


def cmd_drop(args) -> int:
    root = os.path.abspath(args.dir)
    store = _store._store_dir(root)

    if not args.all and not args.ids:
        return _err('specify a snapshot ID or --all')

    try:
        result = _store.drop_snapshots(store, args.ids or [], all_snaps=args.all)
    except RuntimeError as e:
        return _err(str(e))

    n = result['dropped']
    gc = result['gc_objects']
    if args.json:
        _print_json(result)
    else:
        print('dropped {} snapshot{}.  {} object{} removed from store.'.format(
            n, 's' if n != 1 else '',
            gc, 's' if gc != 1 else '',
        ))
    return 0


def cmd_where(args) -> int:
    root = os.path.abspath(args.dir)
    info = _store.where_info(root)
    if args.json:
        _print_json(info)
    else:
        print(info['store_dir'])
        print('{} snapshot{}, {}'.format(
            info['snap_count'],
            's' if info['snap_count'] != 1 else '',
            info['total_size'],
        ))
    return 0


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog='unedit',
        description='A safety net for letting an agent loose on your files.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            'examples:\n'
            '  unedit save -m "before agent refactor"\n'
            '  unedit list\n'
            '  unedit back\n'
            '  unedit diff\n'
            '  unedit where\n'
        ),
    )
    p.add_argument(
        '--version',
        action='version',
        version='unedit {}'.format(__version__),
    )
    p.add_argument(
        '--dir',
        metavar='DIR',
        default='.',
        help='project root to operate on (default: current directory)',
    )

    sub = p.add_subparsers(dest='command', metavar='COMMAND')
    sub.required = True

    def add_json(sp):
        sp.add_argument('--json', action='store_true', help='output JSON')

    # save
    ps = sub.add_parser('save', help='snapshot the current directory tree')
    ps.add_argument('-m', '--message', metavar='MSG', default='', help='short description')
    ps.add_argument('--force', action='store_true',
                    help='override size/file-count guard rails')
    add_json(ps)

    # list
    pl = sub.add_parser('list', help='show all snapshots')
    add_json(pl)

    # show
    psh = sub.add_parser('show', help='list files captured in a snapshot')
    psh.add_argument('id', nargs='?', metavar='ID', help='snapshot ID (default: newest)')
    add_json(psh)

    # back
    pb = sub.add_parser('back', help='restore a snapshot')
    pb.add_argument('id', nargs='?', metavar='ID', help='snapshot ID (default: newest)')
    pb.add_argument('--yes', '-y', action='store_true', help='skip confirmation prompt')
    pb.add_argument('--hard', action='store_true',
                    help='delete new files instead of moving them aside')
    pb.add_argument('--force', action='store_true',
                    help='override guard rails for the auto-save step')
    add_json(pb)

    # diff
    pd = sub.add_parser('diff', help='what changed since a snapshot')
    pd.add_argument('id', nargs='?', metavar='ID', help='snapshot ID (default: newest)')
    pd.add_argument('--patch', action='store_true', help='include unified diff for changed files')
    add_json(pd)

    # drop
    pdr = sub.add_parser('drop', help='delete snapshots')
    pdr.add_argument('ids', nargs='*', metavar='ID', help='snapshot IDs to drop')
    pdr.add_argument('--all', action='store_true', help='drop all snapshots')
    add_json(pdr)

    # where
    pw = sub.add_parser('where', help='print snapshot directory and disk usage')
    add_json(pw)

    return p


def _write_utf8_if_the_locale_said_nothing() -> None:
    """Write UTF-8 when the machine claims it can only take ASCII.

    A container with no locale set — a Dockerfile without ``ENV LANG``, cron,
    most of CI — leaves Python believing stdout is ASCII, and then a single em
    dash of our own raises ``UnicodeEncodeError`` halfway through a listing:
    a traceback and half a screen, over a character no one chose.

    An ASCII claim is not a claim about the terminal, though.  It is the
    absence of one, and the terminal on the other end is virtually always
    UTF-8.  So we write UTF-8 and keep ``surrogateescape``, which hands back
    unchanged the bytes of any filename this machine could not decode — that is
    what makes a name it cannot spell come out spelled right anyway.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            if codecs.lookup(stream.encoding or '').name == 'ascii':
                stream.reconfigure(encoding='utf-8', errors='surrogateescape')
        except (AttributeError, LookupError, OSError, ValueError):
            pass                        # not a real stream, or already written to


def main(argv=None) -> None:
    """Entry point, and the one place ctrl-c is allowed to mean something.

    Snapshotting a large tree takes a moment, and interrupting a command that
    is taking longer than you expected is ordinary.  A traceback in reply reads
    especially badly out of this tool: people reach for it when something has
    already gone wrong, so a crash from the safety net is the last thing they
    need to see.  130 is the shell's own spelling of "stopped by ctrl-c", and
    it keeps `unedit save && rm -rf build` from deleting anything on the
    strength of a snapshot that was never finished.
    """
    try:
        _run(argv)
    except KeyboardInterrupt:
        sys.exit(130)


def _run(argv=None) -> None:
    _write_utf8_if_the_locale_said_nothing()
    parser = build_parser()
    args = parser.parse_args(argv)

    # Propagate --json and --dir to subcommands
    # (argparse places them on the root namespace, shared with subcommands)

    cmd_map = {
        'save': cmd_save,
        'list': cmd_list,
        'show': cmd_show,
        'back': cmd_back,
        'diff': cmd_diff,
        'drop': cmd_drop,
        'where': cmd_where,
    }

    fn = cmd_map.get(args.command)
    if fn is None:
        parser.print_help()
        sys.exit(2)

    sys.exit(fn(args))


if __name__ == '__main__':
    main()
