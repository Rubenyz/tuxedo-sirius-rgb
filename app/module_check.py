#!/usr/bin/env python3
"""
Controle en automatisch (her)laden van de tuxedo_nb04_rgb_perkey kernelmodule.

Doel: wie dit project kloont kan het direct gebruiken. Ontbreekt de module
of past hij niet bij de draaiende kernel (vermagic-mismatch, bv. na een
kernel-update), dan wordt hij automatisch (her)gebouwd en geladen via een
root-helper (ensure-module.sh) achter een grafische wachtwoordprompt.

Geen Qt-afhankelijkheden hier, zodat dit ook headless/los bruikbaar is.
"""

import os
import platform
import shutil
import subprocess
from pathlib import Path

MODULE = "tuxedo_nb04_rgb_perkey"
SYSFS_BATCH = Path(f"/sys/kernel/{MODULE}/batch")
PROJECT_DIR = Path(__file__).resolve().parent.parent
ENSURE_SCRIPT = PROJECT_DIR / "ensure-module.sh"


def module_loaded() -> bool:
    """True als de module geladen is en de sysfs-interface beschikbaar is."""
    return SYSFS_BATCH.exists()


def _running_kernel() -> str:
    return platform.uname().release


def installed_vermagic() -> str | None:
    """
    Vermagic van de op schijf geïnstalleerde module (via modinfo), of None
    als modinfo de module niet kan vinden. Het eerste veld is de kernelversie.
    """
    modinfo = shutil.which("modinfo") or "/sbin/modinfo"
    try:
        out = subprocess.run(
            [modinfo, "-F", "vermagic", MODULE],
            capture_output=True, text=True, timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if out.returncode != 0:
        return None
    return out.stdout.strip() or None


def needs_rebuild() -> bool:
    """
    True als er (waarschijnlijk) een herbouw nodig is: de module ontbreekt op
    schijf, of de vermagic-kernelversie wijkt af van de draaiende kernel.
    """
    vermagic = installed_vermagic()
    if not vermagic:
        return True
    module_kernel = vermagic.split()[0]
    return module_kernel != _running_kernel()


def diagnosis() -> str:
    """Korte, leesbare uitleg van de huidige modulestatus."""
    if module_loaded():
        return "Module geladen."
    vermagic = installed_vermagic()
    if not vermagic:
        return "Module is niet gebouwd/geïnstalleerd voor deze kernel."
    module_kernel = vermagic.split()[0]
    running = _running_kernel()
    if module_kernel != running:
        return (f"Module is gebouwd voor kernel {module_kernel}, "
                f"maar je draait {running} (vermagic-mismatch).")
    return "Module is geïnstalleerd maar niet geladen."


def _root_runner() -> list[str] | None:
    """
    Bepaal hoe we een commando als root draaien. pkexec geeft een grafische
    prompt (geen terminal nodig); val anders terug op sudo.
    """
    if os.geteuid() == 0:
        return []  # al root
    if shutil.which("pkexec") and os.environ.get("DISPLAY"):
        return ["pkexec"]
    if shutil.which("sudo"):
        return ["sudo"]
    return None


def ensure_module() -> tuple[bool, str]:
    """
    Zorg dat de module geladen is. Probeert zo nodig een (her)bouw via de
    root-helper. Retourneert (ok, melding).
    """
    if module_loaded():
        return True, "Module al geladen."

    if not ENSURE_SCRIPT.exists():
        return False, f"Helper-script ontbreekt: {ENSURE_SCRIPT}"

    runner = _root_runner()
    if runner is None:
        return False, ("Geen manier gevonden om als root te draaien "
                       "(pkexec/sudo ontbreekt). Draai handmatig: "
                       f"sudo {ENSURE_SCRIPT}")

    cmd = runner + ["/bin/bash", str(ENSURE_SCRIPT)]
    try:
        proc = subprocess.run(cmd, timeout=300)
    except subprocess.TimeoutExpired:
        return False, "Reparatie duurde te lang (time-out)."
    except OSError as exc:
        return False, f"Kon reparatie niet starten: {exc}"

    if module_loaded():
        return True, "Module geladen."

    if proc.returncode != 0:
        return False, (f"{diagnosis()} Reparatie mislukte (exitcode "
                       f"{proc.returncode}). Zie: dmesg | tail -20")
    return False, ("Reparatie voltooid maar module nog niet beschikbaar. "
                   "Zie: dmesg | tail -20")


if __name__ == "__main__":
    import sys
    if "--diagnose" in sys.argv:
        # Alleen rapporteren, niets (her)laden.
        print(diagnosis())
        raise SystemExit(0)
    print(diagnosis())
    ok, msg = ensure_module()
    print(("✓ " if ok else "✗ ") + msg)
    raise SystemExit(0 if ok else 1)
