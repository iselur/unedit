# unedit

A safety net for letting an agent loose on your files.

Snapshot your working tree before an agent edits it. Step back with one command if you do not like the result. No git required. No daemon running. No background watcher.

```bash
pip install stillworks   # one install, all five agent tools, including this one
```

Or run it straight from a checkout, no install needed — it is stdlib only:

```bash
git clone https://github.com/iselur/unedit
cd unedit && python3 -m unedit --help
```

---

## 30-second quickstart

```
$ cd my-project/

# before you hand off to an agent:
$ unedit save -m "before agent refactor"
saved  20260802-230236-724062-qaxj  (4 files, 166 B)
       before agent refactor

# agent runs, makes changes. check what changed:
$ unedit diff
diff vs 20260802-230236-724062-qaxj  2026-08-02 23:02:36  — before agent refactor

added (1)
  + src/new_module.py  (14 B)
modified (1)
  ~ src/app.py  (46 B -> 154 B)

# not happy? step back:
$ unedit back --yes
plan:
  1 files to restore
  1 new files to move aside (created since snapshot)

auto-saving current state before restore...
safety snapshot: 20260802-230237-007494-4cx2  (run: unedit back 20260802-230237-007494-4cx2 to undo this restore)

new files moved aside to: /tmp/my-project/.unedit/aside/20260802-230237/

done. 1 restored, 1 moved aside, 0 deleted.
to undo: unedit back 20260802-230237-007494-4cx2
```

Restoring is never a one-way door. `back` prints the plan, then (if you confirm) auto-saves the current state and executes the restore. The auto-save only happens when you confirm — aborting at the prompt creates nothing. The command to undo the undo is always printed.

---

## Why it exists

`git stash` requires a git repository, and every session-based tool (`claude code /rewind`, Gemini CLI checkpoints, OpenCode `/undo`) only protects edits made inside its own session using a shadow git repo internally.

unedit fills the gap where none of those apply: a directory that is not a git repository, or a session where you are handing off to a script, a shell command, or an agent running outside the tools listed above.

The model is deliberately imperative rather than reactive: one explicit `unedit save` before you hand off to any agent or script, one `unedit back` if you do not like the result. The protection never depends on a daemon that was or was not started before the session began.

## Why not just ask my AI to do this?

Because the moment things go wrong is precisely the moment you cannot trust the AI to undo them cleanly. unedit runs before you hand off control. It is a snapshot of reality, not a promise by the system that is about to make changes.

---

## Commands

```
unedit save [-m MSG] [--force]           snapshot the current directory tree
unedit list                              snapshots: id, when, message, file count, size
unedit show [ID]                         list every file in a snapshot with sizes
unedit back [ID] [--yes] [--hard] [--force]  restore a snapshot (auto-saves first)
unedit diff [ID] [--patch]               what changed since a snapshot
unedit drop ID... | --all                delete snapshots and reclaim disk space
unedit where                             print the snapshot directory and disk used
unedit --version                         print the version and exit
```

All commands accept `--json`, and all accept `--project DIR` (or `--dir DIR`,
the older spelling) to operate on a directory other than `.`, before or after
the subcommand. A path that isn't there is an error naming it, not a
directory it quietly creates.

### back: how new files are handled

Files that did not exist at snapshot time are moved to `.unedit/aside/<timestamp>/` with their relative paths preserved, not deleted. The tool prints exactly where they went. Use `--hard` to delete them instead; each deleted filename is printed. Empty directories left behind by moved or deleted files are removed automatically. Without `--yes`, a summary is printed and confirmation is required. `--json` implies non-interactive: the prompt is skipped and the restore proceeds, so agents that parse structured output get clean JSON.

### diff: output contract

Default output is a file-level summary (added / modified / removed, with sizes). This keeps output readable even on large trees. Use `--patch` to include a unified diff for each changed text file.

### storage

Snapshots live in `.unedit/` inside your project directory. Objects are content-addressed (SHA-256): two files with the same content are stored once, even across snapshots. You can inspect any snapshot manifest directly — they are plain JSON under `.unedit/snapshots/`.

A manifest that cannot be read is reported as damaged and named, never skipped: a manifest is only an index, so the file contents it points at are still in `.unedit/objects/` and can be recovered by hand.

Add `.unedit/` to your `.gitignore`.

---

## Example session output

```
$ unedit show
snapshot: 20260802-230236-724062-qaxj
  when: 2026-08-02 23:02:36  — before agent refactor
  4 files

  README.md                                       27 B  2026-08-02 23:02
  src/app.py                                      46 B  2026-08-02 23:02
  src/config.py                                   26 B  2026-08-02 23:02
  tests/test_app.py                               67 B  2026-08-02 23:02

$ unedit diff --patch
diff vs 20260802-230236-724062-qaxj  2026-08-02 23:02:36  — before agent refactor

added (1)
  + src/new_module.py  (14 B)
modified (1)
  ~ src/app.py  (46 B -> 154 B)

--- a/src/app.py
+++ b/src/app.py
@@ -1,2 +1,7 @@
 def greet(name):
+    # agent added logging
+    print(f"Greeting {name}")
     return f"Hello, {name}!"
+
+def farewell(name):
+    return f"Goodbye, {name}!"

$ unedit where
/home/user/my-project/.unedit
2 snapshots, 2.6 KB

$ unedit save --json -m "json test"
{
  "id": "20260802-230237-121074-jo4u",
  "file_count": 5,
  "total_size": 168,
  "message": "json test",
  "timestamp": "2026-08-02T23:02:37+01:00",
  "empty": false,
  "nothing_captured": false,
  "skipped": []
}
```

