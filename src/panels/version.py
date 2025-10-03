"""Panel schema version constants.

Provides a single authoritative place to bump the panel wrapper/schema
version. The wrapper emitted when G6_PANELS_SCHEMA_WRAPPER is enabled
now includes both a backward-compatible "version" field (legacy) and a
new explicit "schema_version" field kept in sync. Downstream consumers
should migrate to reading "schema_version".
"""

from __future__ import annotations

# Increment this when making a breaking change to the wrapper structure
PANEL_SCHEMA_VERSION: int = 1

# Alias for clarity / potential future differentiation
PANEL_WRAPPER_VERSION: int = PANEL_SCHEMA_VERSION

__all__ = ["PANEL_SCHEMA_VERSION", "PANEL_WRAPPER_VERSION"]
