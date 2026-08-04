# unedit

A safety net for letting an agent loose on your files.

Snapshot your working tree before an agent edits it. Step back with one command if you do not like the result. No git required. No daemon running. No background watcher.

```bash
pip install 'stillworks[all]'   # all four agent tools, including this one
pip install unedit              # or just this one, zero dependencies
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
unedit save [-m MESSAGE] [--force]    snapshot the current directory tree
unedit list [--json]                  snapshots: id, when, message, file count, size
unedit show [ID] [--json]             list every file in a snapshot with sizes
unedit back [ID] [--yes] [--hard]     restore a snapshot (auto-saves first)
unedit diff [ID] [--patch] [--json]   what changed since a snapshot
unedit drop ID... | --all             delete snapshots and reclaim disk space
unedit where [--json]                 print the snapshot directory and disk used
```

All commands accept `--dir PATH` to operate on a directory other than `.`.

### back: how new files are handled

Files that did not exist at snapshot time are moved to `.unedit/aside/<timestamp>/` with their relative paths preserved, not deleted. The tool prints exactly where they went. Use `--hard` to delete them instead; each deleted filename is printed. Empty directories left behind by moved or deleted files are removed automatically. Without `--yes`, a summary is printed and confirmation is required. `--json` implies non-interactive: the prompt is skipped and the restore proceeds, so agents that parse structured output get clean JSON.

### diff: output contract

Default output is a file-level summary (added / modified / removed, with sizes). This keeps output readable even on large trees. Use `--patch` to include a unified diff for each changed text file.

### storage

Snapshots live in `.unedit/` inside your project directory. Objects are content-addressed (SHA-256): two files with the same content are stored once, even across snapshots. You can inspect any snapshot manifest directly — they are plain JSON under `.unedit/snapshots/`.

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
  "timestamp": "2026-08-02T23:02:37"
}
```

---

## Default exclusions

unedit skips the following by default: `.git`, `.unedit`, `node_modules`, `.venv`, `venv`, `__pycache__`, `.mypy_cache`, `.pytest_cache`, `dist`, `build`, `target`, `.next`, `.DS_Store`.

It also respects `.gitignore` and `.uneditignore` (same format: one glob per line) if they exist in the project root.

## Safety guard rails

- Refuses to snapshot `/`, `/etc`, `/usr`, `/var`, `/opt`, `/System`, `/Windows`, or your home directory.
- Refuses (with a `--force` escape) when the tree exceeds 2 GB or 50,000 files.
- Symlinks are stored as symlinks and restored as symlinks. They are never followed out of the tree.
- Mode bits are preserved and restored.
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

- **Detection, not proof.** A diff from unedit tells you which files changed by content (hash) and size. It does not tell you whether the change was intentional, correct, or safe. That judgment is yours.

---


## Part of a small family

Five tools for working with coding agents, same house style: zero
dependencies, MIT, no API key, nothing leaves your machine. None of them
call a model — that is the point, since the thing being checked already is
one.

- [stillworks](https://github.com/iselur/stillworks) — record what your code does now, catch when it changes later
- [agentdiff](https://github.com/iselur/agentdiff) — see what the agent actually changed, before you merge
- [agentlog](https://github.com/iselur/agentlog) — what did your coding agent actually do today?
- [agentwatch](https://github.com/iselur/agentwatch) — tail what your agent is doing, right now
- [unedit](https://github.com/iselur/unedit) — a safety net for letting an agent loose on your files  ← you are here

One install gets all five, and `stillworks tools` says which ones you have:

```sh
pip install 'stillworks[all]'
stillworks tools
```

## License

MIT. Copyright (c) 2026 stillworks contributors.
