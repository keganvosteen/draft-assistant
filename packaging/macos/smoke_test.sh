#!/usr/bin/env bash
#
# Verifies a built Draft Assistant.app actually boots and serves the UI.
#
#   ./packaging/macos/smoke_test.sh "dist/pyinstaller/Draft Assistant.app"
#
# Runs the bundle's executable directly in browser mode against a throwaway
# data directory. Catches the usual PyInstaller failure where the build
# succeeds but a data file or hidden import is missing at runtime.
#
set -euo pipefail

APP="${1:?usage: smoke_test.sh <path to Draft Assistant.app>}"
BIN="$APP/Contents/MacOS/DraftAssistant"
TIMEOUT="${2:-60}"

[ -x "$BIN" ] || { echo "ERROR: not executable: $BIN" >&2; exit 1; }

DATA_DIR="$(mktemp -d)"
PORT=$(( RANDOM % 15000 + 49200 ))
PID=""

cleanup() {
    [ -n "$PID" ] && kill "$PID" 2>/dev/null || true
    rm -rf "$DATA_DIR"
}
trap cleanup EXIT

DRAFT_ASSISTANT_HOME="$DATA_DIR" \
DRAFT_ASSISTANT_PORT="$PORT" \
DRAFT_ASSISTANT_NO_OPEN=1 \
    "$BIN" --browser &
PID=$!

deadline=$(( $(date +%s) + TIMEOUT ))
ready=0
while [ "$(date +%s)" -lt "$deadline" ]; do
    if ! kill -0 "$PID" 2>/dev/null; then
        echo "ERROR: app exited early" >&2
        exit 1
    fi
    if curl -fsS "http://127.0.0.1:$PORT/api/state" >/dev/null 2>&1; then
        ready=1
        break
    fi
    sleep 0.5
done

[ "$ready" -eq 1 ] || { echo "ERROR: app did not serve /api/state in ${TIMEOUT}s" >&2; exit 1; }

curl -fsS "http://127.0.0.1:$PORT/" | grep -qi draft \
    || { echo "ERROR: served page does not look like the Draft Assistant UI" >&2; exit 1; }

BOARD="$DATA_DIR/data/projections.json"
[ -f "$BOARD" ] || { echo "ERROR: first-run seeding did not create $BOARD" >&2; exit 1; }

PLAYERS=$(python3 -c "import json,sys; print(len(json.load(open(sys.argv[1]))['players']))" "$BOARD")
[ "$PLAYERS" -gt 0 ] || { echo "ERROR: seeded player board is empty" >&2; exit 1; }

echo "  smoke test OK - served UI, seeded $PLAYERS players"
