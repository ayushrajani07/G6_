"""Pytest configuration ensuring project root is importable.

Adds the repository root to sys.path so that 'src' package imports work
even when pytest is invoked in ways that omit CWD from sys.path.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))