---

## Default exclusions

unedit skips the following by default: `.git`, `.unedit`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `dist`, `build`, `target`, `.next`, `.DS_Store`.

It also respects `.gitignore` and `.uneditignore` (same format: one glob per line) if they exist in the project root.

## Safety guard rails

- Snapshot ids carry a UTC clock, so the newest one is always the last one.
  `unedit back` with no id restores the newest, and local time does not always
  go forwards — daylight saving ends, a laptop lands in another zone — which
  once had `back` restore an older snapshot and report success. The timestamp
  you read in `list` is still your own local time, now with its offset on it.
- Refuses to snapshot `/`, `/etc`, `/usr`, `/var`, `/opt`, `/System`, `/Windows`, or your home directory.
- Refuses (with a `--force` escape) when the tree exceeds 2 GB or 50,000 files.
- Symlinks are stored as symlinks and restored as symlinks. They are never followed out of the tree.
- A restore that would write outside the project is refused whole, before
  anything is touched — no safety snapshot, no partly-restored tree, exit `2`.
  It says which of the two it was: a snapshot naming a path outside the
  project, or an ordinary path that a symlink now redirects. The second one
  is not the snapshot's fault, and the message names the link and where it
  leads, because that is the thing to remove.
- Mode bits are preserved and restored.
- Exit codes: `0` fine, `1` the command failed, `2` usage error, `130`
  stopped by ctrl-c, `141` the reader hung up (`unedit diff | head`, or
  `| less` quit with `q`). The last two are not `0`, because a snapshot or
  a listing that was cut off finished nothing — and `unedit save && rm -rf
  build` must not delete anything on the strength of one.
- An empty store is `1`, not `2`, on every command that can hit it. Nothing
  was typed wrong — there is simply nothing saved yet. `2` stays reserved for
  a command line that was wrong, including naming a snapshot id that is not
  there, so a script can tell "save something first" from "that id is gone".
- A restore that put back fewer files than it planned to exits `1`, not `0`.
  Files can refuse to come back — a read-only directory, another owner, a full
  disk — and `unedit back --yes && npm test` must not run the tests against a
  tree that was never put back. The safety snapshot id is still printed, so
  there is a way out of a half-done restore.
- unedit uses no git internally. Snapshots are a flat content-addressed file store under `.unedit/objects/` with a human-readable JSON manifest per snapshot. No git objects. No git index. Inspectable with any text editor.

---

## Prior art (and what's different)

unedit occupies a specific gap: no background watcher required, no tie to any specific AI tool's session, no git repository required. The model is deliberately imperative — one explicit `save`, one explicit `back`. That combination is not offered by any of the tools below.

**Direct overlap — tools that also protect working-tree state from agent edits:**

- **Salvager (salvager.sh)** — Purpose-built CLI + optional MCP server for AI-agent edit protection. Run `salvager watch` in any project root and it saves a per-file revision into `.salvager/` whenever any file changes, including from agent edits. Restore first saves a pre-restore revision (same "undo the undo" safety). Apache 2.0, single static binary, no telemetry. The key difference: Salvager's protection is reactive and requires `salvager watch` to have been started before edits begin. unedit is imperative: you invoke `save` when you choose. Neither approach is strictly better — they suit different workflows.

- **Claude Code /rewind (built-in checkpointing)** — Claude Code v2+ automatically snapshots files before each edit. `/rewind` opens a menu to restore any checkpoint. Checkpoints persist for 30 days. Uses a shadow git repo under `~/.claude/`. Tied exclusively to Claude Code sessions; does not protect changes made by other tools in the same directory.

- **Gemini CLI checkpointing** — Creates a checkpoint (shadow git commit in `~/.gemini/history/<project_hash>/`) before each approved file-modifying tool call. `/restore` reverts all project files. Disabled by default; requires opt-in. Tied exclusively to Gemini CLI sessions.

- **OpenCode /undo and /redo** — OpenCode snapshots file state per conversation turn using an internal git mechanism. `/undo` walks back through turns. Requires the project to be a git repository. Tied to OpenCode sessions.

**Partial overlap — adjacent tools that informed this design:**

- **ccundo (npm)** — Reads Claude Code session JSON files on disk and reconstructs per-operation undo capability. Not a snapshot tool; it parses the agent's own log rather than capturing an independent snapshot.

- **Rewind MCP (khalilbalaree/undo-mcp)** — MCP server that intercepts file modifications made through Claude Code tool calls and saves checkpoints. Coverage is only as wide as what goes through MCP tool calls; direct shell edits are invisible.

