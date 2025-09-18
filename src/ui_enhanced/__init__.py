"""Enhanced UI placeholder package.
Activates when feature flag G6_ENHANCED_UI is set (or CLI --enhanced-ui).
Contains safe fallbacks so production does not break if incomplete modules are present.
"""
from __future__ import annotations

ENHANCED_UI_AVAILABLE = True  # marker for conditional logic

__all__ = ["ENHANCED_UI_AVAILABLE"]
