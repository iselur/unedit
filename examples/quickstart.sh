#!/usr/bin/env bash
# unedit quickstart example
# Run this from any directory that is NOT your home directory or a system root.
# It creates a sample project in /tmp, runs through every unedit command,
# and cleans up after itself.
#
# Usage:
#   bash examples/quickstart.sh

set -euo pipefail

SCRATCH=$(mktemp -d /tmp/unedit-quickstart-XXXXXX)
trap "rm -rf '$SCRATCH'" EXIT

echo "Working in: $SCRATCH"
echo ""

# --- Set up a sample project ---
mkdir -p "$SCRATCH/src" "$SCRATCH/tests"

cat > "$SCRATCH/src/app.py" << 'EOF'
def greet(name):
    return f"Hello, {name}!"
EOF

cat > "$SCRATCH/src/config.py" << 'EOF'
DEBUG = False
PORT = 8080
EOF

cat > "$SCRATCH/tests/test_app.py" << 'EOF'
from src.app import greet
assert greet("world") == "Hello, world!"
EOF

cat > "$SCRATCH/README.md" << 'EOF'
# Sample Project
EOF

echo "=== 1. Snapshot before agent runs ==="
unedit --dir "$SCRATCH" save -m "before agent refactor"
echo ""

echo "=== 2. List snapshots ==="
unedit --dir "$SCRATCH" list
echo ""

echo "=== 3. Show snapshot contents ==="
unedit --dir "$SCRATCH" show
echo ""

echo "--- simulating agent edits ---"
cat > "$SCRATCH/src/app.py" << 'EOF'
def greet(name):
    # agent added logging
    print(f"Greeting {name}")
    return f"Hello, {name}!"

def farewell(name):
    return f"Goodbye, {name}!"
EOF
echo "agent_helper.py added by agent" > "$SCRATCH/src/agent_helper.py"

echo "=== 4. Diff to see what changed ==="
unedit --dir "$SCRATCH" diff
echo ""

echo "=== 5. Diff with patch to see line-level changes ==="
unedit --dir "$SCRATCH" diff --patch
echo ""

echo "=== 6. Step back (restore snapshot) ==="
unedit --dir "$SCRATCH" back --yes
echo ""

echo "=== 7. Verify app.py is restored ==="
echo "src/app.py contents:"
cat "$SCRATCH/src/app.py"
echo ""

echo "=== 8. See where snapshots are stored ==="
unedit --dir "$SCRATCH" where
echo ""

echo "=== 9. JSON output (useful for scripts) ==="
echo "x" > "$SCRATCH/extra.txt"
unedit --dir "$SCRATCH" save --json -m "json snapshot"
echo ""

echo "=== 10. List all snapshots ==="
unedit --dir "$SCRATCH" list
echo ""

echo "=== 11. Drop all snapshots ==="
unedit --dir "$SCRATCH" drop --all
echo ""

echo "=== 12. Confirm list is empty ==="
unedit --dir "$SCRATCH" list || echo "(exit code 1 = no snapshots, as expected)"
echo ""

echo "=== done ==="
