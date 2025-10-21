"""Centralized CSV path generation for options and overview outputs.

Encapsulates directory layout and filename conventions to avoid duplication.
"""
from __future__ import annotations

import datetime as _dt
import os

from src.utils.path_utils import resolve_path


class CSVPathGenerator:
    def __init__(self, base_dir: str) -> None:
        # Resolve base_dir relative to project root if not absolute
        self.base_dir = resolve_path(base_dir)

    # ----------- Options per-strike paths -----------
    def option_offset_dir(self, index: str, expiry_code: str, offset: int) -> str:
        off_dir = f"+{offset}" if int(offset) > 0 else f"{int(offset)}"
        return os.path.join(self.base_dir, index, expiry_code, off_dir)

    def option_file_path(self, index: str, expiry_code: str, offset: int, date: _dt.date | _dt.datetime) -> str:
        if isinstance(date, _dt.datetime):
            date = date.date()
        dir_path = self.option_offset_dir(index, expiry_code, int(offset))
        return os.path.join(dir_path, f"{date.strftime('%Y-%m-%d')}.csv")

    def debug_file_path(self, index: str, expiry_code: str, date: _dt.date | _dt.datetime) -> str:
        if isinstance(date, _dt.datetime):
            date = date.date()
        exp_dir = os.path.join(self.base_dir, index, expiry_code)
        return os.path.join(exp_dir, f"{date.strftime('%Y-%m-%d')}_debug.json")

    # ----------- Overview paths -----------
    def overview_dir(self, index: str) -> str:
        return os.path.join(self.base_dir, "overview", index)

    def overview_file_path(self, index: str, date: _dt.date | _dt.datetime) -> str:
        if isinstance(date, _dt.datetime):
            date = date.date()
        return os.path.join(self.overview_dir(index), f"{date.strftime('%Y-%m-%d')}.csv")
