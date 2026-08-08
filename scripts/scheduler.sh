#!/bin/bash
# Pre-market Radar — launchd scheduler control.
#
#   ./scripts/scheduler.sh install     generate + load the LaunchAgent
#   ./scripts/scheduler.sh uninstall   unload + remove it
#   ./scripts/scheduler.sh status      is it loaded? what has been sent?
#   ./scripts/scheduler.sh log         tail the autorun log
#
# The agent ticks every 5 minutes and calls `python -m src.autorun`, which
# decides in ET whether a report is due and whether it has already gone out.
# The tick is cheap (no network unless a report is actually due), which is what
# lets us schedule by polling instead of by wall-clock — see src/autorun.py.
set -euo pipefail

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LABEL="com.premarket-radar.scheduler"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
PYTHON="$REPO/.venv/bin/python"

cmd="${1:-status}"

case "$cmd" in
install)
    [ -x "$PYTHON" ] || { echo "no venv python at $PYTHON" >&2; exit 1; }
    mkdir -p "$REPO/output/logs" "$HOME/Library/LaunchAgents"

    cat > "$PLIST" <<PLIST_EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$LABEL</string>
    <key>ProgramArguments</key>
    <array>
        <string>$PYTHON</string>
        <string>-m</string>
        <string>src.autorun</string>
    </array>
    <key>WorkingDirectory</key>
    <string>$REPO</string>
    <!-- Tick every 5 min. StartInterval is not aligned to the wall clock, so
         the interval is also the worst-case lateness for hitting the 08:30 ET
         start the 09:00 delivery target depends on. An idle tick costs no
         network I/O. launchd fires a missed interval once on wake, which is
         exactly the catch-up behaviour we want after sleep. -->
    <key>StartInterval</key>
    <integer>300</integer>
    <key>RunAtLoad</key>
    <true/>
    <!-- Without this, macOS throttles the agent as background work and defers
         the interval indefinitely on battery ("pended nondemand spawn" in
         `launchctl print`, observed: 46 min with zero 300s ticks). Interactive
         opts out of that task policy. -->
    <key>ProcessType</key>
    <string>Interactive</string>
    <key>StandardOutPath</key>
    <string>$REPO/output/logs/launchd.out.log</string>
    <key>StandardErrorPath</key>
    <string>$REPO/output/logs/launchd.err.log</string>
</dict>
</plist>
PLIST_EOF

    launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
    launchctl bootstrap "gui/$UID" "$PLIST"
    echo "installed: $PLIST"
    echo "ticking every 5 min → $PYTHON -m src.autorun"
    ;;

uninstall)
    launchctl bootout "gui/$UID/$LABEL" 2>/dev/null || true
    rm -f "$PLIST"
    echo "uninstalled: $LABEL"
    ;;

status)
    if launchctl print "gui/$UID/$LABEL" >/dev/null 2>&1; then
        echo "loaded: $LABEL"
        launchctl print "gui/$UID/$LABEL" | grep -E "^\s+(state|last exit code|runs) " || true
    else
        echo "NOT loaded — run: ./scripts/scheduler.sh install"
    fi
    echo
    "$PYTHON" -m src.autorun --status
    ;;

log)
    tail -n "${2:-40}" "$REPO/output/logs/autorun.log"
    ;;

*)
    sed -n '2,9p' "${BASH_SOURCE[0]}"
    exit 1
    ;;
esac
