#!/usr/bin/env python3
"""
Python library for TUXEDO Sirius Per-Key RGB control
Uses tuxedo_nb04_rgb_perkey kernel module via sysfs
"""

import json
from pathlib import Path
from typing import Dict, List, Tuple


class TuxedoRGB:
    """TUXEDO Sirius Per-Key RGB Controller - Low level interface to kernel module"""
    
    SYSFS_BATCH = Path("/sys/kernel/tuxedo_nb04_rgb_perkey/batch")
    SYSFS_LIGHTBAR = Path("/sys/kernel/tuxedo_nb04_rgb_perkey/lightbar")
    
    def __init__(self):
        """Initialize RGB controller"""
        if not self.SYSFS_BATCH.exists():
            raise RuntimeError(
                "Kernel module not loaded! Run: cd driver && sudo make install"
            )
        
        # Load keyboard layout for key validation
        self.keyboard_layout = None
        layout_file = Path(__file__).resolve().parent.parent / "layouts" / "keyboard_layout.json"
        if layout_file.exists():
            with open(layout_file, 'r') as f:
                self.keyboard_layout = json.load(f)
    
    def get_all_key_ids(self) -> List[int]:
        """Get list of all valid key IDs from layout"""
        if self.keyboard_layout:
            # Keys are stored with 'hex' field in keyboard_layout.json
            return [int(key['hex'], 16) for key in self.keyboard_layout.get('keys', [])]
        return list(range(256))  # Fallback to all possible IDs
    
    def _send_batch(self, data: bytes) -> None:
        """Send binary batch data to kernel driver"""
        try:
            with open(self.SYSFS_BATCH, 'wb') as f:
                f.write(data)
        except PermissionError:
            raise PermissionError(
                "Permission denied. Run script with sudo or add udev rule."
            )
    
    def set_keys_batch(self, keys_data: List[Tuple[int, int, int, int]]) -> None:
        """
        Set multiple keys at once using batch interface (FAST!)
        
        Args:
            keys_data: List of (key_id, r, g, b) tuples
                      Example: [(0x1A, 255, 0, 0), (0x04, 0, 255, 0)]
        """
        if not keys_data:
            return
        
        if len(keys_data) > 120:
            raise ValueError("Too many keys! Max 120 per batch")
        
        # Build binary data: KEY_ID R G B for each key
        batch = bytearray()
        for key_id, r, g, b in keys_data:
            if not (0 <= key_id <= 0xFF):
                raise ValueError(f"Key ID must be 0x00-0xFF, got {key_id}")
            if not all(0 <= c <= 255 for c in [r, g, b]):
                raise ValueError(f"RGB values must be 0-255, got ({r},{g},{b})")
            
            batch.append(key_id)
            batch.append(r)
            batch.append(g)
            batch.append(b)
        
        self._send_batch(bytes(batch))
    
    def all_black(self) -> None:
        """Turn all keys off (black) - sets all keyboard keys to black using batch"""
        key_ids = self.get_all_key_ids()
        batch_data = [(key_id, 0, 0, 0) for key_id in key_ids]
        
        # Send in batches of 120 (hardware limit)
        for i in range(0, len(batch_data), 120):
            chunk = batch_data[i:i+120]
            self.set_keys_batch(chunk)
    
    def all_white(self) -> None:
        """Turn all keys on (white) - sets all keyboard keys to white using batch"""
        key_ids = self.get_all_key_ids()
        batch_data = [(key_id, 255, 255, 255) for key_id in key_ids]
        
        # Send in batches of 120 (hardware limit)
        for i in range(0, len(batch_data), 120):
            chunk = batch_data[i:i+120]
            self.set_keys_batch(chunk)
    
    def set_lightbar(self, zone: int, r: int, g: int, b: int, brightness: int = 10) -> None:
        """
        Set lightbar LED color via method 3 zone control.
        
        Args:
            zone: 0x10 (left), 0x20 (right), or 0x30 (both)
            r, g, b: Color values 0-255
            brightness: Brightness 0-255 (default 10)
        
        Note: enable is always 1. To turn off, use RGB=(0,0,0).
              Setting enable=0 disables the entire RGB controller (including keyboard!)
        """
        enable = 1  # Always enabled - use RGB=(0,0,0) for "off"
        try:
            with open(self.SYSFS_LIGHTBAR, 'w') as f:
                f.write(f"{zone} {r} {g} {b} {brightness} {enable}")
        except FileNotFoundError:
            pass  # Lightbar sysfs not available (older driver)
        except PermissionError:
            raise PermissionError(
                "Permission denied. Run script with sudo or add udev rule."
            )
    
if __name__ == "__main__":
    print("TUXEDO Sirius RGB Control Library")
    print("Import this module to control your keyboard RGB")
    print("")
    print("Usage:")
    print("  from tuxedo_rgb import TuxedoRGB")
    print("  rgb = TuxedoRGB()")
    print("  rgb.set_keys_batch([(0x1A, 255, 0, 0)])  # Set W to red")
    print("  rgb.load_config('color-config.json')     # Load config")
