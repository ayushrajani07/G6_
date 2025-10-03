# Configuration Model (Baseline Draft)

> Status: Draft (Phase 1). Documents current observed patterns and establishes a target consolidation model.

## 1. Sources of Configuration

Current active sources (implicit precedence as implemented across code):
1. Hard-coded inline defaults (scattered: orchestrator, metrics, summary renderer)
2. Environment variables (prefix `G6_` – large surface; authoritative docs: `env_dict.md`)
3. JSON config file `_config.json` (in `config/` directory) – selectively loaded, not authoritative
4. CLI arguments (primarily in `scripts/run_orchestrator_loop.py` and some dev utilities)
5. Test fixtures overriding env for deterministic behavior

Planned explicit precedence (highest wins):
CLI args > Environment Variables > Config File > Built-in Defaults

## 2. Problems / Gaps
- Env reads are ad-hoc and duplicated
- No central schema or validation (typos silently create new flags)
- Mixed naming conventions and lifecycles (deprecated vs active vs experimental)
- Some compound feature flags govern multiple behaviors (hidden coupling)
- Difficulty diffing runtime effective configuration for support/debug

## 3. Target Central Config Object
A single assembly function executed once during bootstrap:
```
load_defaults() -> apply_config_file() -> apply_env() -> apply_cli() -> validate() -> freeze()
```
Output: immutable `Config` dataclass (or `pydantic` model if dependency allowed) injected into `RuntimeContext`.

### 3.1 Example Shape (Illustrative)
```python
@dataclass(frozen=True)
class Config:
    loop_interval_s: float
    metrics_port: int | None
    enable_metrics: bool
    adaptive: AdaptiveConfig
    summary: SummaryConfig
    storage: StorageConfig
    features: FeatureFlags
```
Sub-sections would cluster existing flags into semantic groups.

## 4. Classification of Flags (Initial Taxonomy)
| Class | Examples (prefix) | Purpose | Lifecycle Policy |
|-------|-------------------|---------|------------------|
| Adaptive Tuning | G6_ADAPTIVE_* | Alert/severity behavior | Needs grouping + validation |
| Summary / UI | G6_SUMMARY_*, G6_PANELS_* | Presentation & rendering | Move to declarative layout config |
| Metrics | G6_METRICS_* | Observability endpoints & verbosity | Consolidate; single enable + structured options |
| Storage / Export | G6_STORAGE_*, G6_BENCHMARK_* | Persistence & snapshots | Introduce exporter registry |
| Debug / Introspection | G6_REFACTOR_DEBUG, G6_LATENCY_PROFILING | Developer diagnostics | Add explicit DEBUG group |
| Compatibility / Legacy | G6_ALLOW_LEGACY_*, G6_SUMMARY_LEGACY | Transitional gating | Add sunset metadata |
| Experimental / Wildcard | suffix '_' patterns (e.g., G6_BENCHMARK_) | Namespacing for sub-flags | Replace with structured composite config |

## 5. Validation Strategy
- Type coercion (int, float, bool, lists) at assembly boundary
- Ranged constraints (e.g., non-negative intervals, percentage 0-1 bounds)
- Mutual exclusivity (legacy vs new pipeline flags)
- Deprecation warnings: log once with suggested replacement
- Stale detection: if documented but unused -> mark for removal (inventory script feeds list)

## 6. Implementation Phases
1. Passive wrapper: introduce `config/loader.py` that centralizes existing reads (no behavior change)
2. Replace scattered `os.getenv` calls with `config.get("NAME")`
3. Introduce grouped dataclasses + validation harness
4. Emit `data/active_config.json` snapshot each run (for support & diff)
5. Enforce allowlist: raise on unknown `G6_` env vars (after stabilization)

## 7. Tooling & Automation
- Extend `scripts/gen_env_inventory.py` to emit JSON for CI diff -> detect new undocumented flags
- Add governance test to assert zero undocumented (with suppression window)
- Optional: script to compare two runtime snapshots -> highlight changes

## 8. Migration Considerations
| Risk | Mitigation |
|------|-----------|
| Hidden dependency on implicit defaults | Log full resolved config early |
| Unexpected type coercion changes | Dual read period with warning logs |
| Deprecation churn | Provide mapping table + removal schedule |

## 9. Immediate Actions (Phase 1 Scope)
- Create loader scaffold file (TBD) – no code changes yet in this draft
- Enumerate groups & map existing flags (derive from `env_dict.md` + auto inventory)
- Tag obviously stale / duplicate toggles for removal candidate list

---
Draft will evolve as config consolidation implementation begins.
