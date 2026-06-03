#!/bin/bash
# TUXEDO Per-Key RGB — zorgt dat de kernelmodule geladen is.
#
# Escalatieladder (snel -> zwaar):
#   1. sysfs al aanwezig?            -> klaar
#   2. modprobe (module bestaat al)  -> klaar
#   3. volledige DKMS-(her)bouw via fix-module.sh
#
# Bedoeld om als root aangeroepen te worden (door de app via pkexec).
#   sudo ./ensure-module.sh

set -euo pipefail

MODULE="tuxedo_nb04_rgb_perkey"
SYSFS="/sys/kernel/${MODULE}/batch"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# 1. Al geladen?
if [ -e "$SYSFS" ]; then
    exit 0
fi

if [ "$(id -u)" -ne 0 ]; then
    echo "✗ Moet als root draaien (sudo / pkexec)." >&2
    exit 1
fi

# Conflicterende stockmodules lossen
modprobe -r tuxedo_nb04_keyboard 2>/dev/null || true
modprobe -r tuxedo_nb04_wmi_ab   2>/dev/null || true

# 2. Eenvoudig laden — werkt als de module voor deze kernel al bestaat
#    (bv. DKMS heeft 'm al automatisch herbouwd na een kernel-update).
if modprobe "$MODULE" 2>/dev/null && [ -e "$SYSFS" ]; then
    echo "✓ Module geladen via modprobe."
    exit 0
fi

# 3. Module ontbreekt of past niet bij deze kernel -> volledige reparatie.
echo "→ Module niet laadbaar voor huidige kernel; volledige DKMS-(her)bouw..."
exec "$SCRIPT_DIR/fix-module.sh"
