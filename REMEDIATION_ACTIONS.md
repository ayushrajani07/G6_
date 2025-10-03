# G6 Remediation & Recovery Playbook

Purpose: Fast, actionable steps to diagnose and recover from NO_DATA, PARTIAL coverage, or performance regressions in the unified collectors + provider pipeline.

---
## 1. Quick Classification Matrix
| Symptom | Likely Root | First Action | Escalate If |
|---------|-------------|--------------|-------------|
| NO_DATA for all indices | Provider auth fail or instrument universe empty | Check logs for `auth failed` / run health probe | After token refresh still empty |
| NO_DATA single index | Expiry mismatch or strict underlying rejection | Enable TRACE (`G6_TRACE_COLLECTOR=1`) inspect `instrument_filter_summary` | Reject counts dominated by expiry_mismatch for >2 cycles |
| PARTIAL (few strikes) | Strike ladder mis-sized or ATM drift | Compare requested vs matched in `instrument_filter_strike_diag` | Missing >50% strikes for 5 cycles |
| Sudden contamination (other index symbols) | Prefilter disabled or symbol root parsing drift | Ensure `G6_DISABLE_PREFILTER` not set; verify root detection | Contamination persists with prefilter on |
| High expiry_mismatch only | Expiry service stale or holiday shift | Dump expiry list (`EXPIRIES idx=...`) check target | Candidate list missing expected weekly |
| High strike_mismatch only | Step mismatch or scale factor misapplied | Confirm `index_registry` step vs strikes emitted | Step logged differs from registry |
| Performance slowdown | Repeated by-exp looping | Verify fallback logs not spamming; ensure P0 patch deployed | CPU > 2x baseline with same config |

---
## 2. Environment Flag Tuning (Fast Toggles)
| Flag | Default | Use Case | Impact |
|------|---------|----------|--------|
| `G6_LEAN_MODE` | off | Reduce overhead during investigation | Skips greeks & heavy enrich paths |
| `G6_TRACE_COLLECTOR` | off | Deep instrument filtering diagnostics | High log volume (enable briefly) |
| `G6_TRACE_OPTION_MATCH` | off | Pre-index & acceptance sampling | Adds sample warnings per expiry |
| `G6_DISABLE_PREFILTER` | off | Temporarily bypass raw prefilter | Increases candidate noise (avoid prolonged) |
| `G6_ENABLE_NEAREST_EXPIRY_FALLBACK` | on | Forward expiry recovery | Turn off to isolate mismatch root |
| `G6_ENABLE_BACKWARD_EXPIRY_FALLBACK` | on | Backward (<=3d) recovery | Off to confirm true expiry absence |
| `G6_FORCE_MARKET_OPEN` | off | Collect outside hours | For offline testing |
| `G6_INSTRUMENT_CACHE_TTL` | adaptive | Control refresh cadence | Lower to 30–60s for debugging |

---
## 3. Triage Flow (5 Minute Loop)
1. Run one debug cycle:
   ```powershell
   $env:G6_LEAN_MODE='1'; $env:G6_TRACE_COLLECTOR='1'; python scripts/run_debug_cycle.py
   ```
2. Capture key TRACE lines:
   - `instrument_prefilter`
   - `instrument_filter_summary`
   - `instrument_filter_expiry_diag`
   - `instrument_filter_strike_diag`
3. Classify dominant rejection bucket.
4. Apply targeted remedy (section 4) and re-run with TRACE off (to measure steady state).
5. If unresolved after 2 iterations escalate to deeper inspection (section 5).

---
## 4. Targeted Remedies by Dominant Rejection Type
### expiry_mismatch Dominant
Actions:
- Inspect `EXPIRIES` log for index. Ensure weekly cadence correct (Tue FINNIFTY, Thu NIFTY/BANKNIFTY, Fri SENSEX).
- If missing: invalidate cache: delete `_expiry_dates_cache` via restart or bump process.
- Temporarily disable forward fallback to see raw mismatch clarity:
  ```powershell
  $env:G6_ENABLE_NEAREST_EXPIRY_FALLBACK='0'
  ```
- If holiday shift suspected: confirm real exchange calendar; manually set override by injecting earliest valid future expiry via config (future enhancement: manual override hook).

### strike_mismatch Dominant
Actions:
- Compare requested vs matched sample lists (`missing_sample`).
- Verify registry step: run `python -c "from src.utils.index_registry import get_index_meta;print(get_index_meta('NIFTY'))"`.
- If ATM mis-rounded: ensure all code paths use `atm_round` (search for manual `round(lp/50)` patterns; replace).
- If adaptive scaling used: confirm `G6_ADAPTIVE_SCALE_PASSTHROUGH=1` actually sets expected scale in logs.

