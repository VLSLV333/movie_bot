#!/usr/bin/env python3
"""
Simple script to compile .po files to .mo files using polib.
"""

import polib
import os
from pathlib import Path

def compile_po_to_mo():
    """Compile all .po files to .mo files in the locales directory."""
    locales_dir = Path('bot/locales')
    
    # Language directories to process
    languages = ['en', 'ru', 'uk']
    
    for lang in languages:
        po_file_path = locales_dir / lang / 'LC_MESSAGES' / 'messages.po'
        mo_file_path = locales_dir / lang / 'LC_MESSAGES' / 'messages.mo'
        
        print(f"Checking {lang}...")
        print(f"  PO file exists: {po_file_path.exists()}")
        print(f"  PO file path: {po_file_path}")
        
        if po_file_path.exists():
            print(f"Compiling {lang} translations...")
            try:
                # Load the .po file
                po = polib.pofile(str(po_file_path))
                
                # Save as .mo file
                po.save_as_mofile(str(mo_file_path))
                
                print(f"✅ Successfully compiled {lang} translations")
                print(f"   Source: {po_file_path}")
                print(f"   Output: {mo_file_path}")
                print(f"   Entries: {len(po)}")
                
            except Exception as e:
                print(f"❌ Failed to compile {lang} translations: {e}")
                import traceback
                traceback.print_exc()
        else:
            print(f"⚠️  .po file not found for {lang}: {po_file_path}")

if __name__ == "__main__":
    print("🚀 Compiling .po files to .mo files...")
    print("=" * 50)
    compile_po_to_mo()
    print("=" * 50)
    print("✅ Compilation complete!") 