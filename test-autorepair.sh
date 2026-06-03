#!/bin/bash
# TUXEDO Per-Key RGB — test de automatische module-reparatie.
#
# Simuleert een ontbrekende module (modprobe -r) en laat vervolgens de
# Python-laag (app/module_check.py -> ensure-module.sh) zichzelf herstellen.
# Draai met root:   sudo ./test-autorepair.sh
#
# User-onafhankelijk: alle paden zijn relatief aan dit script; de Python-venv
# wordt via het script-pad gevonden, niet via $HOME of een gebruikersnaam.

set -uo pipefail

MODULE="tuxedo_nb04_rgb_perkey"
SYSFS="/sys/kernel/${MODULE}/batch"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PY="$SCRIPT_DIR/app/.venv/bin/python"
CHECK="$SCRIPT_DIR/app/module_check.py"

if [ "$(id -u)" -ne 0 ]; then
    echo "✗ Draai dit met root: sudo $0"
    exit 1
fi

if [ ! -x "$PY" ]; then
    echo "✗ Python-venv niet gevonden op: $PY"
    echo "  Draai eerst install.sh om de venv aan te maken."
    exit 1
fi

# Python schrijft geen .pyc (voorkomt root-owned __pycache__ onder sudo)
export PYTHONDONTWRITEBYTECODE=1

step() { echo ""; echo "── $* ──"; }

step "1. Status vooraf"
"$PY" "$CHECK" || true
echo "   sysfs aanwezig: $([ -e "$SYSFS" ] && echo ja || echo nee)"

step "2. Module verwijderen (faalsituatie simuleren)"
modprobe -r "$MODULE" 2>/dev/null || true
if [ -e "$SYSFS" ]; then
    echo "✗ Module liet zich niet verwijderen — test kan niet doorgaan."
    echo "  (Is hij in gebruik? Sluit de GUI en probeer opnieuw.)"
    exit 1
fi
echo "✓ Module verwijderd — sysfs weg: $([ -e "$SYSFS" ] && echo nog-aanwezig || echo ja)"

step "3. Diagnose met module afwezig"
"$PY" "$CHECK" --diagnose

step "4. Automatische reparatie via app/module_check.py"
# Draait als root -> ensure_module() roept ensure-module.sh direct aan
# (geen pkexec nodig). Dit is exact wat de GUI doet, minus de wachtwoordprompt.
"$PY" "$CHECK"
RC=$?

step "5. Status achteraf"
if [ -e "$SYSFS" ]; then
    echo "✓ Module weer geladen — sysfs aanwezig: $SYSFS"
else
    echo "✗ Module NIET hersteld. Zie: dmesg | tail -20"
fi

echo ""
if [ -e "$SYSFS" ] && [ "$RC" -eq 0 ]; then
    echo "✓✓ Auto-reparatie geslaagd."
    exit 0
else
    echo "✗✗ Auto-reparatie mislukt (exitcode $RC)."
    exit 1
fi
