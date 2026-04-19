#!/usr/bin/env python3
"""Import a single OCR file to all four databases."""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))
from unified_four_db_import import UnifiedImporter

if len(sys.argv) < 2:
    print("Usage: python import_single_file.py <filename>")
    sys.exit(1)

filename = sys.argv[1]
importer = UnifiedImporter()
importer.initialize()

from pathlib import Path
from unified_four_db_import import OCR_OUTPUT_DIR, KB_DIR

# Find file
path = None
for base in [OCR_OUTPUT_DIR, KB_DIR]:
    if base == OCR_OUTPUT_DIR:
        candidates = list(base.glob(f"*{filename}*"))
    else:
        candidates = []
        for d in base.iterdir():
            if d.is_dir():
                candidates.extend(list(d.glob(f"*{filename}*")))
    for c in candidates:
        if c.name == filename or filename in c.name:
            path = c
            break
    if path:
        break

if not path:
    print(f"File not found: {filename}")
    sys.exit(1)

print(f"Importing: {path}")
n = importer.process_file(path)
print(f"Imported {n} chunks")
importer.close()
