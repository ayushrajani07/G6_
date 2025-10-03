"""Kite provider modularization package (Phase 1).

Currently exposes only expiry resolution helper; future phases will move
more logic here and re-export public provider classes.
"""
from .expiries import resolve_expiry_rule  # re-export for convenience
from .synthetic import (
	generate_synthetic_instruments,
	synth_ltp_for_pairs,
	build_synthetic_quotes,
)  # phase 2 helpers
from .settings import Settings, load_settings  # phase 3 settings

__all__ = [
	"resolve_expiry_rule",
	"generate_synthetic_instruments",
	"synth_ltp_for_pairs",
	"build_synthetic_quotes",
	"Settings",
	"load_settings",
]
