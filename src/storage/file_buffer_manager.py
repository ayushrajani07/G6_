"""Buffered file writer with LRU-managed open handles.

This utility batches CSV row writes per file and periodically flushes to disk,
reducing the overhead of opening/closing files on every write. It enforces a
limit on concurrently open file handles using a simple LRU eviction policy.

Notes:
- Designed to be lightweight, thread-agnostic (call from single writer thread).
- Flushes on either time threshold or row-count threshold.
"""
from __future__ import annotations

import csv
import os
import time
from dataclasses import dataclass, field
from typing import Any, TextIO


@dataclass
class _FileEntry:
    path: str
    fh: TextIO
    writer: Any
    header_written: bool
    pending: list[list[object]] = field(default_factory=list)
    last_access: float = field(default_factory=time.time)
    last_flush: float = field(default_factory=time.time)


class FileBufferManager:
    def __init__(
        self,
        max_open_files: int = 64,
        flush_interval_seconds: float = 2.0,
        buffer_size: int = 0,
        newline: str = "",
        encoding: str = "utf-8",
    ) -> None:
        self.max_open_files = max(1, int(max_open_files))
        self.flush_interval_seconds = max(0.1, float(flush_interval_seconds))
        self.buffer_size = max(0, int(buffer_size))
        self.newline = newline
        self.encoding = encoding
        self._files: dict[str, _FileEntry] = {}

    # ---------------- Public API ----------------
    def write_row(self, filepath: str, row: list[object], header: list[str] | None = None) -> None:
        """Queue a row for a file; create/open the file if needed.

        If file is new and header is provided, header is written immediately
        before any queued rows to keep schema consistent for first reader.
        """
        fe = self._ensure_file(filepath, header)
        fe.pending.append(row)
        fe.last_access = time.time()
        # Flush based on row threshold or time interval
        if self.buffer_size and len(fe.pending) >= self.buffer_size:
            self._flush_one(fe)
        else:
            if (time.time() - fe.last_flush) >= self.flush_interval_seconds:
                self._flush_one(fe)

    def flush_all(self, force: bool = True) -> None:
        for fe in list(self._files.values()):
            if force or fe.pending:
                self._flush_one(fe)

    def close_all(self) -> None:
        try:
            self.flush_all(force=True)
        finally:
            for path, fe in list(self._files.items()):
                try:
                    fe.fh.close()
                except Exception:
                    pass
                finally:
                    self._files.pop(path, None)

    # ---------------- Internals ----------------
    def _ensure_file(self, filepath: str, header: list[str] | None) -> _FileEntry:
        fe = self._files.get(filepath)
        if fe is not None:
            return fe
        # Enforce LRU constraint
        if len(self._files) >= self.max_open_files:
            self._evict_lru()
        # Open path (append if exists, else write)
        os.makedirs(os.path.dirname(filepath), exist_ok=True)
        file_exists = os.path.isfile(filepath)
        mode = "a" if file_exists else "w"
        fh = open(filepath, mode, newline=self.newline, encoding=self.encoding)
        # Help type checker: treat file handle as TextIO for csv writer
        fh_typed: TextIO = fh  # type: ignore[assignment]
        writer = csv.writer(fh_typed)
        fe = _FileEntry(path=filepath, fh=fh_typed, writer=writer, header_written=file_exists)
        self._files[filepath] = fe
        # Header for new file
        if (not fe.header_written) and header:
            writer.writerow(header)
            fe.header_written = True
            fh_typed.flush()
        return fe

    def _flush_one(self, fe: _FileEntry) -> None:
        if not fe.pending:
            fe.last_flush = time.time()
            return
        try:
            for row in fe.pending:
                fe.writer.writerow(row)
            fe.fh.flush()
        finally:
            fe.pending.clear()
            fe.last_flush = time.time()

    def _evict_lru(self) -> None:
        # Select least recently accessed
        if not self._files:
            return
        oldest_path = min(self._files, key=lambda p: self._files[p].last_access)
        fe = self._files.pop(oldest_path)
        try:
            # Ensure pending data is written before closing
            if fe.pending:
                for row in fe.pending:
                    fe.writer.writerow(row)
                fe.fh.flush()
        except Exception:
            pass
        finally:
            try:
                fe.fh.close()
            except Exception:
                pass