### root_mismatch / underlying_mismatch Dominant
Actions:
- Ensure prefilter ON (unset `G6_DISABLE_PREFILTER`).
- Look at contamination samples; validate they truly belong to other indices (e.g., BANKNIFTY symbols in NIFTY run).
- If legit symbols rejected: check `symbol_matches_index` mode; try relaxed test:
  ```powershell
  $env:G6_SYMBOL_MATCH_MODE='lenient'
  ```
- If still failing, log raw `tradingsymbol` and run root detector manually for one sample.

### No Instruments Accepted (Zero Data Sentinel Triggered)
Actions:
- Confirm not an auth issue: run provider health check (add a small script calling `KiteProvider.get_ltp`).
- Validate strikes request list length > 0 (check collectors log for strikes=...).
- Toggle off underlying strict temporarily:
  ```powershell
  $env:G6_SYMBOL_MATCH_UNDERLYING_STRICT='0'
  ```
- If fallback expiries also empty, re-check instrument universe size with a diagnostic snippet iterating provider `get_instruments` count.

### Performance Regression (High CPU / Latency)
Actions:
- Ensure updated fallback optimization deployed (search for `by_exp_meta` in provider file).
- If fallbacks still firing every cycle, confirm actual target expiry exists—excessive fallback implies upstream expiry selection drift.
- Temporarily disable both fallback flags to quantify baseline speed.

---
## 5. Deep Inspection (When Quick Remedies Fail)
| Aspect | Probe | Interpretation |
|--------|-------|----------------|
| Root parsing | Manually run symbol_root functions on sample ts | Divergence => update parser heuristics |
| Expiry service | Dump list length per index over time | Shrinking list mid-session suggests cache invalidation bug |
| Strike generation | Log raw atm, offsets, final list length | Unexpected shrink => scaling or step retrieval issue |
| Option universe size | Count CE/PE for index prefix | Very low (<20) => provider returning truncated data |

---
## 6. Prevent Recurrence (Hardening Measures)
- Add automated periodic fast-path expiry refresh (every N cycles) if list length < threshold.
- Emit metric: `g6_option_filter_reject_ratio{reason=...}` to surface spikes.
- Introduce health gate: abort greeks phase if PARTIAL > 70% for 3 consecutive cycles.
- Cache symbol root parsing results across indices (already localized per cycle; promote to provider-level optional LRU if CPU hotspots reappear).

---
## 7. Minimal Commands Cheat-Sheet (PowerShell)
```powershell
# Full TRACE one-off
$env:G6_TRACE_COLLECTOR='1'; $env:G6_TRACE_OPTION_MATCH='1'; python scripts/run_debug_cycle.py

# Lean quick check (no TRACE)
$env:G6_LEAN_MODE='1'; python scripts/run_debug_cycle.py

# Force market open outside hours
$env:G6_FORCE_MARKET_OPEN='1'; python scripts/run_debug_cycle.py

# Disable fallbacks to isolate raw mismatch
$env:G6_ENABLE_NEAREST_EXPIRY_FALLBACK='0'; $env:G6_ENABLE_BACKWARD_EXPIRY_FALLBACK='0'; python scripts/run_debug_cycle.py

# Relax symbol matching selectively
$env:G6_SYMBOL_MATCH_MODE='lenient'; python scripts/run_debug_cycle.py
```

---
## 8. Escalation Checklist
Before escalating:
- Attach last 2 cycle TRACE summaries (`instrument_filter_summary`).
- Provide counts: accepted, expiry_mismatch, strike_mismatch, root_mismatch.
- Include current env flags set (sanitized). 
- Confirm whether ATM rounding changed recently.

---
## 9. Future Enhancements (Backlog Candidates)
- Dedicated `g6_filter_rejects_total` Prometheus counter per reason.
- Configurable manual expiry override list (YAML) for holiday weeks.
- Strike ladder auto-densification when PARTIAL coverage detected.
- Structured JSON emission of fallback choice events for audit.

---
## 10. Quick Reference Summary
| Scenario | Primary Lever | Secondary |
|----------|---------------|-----------|
| Missing weekly expiry | Expiry cache invalidate | Disable forward fallback to verify |
| Few strikes accepted | Verify step via registry | Check adaptive scale factor |
| Contamination | Prefilter ON | Match mode lenient test |
| Slow cycle | Confirm fallback not looping | Disable fallbacks to profile |
| Zero data sentinel | Auth, expiry, strikes ordering | Underlying strict toggle |

---
Stay concise: Always turn TRACE flags back OFF after resolution to restore performance and log hygiene.
