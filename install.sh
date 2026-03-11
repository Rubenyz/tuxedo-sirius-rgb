#!/bin/bash
# TUXEDO Sirius Per-Key RGB — Install Script
# Run this once after cloning the repository.

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "╔══════════════════════════════════════════════════╗"
echo "║  TUXEDO Sirius Per-Key RGB — Installer          ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── 1. Check prerequisites ──────────────────────────────
echo "▸ Checking prerequisites..."

if ! command -v python3 &>/dev/null; then
    echo "✗ python3 not found. Install it with your package manager."
    exit 1
fi

if ! python3 -m venv --help &>/dev/null; then
    echo "✗ python3-venv not found. Install it with:"
    echo "  Debian/Ubuntu: sudo apt install python3-venv"
    echo "  Fedora:        sudo dnf install python3"
    exit 1
fi

if ! command -v make &>/dev/null; then
    echo "✗ make not found. Install build tools:"
    echo "  Debian/Ubuntu: sudo apt install build-essential"
    echo "  Fedora:        sudo dnf groupinstall 'Development Tools'"
    exit 1
fi

KDIR="/lib/modules/$(uname -r)/build"
if [ ! -d "$KDIR" ]; then
    echo "✗ Kernel headers not found at $KDIR"
    echo "  Debian/Ubuntu: sudo apt install linux-headers-$(uname -r)"
    echo "  Fedora:        sudo dnf install kernel-devel"
    exit 1
fi

echo "  python3 ✓"
echo "  make    ✓"
echo "  kernel headers ✓"
echo ""

# ── 2. Build kernel module ──────────────────────────────
echo "▸ Building kernel module..."
cd "$SCRIPT_DIR/kernel"
make clean 2>/dev/null || true
make
echo ""

# ── 3. Install udev rule (sudo-free access) ─────────────
echo "▸ Installing udev rule for non-root access..."
RULES_SRC="$SCRIPT_DIR/kernel/99-tuxedo-perkey.rules"
RULES_DST="/etc/udev/rules.d/99-tuxedo-perkey.rules"

if [ -f "$RULES_DST" ]; then
    echo "  udev rule already installed, skipping"
else
    sudo cp "$RULES_SRC" "$RULES_DST"
    sudo udevadm control --reload-rules
    sudo udevadm trigger
    echo "  udev rule installed ✓"
fi
echo ""

# ── 4. Python virtual environment ───────────────────────
echo "▸ Setting up Python virtual environment..."
cd "$SCRIPT_DIR/app"

if [ ! -d ".venv" ]; then
    python3 -m venv .venv
    echo "  venv created ✓"
else
    echo "  venv already exists, skipping creation"
fi

echo "  Installing Python dependencies..."
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -r "$SCRIPT_DIR/requirements.txt"
echo "  dependencies installed ✓"
echo ""

# ── 5. Install systemd service ──────────────────────────
echo "▸ Installing systemd service (loads driver + applies config at boot)..."
SERVICE_SRC="$SCRIPT_DIR/systemd/tuxedo-perkey.service"
SERVICE_DST="/etc/systemd/system/tuxedo-perkey.service"

# Replace placeholder with actual install path
sed "s|__TUXEDO_PERKEY_DIR__|${SCRIPT_DIR}|g" "$SERVICE_SRC" | sudo tee "$SERVICE_DST" >/dev/null
sudo systemctl daemon-reload
sudo systemctl enable tuxedo-perkey.service
echo "  service enabled ✓"

echo "  Starting service now..."
sudo systemctl start tuxedo-perkey.service
echo "  service started ✓"
echo ""

# ── 6. DKMS setup (auto-rebuild on kernel updates) ──────
echo "▸ Setting up DKMS (auto-rebuild on kernel updates)..."
if command -v dkms &>/dev/null; then
    DKMS_NAME="tuxedo-nb04-rgb-perkey"
    DKMS_VER="1.0.0"
    DKMS_SRC="/usr/src/${DKMS_NAME}-${DKMS_VER}"

    # Remove old DKMS registration if present
    sudo dkms remove "${DKMS_NAME}/${DKMS_VER}" --all 2>/dev/null || true

    # Symlink driver source into /usr/src/
    sudo rm -rf "$DKMS_SRC"
    sudo mkdir -p "$DKMS_SRC"
    sudo cp "$SCRIPT_DIR/kernel/tuxedo_nb04_rgb_perkey.c" "$DKMS_SRC/"
    sudo cp "$SCRIPT_DIR/kernel/Makefile" "$DKMS_SRC/"
    sudo cp "$SCRIPT_DIR/kernel/dkms.conf" "$DKMS_SRC/"

    sudo dkms add "${DKMS_NAME}/${DKMS_VER}"
    sudo dkms build "${DKMS_NAME}/${DKMS_VER}"
    sudo dkms install "${DKMS_NAME}/${DKMS_VER}"
    echo "  DKMS registered ✓ (module will auto-rebuild on kernel updates)"
else
    echo "  dkms not found, skipping (module must be rebuilt manually after kernel updates)"
    echo "  Install dkms: sudo apt install dkms  /  sudo dnf install dkms"
fi
echo ""

# ── 7. Install desktop entry (app menu launcher) ────────
echo "▸ Installing desktop menu entry..."
DESKTOP_SRC="$SCRIPT_DIR/tuxedo-keyboard-rgb.desktop"
DESKTOP_DST="/usr/share/applications/tuxedo-keyboard-rgb.desktop"

# Replace placeholder with actual install path
sed "s|__TUXEDO_PERKEY_DIR__|${SCRIPT_DIR}|g" "$DESKTOP_SRC" | sudo tee "$DESKTOP_DST" >/dev/null
sudo chmod 644 "$DESKTOP_DST"
echo "  desktop entry installed ✓"
echo ""

# ── Done ─────────────────────────────────────────────────
echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║  Installation complete!                         ║"
echo "╠══════════════════════════════════════════════════╣"
echo "║                                                 ║"
echo "║  ✓ Driver loaded and active                     ║"
echo "║  ✓ Config applied                               ║"
echo "║  ✓ Auto-start on boot enabled                   ║"
echo "║                                                 ║"
echo "║  Start the GUI:                                 ║"
echo "║    ./run_gui.sh                                 ║"
echo "║                                                 ║"
echo "║  Or find 'TUXEDO Keyboard RGB' in your          ║"
echo "║  application menu.                              ║"
echo "║                                                 ║"
echo "║  The GUI runs in the system tray.               ║"
echo "║  To close it, right-click the tray icon.        ║"
echo "╚══════════════════════════════════════════════════╝"
