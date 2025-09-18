"""Console (Rich) terminal integration package.
Minimal attach-mode implementation for monitoring runtime_status.json and log tail.
"""
from .terminal import TerminalUI, load_terminal_config

__all__ = ["TerminalUI", "load_terminal_config"]
