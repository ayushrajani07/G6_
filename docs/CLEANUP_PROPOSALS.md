# Cleanup proposals (focused, post-panels)

This note lists duplicate/legacy code and safe removal candidates, plus consolidations.

## High-confidence consolidations

- scripts/summary_view.py
  - Retains many legacy helpers now implemented under scripts/summary/*.
  - Keep the thin runner (delegating to scripts.summary.app) but migrate/centralize helpers:
    - Move any remaining formatters/derive functions into scripts/summary/derive.py
    - Ensure panels read only via scripts/summary/panels/*
  - Action: Identify unused functions and remove; keep StatusCache, plain_fallback only if still referenced.

- scripts/panels_simulator.py
  - Superseded by scripts/status_to_panels.py for driving panel JSON from status; retain if needed for demo-only.
  - Action: Mark as demo-only or remove after confirming bridge covers scenarios.

- Output helpers duplication
  - src/summary/publisher.py + scripts/status_to_panels.py both publish panels. This is intentional (in-process vs out-of-process), but shared safety is now in src/summary/resilience.py.
  - Action: Keep both, but avoid re-implementing guards elsewhere; use resilience helpers.

## Safe-to-delete candidates (after verification)

- scripts/run_mock_dashboard.py
  - If summary_view replaces this for terminal use, and dashboards are handled elsewhere, mark deprecated.

- scripts/mock_run_once.py
  - If no longer used by tests or workflows, remove in favor of dev_tools run-once.

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
