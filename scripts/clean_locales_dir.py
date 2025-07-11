#!/usr/bin/env python3
"""
Script to clean up the locales directory by moving non-locale files/directories.
This fixes aiogram_i18n from trying to scan __pycache__, keys.py, etc. as locales.
"""

import shutil
from pathlib import Path

def clean_locales_directory():
    """Move non-locale files/directories out of the locales directory."""
    
    locales_dir = Path("bot/locales")
    
    if not locales_dir.exists():
        print(f"❌ Locales directory not found: {locales_dir}")
        return
    
    # Valid locale directories (only these should remain)
    valid_locales = {"en", "uk", "ru"}
    
    # Create a backup directory for moved files
    backup_dir = Path("bot/locales_backup")
    backup_dir.mkdir(exist_ok=True)
    
    print(f"🧹 Cleaning locales directory: {locales_dir}")
    print(f"📁 Moving non-locale files to: {backup_dir}")
    
    # Scan all items in locales directory
    for item in locales_dir.iterdir():
        if item.name in valid_locales:
            print(f"✅ Keeping locale directory: {item.name}")
            continue
            
        # Move non-locale items to backup directory
        target_path = backup_dir / item.name
        try:
            if target_path.exists():
                if target_path.is_dir():
                    shutil.rmtree(target_path)
                else:
                    target_path.unlink()
            
            shutil.move(str(item), str(target_path))
            print(f"📦 Moved {item.name} -> {target_path}")
        except Exception as e:
            print(f"❌ Failed to move {item.name}: {e}")
    
    print("🎉 Finished cleaning locales directory!")
    print(f"📝 Remaining items in locales:")
    for item in locales_dir.iterdir():
        print(f"   - {item.name}")

if __name__ == "__main__":
    clean_locales_directory() 