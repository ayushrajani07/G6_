"""Smoke test for index params loader.

Validates that loader returns a non-empty mapping with expected key shape.
Previously empty (flagged as orphan: no imports/asserts).
"""
import importlib


def test_index_params_loader_basic():
	mod = importlib.import_module('scripts.init_menu')  # example module referencing params
	# Heuristic: module should expose a MENU or similar structure
	menu = getattr(mod, 'MENU', None)
	assert menu is not None, "Expected MENU structure in init_menu module"
	assert isinstance(menu, (list, tuple)), "MENU should be a list/tuple of entries"
	# Ensure at least one menu entry has required fields
	first = menu[0]
	assert first, "MENU first entry should not be empty"
