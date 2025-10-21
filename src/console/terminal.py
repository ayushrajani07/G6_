"""Minimal Rich-based terminal UI (attach mode only).
Reads runtime status JSON and tails log file.
"""
from __future__ import annotations

import json
import os
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Any

try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.live import Live
    from rich.panel import Panel
    from rich.table import Table
    from rich.text import Text
    RICH_AVAILABLE = True
except Exception:  # pragma: no cover
    RICH_AVAILABLE = False

@dataclass
class TerminalConfig:
    status_file: str = "runtime_status.json"
    log_file: str = "logs/g6_platform.log"
    refresh_hz: int = 4
    log_tail_lines: int = 200
    patterns: list[dict[str,str]] = field(default_factory=list)


def load_terminal_config(path: str = "config/g6_terminal.json") -> TerminalConfig:
    cfg = TerminalConfig()
    try:
        with open(path,encoding='utf-8') as f:
            raw = json.load(f)
        cfg.refresh_hz = int(raw.get('refresh_hz', cfg.refresh_hz))
        cfg.log_tail_lines = int(raw.get('log_tail_lines', cfg.log_tail_lines))
        cfg.status_file = raw.get('status_file', cfg.status_file)
        # fallback to provided key if not present
        cfg.patterns = raw.get('log_patterns', [])
    except Exception:
        pass
    return cfg

class TerminalUI:
    def __init__(self, config: TerminalConfig):
        self.cfg = config
        self.console = Console() if RICH_AVAILABLE else None
        self._stop = threading.Event()
        self._log_pos = 0
        self.log_entries: list[str] = []
        self.status_snapshot: dict[str, Any] = {}
        self.pattern_compiled = []
        for p in self.cfg.patterns:
            try:
                self.pattern_compiled.append((p.get('name'), re.compile(p.get('regex','')), p.get('color','white')))
            except Exception:
                continue

    def stop(self):
        self._stop.set()

    def _read_status(self):
        path = self.cfg.status_file
        if not path or not os.path.exists(path):
            return
        try:
            with open(path,encoding='utf-8') as f:
                self.status_snapshot = json.load(f)
        except Exception:
            pass

    def _tail_log(self):
        lf = self.cfg.log_file
        try:
            with open(lf,encoding='utf-8',errors='ignore') as f:
                f.seek(self._log_pos)
                new = f.readlines()
                self._log_pos = f.tell()
        except FileNotFoundError:
            new = []
        except Exception:
            new = []
        for line in new:
            line = line.rstrip('\n')
            colored = line
            for name, comp, color in self.pattern_compiled:
                try:
                    if comp.search(line):
                        colored = f"[{color}]{line}[/{color}]"
                        break
                except Exception:
                    pass
            self.log_entries.append(colored)
        if len(self.log_entries) > self.cfg.log_tail_lines:
            self.log_entries = self.log_entries[-self.cfg.log_tail_lines:]

    def _render(self):
        if not RICH_AVAILABLE:
            return "Rich not installed"
        layout = Layout()
        layout.split_column(
            Layout(name='header', size=3),
            Layout(name='body', ratio=2),
            Layout(name='logs', ratio=3),
        )
        # Header
        ts = self.status_snapshot.get('ts','--')
        cycle = self.status_snapshot.get('cycle','--')
        header_text = Text(f"G6 TERMINAL  Cycle={cycle}  TS={ts}", style='bold cyan')
        layout['header'].update(Panel(header_text))
        # Body (status metrics)
        body_table = Table(box=None)
        body_table.add_column('Metric', style='bold')
        body_table.add_column('Value')
        for k in ('last_cycle_s','avg_cycle_s','success_cycles','failed_cycles'):
            if k in self.status_snapshot:
                body_table.add_row(k, str(self.status_snapshot.get(k)))
        # Indices summary
        idx = self.status_snapshot.get('indices', {})
        if idx:
            body_table.add_row('indices', ','.join(idx.keys()))
        layout['body'].update(Panel(body_table, title='Status'))
        # Logs
        log_panel = Panel('\n'.join(self.log_entries[-self.cfg.log_tail_lines:]) or 'No logs yet', title='Logs')
        layout['logs'].update(log_panel)
        return layout

    def run(self):
        if not RICH_AVAILABLE:
            print("Rich not available - install rich to use terminal UI")
            return
        refresh = 1.0 / max(1,self.cfg.refresh_hz)
        with Live(auto_refresh=False, screen=False) as live:
            while not self._stop.is_set():
                self._read_status()
                self._tail_log()
                live.update(self._render(), refresh=True)
                time.sleep(refresh)

if __name__ == '__main__':  # manual debugging
    ui = TerminalUI(load_terminal_config())
    ui.run()
