# Egress Freeze (G6_EGRESS_FROZEN)

The platform supports an environment-controlled "egress freeze" that disables
all non-Prometheus outward panel / diff style emission surfaces so core
metrics + Grafana iteration can proceed with a reduced surface area.

## What Is Frozen

When `G6_EGRESS_FROZEN=1` (or any truthy value: 1, true, yes, on):

- Panel Diff Emitter (`src/orchestrator/panel_diffs.py`) becomes a no-op.
  * No `.diff.json` or periodic `.full.json` artifacts are written.
  * Associated panel diff Prometheus metrics are **not registered**:
    - `g6_panel_diff_writes_total`
    - `g6_panel_diff_truncated_total`
    - `g6_panel_diff_bytes_total`
    - `g6_panel_diff_bytes_last`
- Legacy panels bridge script `scripts/status_to_panels.py` is replaced by a
  tombstone stub that exits immediately (0) and performs no work.
- Tests that specifically assert panel diff metric presence or diff behavior
  are skipped (using `@pytest.mark.skipif(G6_EGRESS_FROZEN)` safeguards).

Prometheus metrics unrelated to panel diffs continue to function normally.

## What Is NOT Frozen

- Core collection cycle metrics and all governed spec metrics.
- Grafana / Prometheus pipeline, including recording rules and alerts.
- Unified summary application (`python -m scripts.summary.app`).
- SSE / event bus scaffolding (these remain inert unless explicitly enabled by
  their own configuration flags; the freeze does not remove internal buses).
 - Dashboard generation (`scripts/gen_dashboards_modular.py`) – you can still regenerate and verify Grafana dashboards; freeze only suppresses legacy diff/full panel artifact emission and associated metrics.

## Rationale

Freezing de-emphasized egress mechanisms reduces:

- Cognitive overhead while iterating on core metrics and dashboards.
- Noise from artifact-oriented file writes and their governance metrics.
- Risk of partial / stale diff consumers influencing design discussions.

It also makes it immediately visible (via absence of panel diff metrics) that
those pathways are intentionally dormant.

## Reactivating Frozen Egress

Unset or set `G6_EGRESS_FROZEN=0` (or remove the variable) and restart the
process. On next startup:

- Panel diff metrics will be force-rebound early with canonical label sets.
- Setting `G6_PANEL_DIFFS=1` will resume diff/full artifact emission.
- Tests (when run without the freeze flag) will again validate diff behaviors.

## Related Environment Flags

| Variable | Purpose |
|----------|---------|
| `G6_EGRESS_FROZEN` | Master kill-switch for non-Prometheus egress features. |
| `G6_PANEL_DIFFS` | Enables the panel diff emitter when not frozen. |
| `G6_SUPPRESS_LEGACY_CLI` | Suppresses tombstone message from legacy scripts. |
| `G6_ENABLE_METRIC_GROUPS` / `G6_DISABLE_METRIC_GROUPS` | Existing group filters (still honored for remaining groups). |

## Tombstoned Legacy Bridge

The previous `status_to_panels.py` implementation is removed. The stub only
prints a short note (unless suppressed) and exits 0 if frozen, 2 otherwise.
Refer to `DEPRECATIONS.md` for broader migration context.

## Testing Strategy

CI / local tests can exercise both modes:

```
# Frozen mode (panel diff tests skipped)
G6_EGRESS_FROZEN=1 pytest -q

# Active mode (panel diff tests run)
pytest -q
```

Skips are explicit so any accidental reintroduction of panel diff assertions
in frozen contexts will not produce confusing failures.

## Future Clean Removal Considerations

If the panel diff pathway remains unused long-term, a subsequent phase can:

- Remove the emitter module and associated tests entirely.
- Delete panel diff dashboards / recording rule hints.
- Drop the gating logic and this documentation in favor of a concise CHANGELOG entry.

Until then, the freeze provides a reversible, low-risk isolation boundary.
