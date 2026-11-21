#!/usr/bin/env python3
"""Print the file inventory of the project (useful for release checks)."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {"__pycache__", ".git", "userdata", ".pytest_cache"}

total = 0
for p in sorted(ROOT.rglob("*")):
    if any(part in SKIP_DIRS for part in p.parts):
        continue
    if p.is_file():
        total += 1
        print(f"{p.relative_to(ROOT)}  ({p.stat().st_size} bytes)")
print(f"\n{total} files")
sys.exit(0)
