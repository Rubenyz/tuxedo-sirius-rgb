#!/usr/bin/env python3
"""
Keyboard RGB Color Configuration Manager
Loads layout, creates/loads/saves color configs
"""

import json
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent))
from kernel import TuxedoRGB


class ColorConfigManager:
    """Manages keyboard color configurations"""
    
    def __init__(self):
        """Initialize the config manager"""
        self.rgb = TuxedoRGB()
        self.layout = self.rgb.keyboard_layout
        
        if not self.layout:
            raise RuntimeError("Keyboard layout not loaded!")
        
        print(f"Loaded keyboard layout: {self.layout['keyboard']}")
        print(f"  Total keys: {self.layout['total_keys']}")
    
        # Load available keymaps
        self.keymaps_dir = Path(__file__).resolve().parent.parent / "layouts" / "keymaps"
        self.keymaps = self._load_keymaps()
    
    def _load_keymaps(self):
        """Scan layouts/keymaps/ and return {filename: keymap_dict}"""
        keymaps = {}
        if self.keymaps_dir.is_dir():
            for f in sorted(self.keymaps_dir.glob("*.json")):
                try:
                    with open(f, 'r') as fh:
                        keymaps[f.stem] = json.load(fh)
                except Exception as e:
                    print(f"Warning: Failed to load keymap {f.name}: {e}")
        return keymaps
    
    def get_key_label(self, hex_code, keymap_name=None):
        """Get display label for a key, using keymap if provided"""
        if keymap_name and keymap_name in self.keymaps:
            keys = self.keymaps[keymap_name].get("keys", {})
            if hex_code in keys:
                return keys[hex_code]
        # Fallback to layout name
        for key in self.layout['keys']:
            if key['hex'] == hex_code:
                return key['name']
        return hex_code
    
    def create_blank_config(self, name="Blank", all_black=True):
        """
        Create a new blank configuration
        
        Args:
            name: Config name
            all_black: If True, all keys are set to Black preset, else no keys defined
        
        Returns:
            Config dict
        """
        config = {
            "name": name,
            "keys": [],
            "presets": [
                {"h": 0, "s": 0, "v": 0},
            ],
            "lightbar": {
                "left": {"preset": 0},
                "right": {"preset": 0}
            }
        }
        
        if all_black:
            # Add all keys from layout with Black preset (index 0)
            for key in self.layout['keys']:
                config['keys'].append({
                    "id": int(key['hex'], 16),  # Convert hex string to int
                    "preset": 0  # Black is at index 0
                })
        
        return config
    
    def save_config(self, config, filename):
        """
        Save configuration to JSON file
        
        Args:
            config: Config dict
            filename: Path to save file
        """
        filepath = Path(filename)
        
        print(f"Saving config to {filepath}...")
        with open(filepath, 'w') as f:
            json.dump(config, f, indent=2)
        
        print(f"Saved {len(config['keys'])} keys")
    
    def load_config(self, filename):
        """
        Load configuration from JSON file
        
        Args:
            filename: Path to config file
        
        Returns:
            Config dict
        """
        filepath = Path(filename)
        
        if not filepath.exists():
            raise FileNotFoundError(f"Config file not found: {filepath}")
        
        print(f"Loading config from {filepath}...")
        with open(filepath, 'r') as f:
            config = json.load(f)
        
        # Backward compat: add lightbar section if missing
        if 'lightbar' not in config:
            config['lightbar'] = {
                'left': {'preset': 0},
                'right': {'preset': 0}
            }
        
        print(f"Loaded '{config['name']}'")
        print(f"  Keys: {len(config['keys'])}")
        
        return config
    
    def apply_config(self, config, changed_preset_idx=None):
        """
        Apply configuration to keyboard and lightbar.
        
        Args:
            config: Config dict
            changed_preset_idx: If set, only send hardware writes for
                                components using this preset index.
                                If None, send everything (full apply).
                                Special values: -1 = keys only, -2 = lightbar only
        """
        import colorsys
        
        print(f"Applying config: {config['name']}")
        
        presets = self.get_or_create_presets(config)
        
        lightbar = config.get('lightbar', {})

        # Determine what needs updating
        if changed_preset_idx == -1:
            # Keys only
            keys_dirty = True
            lightbar_dirty = False
        elif changed_preset_idx == -2:
            # Lightbar only
            keys_dirty = False
            lightbar_dirty = True
        elif changed_preset_idx is None:
            # Full apply
            keys_dirty = True
            lightbar_dirty = True
        else:
            # Preset change - check who uses it
            keys_dirty = any(
                key.get('preset') == changed_preset_idx for key in config['keys']
            )
            lightbar_dirty = any(
                lightbar.get(side, {}).get('preset') == changed_preset_idx
                for side in ('left', 'right')
            )
        
        # Apply per-key colors (method 6)
        if keys_dirty:
            batch_data = []
            for key in config['keys']:
                preset_idx = key.get('preset', 0)
                if 0 <= preset_idx < len(presets):
                    preset = presets[preset_idx]
                    h = preset['h'] / 360.0
                    s = preset['s'] / 255.0
                    v = preset['v'] / 255.0
                    r, g, b = colorsys.hsv_to_rgb(h, s, v)
                    r, g, b = int(r * 255), int(g * 255), int(b * 255)
                else:
                    r, g, b = 0, 0, 0
                batch_data.append((key['id'], r, g, b))
            
            if batch_data:
                for i in range(0, len(batch_data), 120):
                    chunk = batch_data[i:i+120]
                    self.rgb.set_keys_batch(chunk)
                print(f"Applied {len(batch_data)} keys")
        
        # Apply lightbar colors (method 3)
        if lightbar_dirty:
            for side, zone in (('left', 0x10), ('right', 0x20)):
                preset_idx = lightbar.get(side, {}).get('preset', 0)
                if 0 <= preset_idx < len(presets):
                    preset = presets[preset_idx]
                    h = preset['h'] / 360.0
                    s = preset['s'] / 255.0
                    v = preset['v'] / 255.0
                    r, g, b = colorsys.hsv_to_rgb(h, s, v)
                    r, g, b = int(r * 255), int(g * 255), int(b * 255)
                else:
                    r, g, b = 0, 0, 0
                self.rgb.set_lightbar(zone, r, g, b)
            print("Applied lightbar")
    
    def get_key_info(self, key_id):
        """Get key information from layout"""
        for key in self.layout['keys']:
            if key['id'] == key_id:
                return key
        return None
    
    def add_key_to_config(self, config, key_id, preset_idx):
        """
        Add or update a key in the config with preset index
        
        Args:
            config: Config dict
            key_id: Key ID to add/update
            preset_idx: Index of the preset to use
        """
        # Check if key exists, update it
        for key in config['keys']:
            if key['id'] == key_id:
                key['preset'] = preset_idx
                return
        
        # Add new key
        config['keys'].append({
            "id": key_id,
            "preset": preset_idx
        })
    
    def get_key_rgb(self, config, key_id):
        """
        Get RGB values for a key based on its preset
        
        Args:
            config: Config dict
            key_id: Key ID
        
        Returns:
            (r, g, b) tuple or (0, 0, 0) if not found
        """
        import colorsys
        
        for key in config['keys']:
            if key['id'] == key_id:
                preset_idx = key.get('preset', 0)
                presets = self.get_or_create_presets(config)
                if 0 <= preset_idx < len(presets):
                    preset = presets[preset_idx]
                    # Convert HSV to RGB
                    h = preset['h'] / 360.0
                    s = preset['s'] / 255.0
                    v = preset['v'] / 255.0
                    r, g, b = colorsys.hsv_to_rgb(h, s, v)
                    return (int(r * 255), int(g * 255), int(b * 255))
                return (0, 0, 0)
        
        return (0, 0, 0)
    
    def get_or_create_presets(self, config):
        """
        Get presets from config, or create default presets if not present
        
        Args:
            config: Config dict
        
        Returns:
            List of preset dicts: [{"h": int, "s": int, "v": int}, ...]
        """
        if "presets" not in config:
            # Create default presets in HSV format (H: 0-360, S: 0-255, V: 0-255)
            # Black is always first (index 0) and not editable
            config["presets"] = [
                {"h": 0, "s": 0, "v": 0},          # 0: Black (not editable)
                {"h": 0, "s": 255, "v": 255},      # 1: Red
                {"h": 120, "s": 255, "v": 255},    # 2: Green
                {"h": 240, "s": 255, "v": 255},    # 3: Blue
                {"h": 60, "s": 255, "v": 255},     # 4: Yellow
                {"h": 300, "s": 255, "v": 255},    # 5: Purple
                {"h": 180, "s": 255, "v": 255},    # 6: Cyan
                {"h": 0, "s": 0, "v": 255}         # 7: White
            ]
        
        return config["presets"]
    
    def update_preset(self, config, preset_idx, h, s, v):
        """
        Update or create a preset color by index
        
        Args:
            config: Config dict
            preset_idx: Index of the preset to update
            h, s, v: HSV values (H: 0-360, S: 0-255, V: 0-255)
        
        Returns:
            True if successful, False otherwise
        """
        # Don't allow editing Black (preset 0)
        if preset_idx == 0:
            return False
        
        presets = self.get_or_create_presets(config)
        
        # Check if preset index exists
        if 0 <= preset_idx < len(presets):
            presets[preset_idx]["h"] = h
            presets[preset_idx]["s"] = s
            presets[preset_idx]["v"] = v
            return True
        
        return False
    
    def get_preset_color(self, config, preset_idx):
        """
        Get HSV values for a preset color by index
        
        Args:
            config: Config dict
            preset_idx: Index of the preset (0-7)
        
        Returns:
            (h, s, v) tuple or (0, 0, 0) if not found
        """
        presets = self.get_or_create_presets(config)
        
        if 0 <= preset_idx < len(presets):
            preset = presets[preset_idx]
            return (preset["h"], preset["s"], preset["v"])
        
        return (0, 0, 0)
    
    def add_preset(self, config, h=0, s=255, v=255):
        """
        Add a new preset to the config (appended at end)
        
        Args:
            config: Config dict
            h, s, v: HSV values for new preset
        
        Returns:
            Index of the new preset, or -1 if failed
        """
        presets = self.get_or_create_presets(config)
        
        new_preset = {"h": h, "s": s, "v": v}
        presets.append(new_preset)
        new_idx = len(presets) - 1
        print(f"Added preset at index {new_idx}: HSV({h}, {s}, {v})")
        return new_idx
    
    def remove_preset(self, config, preset_idx):
        """
        Remove a preset from the config (cannot remove Black)
        
        Args:
            config: Config dict
            preset_idx: Index of preset to remove
        
        Returns:
            True if successful, False otherwise
        """
        presets = self.get_or_create_presets(config)
        
        # Don't allow removing Black (preset 0)
        if preset_idx == 0:
            print(f"Cannot remove Black preset (index 0)")
            return False
        
        # Cannot remove if only 1 preset left (must keep Black)
        if len(presets) <= 1:
            print(f"Cannot remove last preset")
            return False
        
        # Remove the preset
        removed = presets.pop(preset_idx)
        print(f"Removed preset {preset_idx}: HSV({removed['h']}, {removed['s']}, {removed['v']})")
        
        # Update any keys that used this preset
        # Keys using the removed preset should switch to Black (index 0)
        for key in config.get('keys', []):
            if key.get('preset') == preset_idx:
                key['preset'] = 0  # Switch to Black
            elif key.get('preset', 0) > preset_idx:
                # Shift down indices for presets after the removed one
                key['preset'] -= 1
        
        return True

    # ── Palette management ──

    def _palette_path(self):
        """Get path to global palette file"""
        return Path(__file__).resolve().parent.parent / "configs" / "palette.json"

    def load_palette(self):
        """Load global color palette, return list of color dicts"""
        path = self._palette_path()
        if path.exists():
            try:
                with open(path, 'r') as f:
                    data = json.load(f)
                return data.get("colors", [])
            except Exception as e:
                print(f"Warning: Failed to load palette: {e}")
        return []

    def save_to_palette(self, h, s, v, name=""):
        """Add a color to the global palette"""
        colors = self.load_palette()
        entry = {"h": h, "s": s, "v": v}
        if name:
            entry["name"] = name
        # Avoid exact duplicates
        for c in colors:
            if c.get("h") == h and c.get("s") == s and c.get("v") == v:
                return
        colors.append(entry)
        path = self._palette_path()
        with open(path, 'w') as f:
            json.dump({"colors": colors}, f, indent=2)
        print(f"Saved color to palette: HSV({h}, {s}, {v})")

    def get_colors_from_all_configs(self, exclude_path=None):
        """Collect unique preset colors from all config files (excluding current)"""
        config_dir = Path(__file__).resolve().parent.parent / "configs"
        colors = []
        seen = set()
        for cfg_file in sorted(config_dir.glob("*.json")):
            if cfg_file.name == "palette.json":
                continue
            if exclude_path and cfg_file == Path(exclude_path):
                continue
            try:
                with open(cfg_file, 'r') as f:
                    data = json.load(f)
                for preset in data.get("presets", []):
                    key = (preset.get("h", 0), preset.get("s", 0), preset.get("v", 0))
                    if key not in seen and key != (0, 0, 0):
                        seen.add(key)
                        colors.append(preset)
            except Exception:
                pass
        return colors


if __name__ == "__main__":
    manager = ColorConfigManager()
    print(f"Layout: {manager.layout['keyboard']}, Keys: {manager.layout['total_keys']}")
