#!/bin/bash
# Start the TUXEDO Keyboard RGB GUI Editor

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Run the GUI detached (background process)
nohup "$SCRIPT_DIR/app/.venv/bin/python" "$SCRIPT_DIR/app/main.py" >/dev/null 2>&1 &
GUI_PID=$!

echo "TUXEDO Keyboard RGB GUI started (PID: $GUI_PID)"
echo "Look for the keyboard icon in your system tray."
echo "To close the GUI, use the tray icon menu."
