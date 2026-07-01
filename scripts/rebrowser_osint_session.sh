#!/usr/bin/env bash
# Launch the dedicated OSINT capture browser (separate from the wispr lanes on
# :95 / ports 9223-9230). One persistent Chromium on display :96, CDP port 9250,
# its own profile. The operator logs into the accounts they need; this launcher
# never navigates to any login page or handles credentials.
#
# Env (no committed loopback/host defaults; runtime values required):
#   REBROWSER_CHROME_BIN   - chrome binary
#   REBROWSER_PROFILE_DIR  - dedicated OSINT profile dir
#   REBROWSER_DISPLAY      - X display (default :96)
#   REBROWSER_OSINT_PORT   - CDP port (default 9250)
set -uo pipefail

CHROME="${REBROWSER_CHROME_BIN:?REBROWSER_CHROME_BIN required}"
PROFILE="${REBROWSER_PROFILE_DIR:?REBROWSER_PROFILE_DIR required}"
DISPLAY="${REBROWSER_DISPLAY:-:96}"
PORT="${REBROWSER_OSINT_PORT:-9250}"

mkdir -p "$PROFILE"

# Ensure an X server is up on the chosen display (stale sockets get reused
# cleanly if present; otherwise start a headless Xvfb).
if ! pgrep -f "Xvfb $DISPLAY" >/dev/null 2>&1; then
  Xvfb "$DISPLAY" -screen 0 1280x900x24 >/dev/null 2>&1 &
fi
export DISPLAY

exec "$CHROME" \
  --user-data-dir="$PROFILE" \
  --remote-debugging-address=127.0.0.1 --remote-debugging-port="$PORT" \
  --no-first-run --no-default-browser-check --disable-dev-shm-usage \
  --disable-gpu-compositing --no-sandbox \
  --window-size=1200,800 \
  about:blank
