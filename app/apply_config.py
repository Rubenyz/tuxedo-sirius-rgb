#!/usr/bin/env python3
"""
Apply keyboard config from GUI editor at boot
"""
import json
import os
import sys
import colorsys

def hsv_to_rgb(h, s, v):
    """Convert HSV (0-360, 0-255, 0-255) to RGB (0-255)"""
    # Normalize HSV to 0-1 range
    h_norm = h / 360.0
    s_norm = s / 255.0
    v_norm = v / 255.0
    
    # Convert to RGB (0-1 range)
    r, g, b = colorsys.hsv_to_rgb(h_norm, s_norm, v_norm)
    
    # Convert to 0-255 range
    return int(r * 255), int(g * 255), int(b * 255)

def apply_config():
    # Resolve paths relative to this script's location
    project_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    configs_dir = os.path.join(project_dir, "configs")
    last_config_file = os.path.join(configs_dir, ".last_config")
    
    # Read last used config, fallback to tuxedo.json
    config_filename = "tuxedo.json"
    if os.path.exists(last_config_file):
        try:
            with open(last_config_file, 'r') as f:
                config_filename = f.read().strip()
        except Exception:
            pass
    
    config_file = os.path.join(configs_dir, config_filename)
    
    # If last config doesn't exist, fallback to tuxedo.json
    if not os.path.exists(config_file):
        config_file = os.path.join(configs_dir, "tuxedo.json")
    
    sysfs_batch = "/sys/kernel/tuxedo_nb04_rgb_perkey/batch"
    sysfs_lightbar = "/sys/kernel/tuxedo_nb04_rgb_perkey/lightbar"
    
    # Check if config file exists
    if not os.path.exists(config_file):
        print(f"Config file not found: {config_file}")
        return False
    
    print(f"Loading config: {config_filename}")
    
    # Check if sysfs interface exists
    if not os.path.exists(sysfs_batch):
        print(f"Sysfs interface not found: {sysfs_batch}")
        return False
    
    try:
        # Load config (includes presets)
        with open(config_file, 'r') as f:
            config = json.load(f)
        
        print(f"Loaded config with {len(config['keys'])} keys")
        
        # Build batch data from config + presets
        batch_data = bytearray()
        for key in config['keys']:
            key_id = key['id']
            preset_idx = key.get('preset', 0)
            
            # Get HSV from preset
            preset = config['presets'][preset_idx]
            h = preset.get('h', 0)
            s = preset.get('s', 0)
            v = preset.get('v', 0)
            
            # Convert to RGB
            r, g, b = hsv_to_rgb(h, s, v)
            
            batch_data.append(key_id)
            batch_data.append(r)
            batch_data.append(g)
            batch_data.append(b)
        
        # Write to sysfs
        with open(sysfs_batch, 'wb') as f:
            f.write(bytes(batch_data))
        
        print(f"Applied {len(config['keys'])} keys to keyboard")
        
        # Apply lightbar if config has it and sysfs exists
        lightbar = config.get('lightbar', {})
        if lightbar and os.path.exists(sysfs_lightbar):
            for side, zone in (('left', 16), ('right', 32)):
                preset_idx = lightbar.get(side, {}).get('preset', 0)
                if 0 <= preset_idx < len(config['presets']):
                    preset = config['presets'][preset_idx]
                    h = preset.get('h', 0)
                    s = preset.get('s', 0)
                    v = preset.get('v', 0)
                    r, g, b = hsv_to_rgb(h, s, v)
                else:
                    r, g, b = 0, 0, 0
                # Always enable=1 - using enable=0 disables entire RGB controller
                with open(sysfs_lightbar, 'w') as f:
                    f.write(f"{zone} {r} {g} {b} 10 1")
            print("Applied lightbar")
        
        return True
        
    except Exception as e:
        print(f"Error applying config: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = apply_config()
    sys.exit(0 if success else 1)
