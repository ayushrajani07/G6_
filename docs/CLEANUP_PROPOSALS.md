# Cleanup proposals (focused, post-panels)

This note lists duplicate/legacy code and safe removal candidates, plus consolidations.

## High-confidence consolidations (Status: summary_view slimming DONE)

- scripts/summary_view.py
  - Slimmed: duplicate derive helpers removed; now imports from `scripts.summary.derive`.
  - Retained legacy wrappers (`plain_fallback`, `indices_panel`, etc.) for backward compatibility tests.
  - Remaining follow-up (optional): move `StatusCache` to a shared utility if reused elsewhere.

- scripts/panels_simulator.py
  - Not present in repo (2025-10-01 audit) — no action required.

- Output helpers duplication
  - Legacy duplication resolved (external bridge retired). Focus on consolidating any residual publisher helpers under `scripts/summary/` modules.

## Safe-to-delete candidates (after verification)

- scripts/run_mock_dashboard.py & scripts/mock_run_once.py
  - Not found in repo (2025-10-01 audit); proposal entries retained only for historical context.

- scripts/summary/legacy blocks in summary_view.py
  - Any duplicated panel renderers; replace with scripts.summary.panels.* imports.

Please validate search usages before deletion:
- Use “Find All References” on each function to ensure no external caller remains.
- Run “pytest -q” after removals.

## Next steps

1. Diff scripts/summary_view.py against scripts/summary/* to identify dead helpers.
2. Remove duplicates; keep only the delegation to scripts.summary.app.run().
3. Convert any remaining one-off panels to modular components under panels/*.
4. Update docs where examples reference old scripts.

## Appendix: panels data sources

- Preferred path: data/panels/*.json via PanelFileSink or status bridge.
- Fallback: data/runtime_status.json when panels mode is off.
- Source indicator: Header shows “Source: Panels” or “Source: Status”.
