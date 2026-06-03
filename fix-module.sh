#!/bin/bash
# TUXEDO Per-Key RGB — eenmalige module-fix / (her)registratie via DKMS
#
# Draai dit één keer met sudo wanneer de kernelmodule niet (meer) laadt,
# bijvoorbeeld na een kernel-update (vermagic-mismatch).
#
#   sudo ./fix-module.sh
#
# Het script registreert de driver in DKMS zodat hij voortaan bij elke
# kernel-update automatisch opnieuw gebouwd wordt.

set -euo pipefail

DKMS_NAME="tuxedo-nb04-rgb-perkey"
DKMS_VER="1.0.0"
DKMS_SRC="/usr/src/${DKMS_NAME}-${DKMS_VER}"
MODULE="tuxedo_nb04_rgb_perkey"

# Projectmap = map waarin dit script staat
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
KERNEL_DIR="$SCRIPT_DIR/kernel"

echo "==> TUXEDO Per-Key RGB module-fix"

# ── 0. sudo-check ───────────────────────────────────────────
if [ "$(id -u)" -ne 0 ]; then
    echo "✗ Dit script moet als root draaien. Gebruik: sudo $0"
    exit 1
fi

KVER="$(uname -r)"
echo "   draaiende kernel: $KVER"

# ── 1. Kernel-headers aanwezig? ─────────────────────────────
if [ ! -d "/lib/modules/$KVER/build" ]; then
    echo "✗ Kernel-headers ontbreken voor $KVER (/lib/modules/$KVER/build)."
    echo "  Installeer ze, bijv.:  sudo apt install linux-headers-$KVER"
    exit 1
fi
echo "   kernel-headers ✓"

# ── 2. Oude handmatige build-artefacten opruimen ────────────
# Voorkomt dat een oude .ko (verkeerde vermagic) per ongeluk geladen wordt.
echo "==> Oude build-artefacten in kernel/ opruimen"
rm -f "$KERNEL_DIR"/*.o "$KERNEL_DIR"/*.ko "$KERNEL_DIR"/*.mod \
      "$KERNEL_DIR"/*.mod.c "$KERNEL_DIR"/*.mod.o "$KERNEL_DIR"/.*.cmd \
      "$KERNEL_DIR"/Module.symvers "$KERNEL_DIR"/modules.order 2>/dev/null || true

# ── 3. DKMS aanwezig? ───────────────────────────────────────
if ! command -v dkms &>/dev/null; then
    echo "✗ dkms is niet geïnstalleerd. Installeer het, bijv.:"
    echo "    sudo apt install dkms     (Debian/Ubuntu)"
    echo "    sudo dnf install dkms     (Fedora)"
    exit 1
fi

# ── 4. Bestaande DKMS-registratie verwijderen ───────────────
echo "==> Bestaande DKMS-registratie opschonen (indien aanwezig)"
dkms remove "${DKMS_NAME}/${DKMS_VER}" --all 2>/dev/null || true

# ── 5. Bron naar /usr/src kopiëren ──────────────────────────
echo "==> Bron naar $DKMS_SRC kopiëren"
rm -rf "$DKMS_SRC"
mkdir -p "$DKMS_SRC"
cp "$KERNEL_DIR/${MODULE}.c" "$DKMS_SRC/"
cp "$KERNEL_DIR/Makefile"    "$DKMS_SRC/"
cp "$KERNEL_DIR/dkms.conf"   "$DKMS_SRC/"

# ── 6. Toevoegen, bouwen, installeren ───────────────────────
echo "==> DKMS add / build / install"
dkms add     "${DKMS_NAME}/${DKMS_VER}"
dkms build   "${DKMS_NAME}/${DKMS_VER}"
dkms install "${DKMS_NAME}/${DKMS_VER}" --force

# ── 7. Conflicterende stockmodules lossen + onze module laden ─
echo "==> Module laden"
modprobe -r tuxedo_nb04_keyboard 2>/dev/null || true
modprobe -r tuxedo_nb04_wmi_ab   2>/dev/null || true
modprobe "$MODULE"

# ── 8. Verifiëren ───────────────────────────────────────────
echo ""
echo "==> Status"
dkms status "${DKMS_NAME}/${DKMS_VER}"
if [ -e "/sys/kernel/${MODULE}/batch" ]; then
    echo "✓ Module geladen — sysfs-interface aanwezig: /sys/kernel/${MODULE}/batch"
else
    echo "✗ Module lijkt niet geladen — sysfs-interface ontbreekt."
    echo "  Kijk in: dmesg | tail -20"
    exit 1
fi

# ── 9. Systemd-service herstarten (indien geïnstalleerd) ────
if systemctl list-unit-files tuxedo-perkey.service &>/dev/null \
   && systemctl is-enabled tuxedo-perkey.service &>/dev/null; then
    echo "==> tuxedo-perkey.service herstarten"
    systemctl restart tuxedo-perkey.service || true
    systemctl --no-pager --lines=0 status tuxedo-perkey.service || true
fi

echo ""
echo "✓ Klaar. De module is via DKMS geregistreerd en herbouwt voortaan"
echo "  automatisch bij elke kernel-update."