- **jj (Jujutsu VCS)** — VCS that snapshots the working copy automatically before every command and supports `jj undo` / `jj op revert` non-destructively. Best-in-class undo story for repos that adopt jj as the VCS.

- **rsnapshot** — Hardlink-based incremental backup via rsync. Each snapshot is a full directory copy; unchanged files are hardlinked. Designed for cron-driven scheduled backups; requires a config file.

- **snapshotter (seanh, PyPI)** — Simple `snapshotter SRC DEST` command making hardlink snapshots. No list/restore/diff UX. Last released 2016, uses rsync under the hood.

- **restic / borg / kopia** — Production-grade deduplicated backup tools with encryption, remote backends, and scheduled backups. All require repository initialisation and carry significant configuration surface area.

- **VS Code Local History / JetBrains Local History** — Per-file change history saved automatically on every save, inside the IDE. No CLI surface, no whole-tree snapshot, no cross-file restore.

- **git stash (with -u flag)** — Stashes tracked modifications and untracked files. Only works inside a git repository.

- **git worktree** — Creates an isolated working directory for parallel agent sessions. Requires git. Does not snapshot pre-existing uncommitted state for non-git projects.

---

## Honest limits (v0.1)

- **gitignore support is partial.** unedit reads `.gitignore` and `.uneditignore` from the project root only (not from subdirectories). Patterns with `!` (negation), `**` (double-star globbing across path separators), and directory-specific patterns are not fully handled. The common patterns (`*.pyc`, `node_modules/`, `dist/`) work correctly.

- **No conflict detection.** If two people restore different snapshots of the same directory at the same time, the last one wins. unedit has no locking mechanism.

- **Binary file diffs are not shown.** `diff --patch` skips binary files and shows the file-level summary (size before/after) only.

- **Aside files are not indexed.** Files moved to `.unedit/aside/` during a restore are not tracked in any manifest. You navigate them by hand.

- **No compression.** Objects are stored as-is. Deduplication reduces storage for identical files across snapshots, but individual large files are not compressed.

- **No encryption.** Snapshots contain copies of your files in plaintext. If your working directory contains secrets, those secrets are in `.unedit/` too.

- **Large binary files slow saves.** The SHA-256 scan reads every byte of every non-excluded file. Repositories with large binary assets (video, compiled artifacts) may be slow to snapshot.

- **Symlink targets are stored verbatim.** If a symlink points outside the project tree, unedit stores the target path as-is. Restoring on a different machine may produce a dangling symlink.

- **One snapshot is one row.** A message and a filename both end up in a
  manifest in `.unedit/`, and both are read by somebody deciding what to
  restore, so both are flattened to a single line before printing — otherwise
  a newline in either wrote an extra row shaped exactly like a real entry, and
  `unedit show` listed a file that is not in the snapshot. Rows are also cut
  at 400 characters with a marker saying how much was dropped: `unedit save -m
  "$(cat NOTES.md)"` is an ordinary thing for a script to do, and it used to
  scroll every other snapshot off the screen. Nothing is lost — the manifest
  and `--json` keep the whole value.

- **An empty snapshot is not a safety net.** An ignore rule that happens to
  match the whole project — a `.gitignore` containing `*`, a vendored tree
  where the checked-in files are all excluded — used to produce `saved  …
  (0 files, 0 B)` on exit `0`. The count was on screen and nobody reads a
  count next to the word *saved*; the net had no floor in it, and that was
  discovered at restore time, which is the one place it cannot be fixed.
  A save that captures nothing while the directory has files in it now says
  so, names one of the files it did not take and the ignore file responsible,
  and exits `1`. A save of a directory that really is empty is still a save
  and still exits `0` — going `back` to it means "clear this out again", which
  is a real thing to want. `back` to any snapshot holding no files now says
  that before it asks you to confirm, since older versions wrote plenty of
  them.

- **Detection, not proof.** A diff from unedit tells you which files changed by content (hash) and size. It does not tell you whether the change was intentional, correct, or safe. That judgment is yours.

---


## Part of a small family

Five tools for working with coding agents, same house style: zero
dependencies, MIT, no API key, nothing leaves your machine. None of them
call a model — that is the point, since the thing being checked already is
one.

Each of those four claims is a test rather than a promise, in
`tests/test_family_claims.py`: every import resolves to the standard library or
to this package, nothing that can open a socket is imported, no environment
variable that looks like a credential is read, and no model SDK or provider
hostname appears anywhere. A claim repeated in five READMEs and checked in none
of them would read as five agreements when it was one assertion.

- [stillworks](https://github.com/iselur/stillworks) — record what your code does now, catch when it changes later
- [agentdiff](https://github.com/iselur/agentdiff) — see what the agent actually changed, before you merge
- [agentlog](https://github.com/iselur/agentlog) — what did your coding agent actually do today?
- [agentwatch](https://github.com/iselur/agentwatch) — tail what your agent is doing, right now
- [unedit](https://github.com/iselur/unedit) — a safety net for letting an agent loose on your files  ← you are here

One install gets all five, and `stillworks tools` says which ones you have:

```sh
pip install stillworks
stillworks tools
```

## License

MIT. Copyright (c) 2026 stillworks contributors.
