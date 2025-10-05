# Features & UI Enhancements History

_Archived on 2025-10-05 (source one-off enhancement docs migrated to this consolidated history)._

This document aggregates prior ad-hoc enhancement markdown files (footer layout, footer integration variant, alerts panel expansion) into a single maintained history. Original detailed narrative files have been moved under `archive/2025-10-05/`.

## 2025-10-05 Footer Integration Enhancement
**Goal:** Integrate uptime & collections footer inside panel table body for cohesive visual layout.

**Before:** Footer rendered after panel border (detached) or as separate grouped component.
**After:** Footer appears as dim-styled bottom table rows with a blank spacer row.

**Benefits:**
- Better visual cohesion (footer inside border)
- Reduced vertical fragmentation
- Consistent spacing & styling across panels

_Key Implementation Notes:_ Removed `Group(tbl, footer)` construct; appended rows directly (`tbl.add_row(...)`).

## 2025-10-05 Footer Screenshot Match Variant
**Goal:** Achieve pixel / layout parity with design screenshot specifying footer outside table but inside panel border.

**Approach:** Restored separate footer component via `Group(tbl, footer_content)` with left-aligned dim text.

**Result:** Provided alternate layout baseline; informs trade-offs (integration vs authenticity). Unified direction now prefers integrated rows (see Integration Enhancement) for density and consistency.

## 2025-10-05 Alerts Panel Full-Length Expansion
**Changes:**
- Normal rows: 5 -> 15; Compact rows: 2 -> 4
- Rolling log capacity: 50 -> 100
- Persistent storage: 200 -> 500
- Centralized alerts fetched: 20 -> 50

**Benefits:**
- 3x alert visibility in normal mode
- Richer debugging context (longer trail)
- Improved screen real estate utilization

**Implementation Snippet:**
```
max_rows = 4 if compact else 15
_get_rolling_alerts_log(max_entries=100)
_add_to_rolling_alerts_log(..., max_entries=500)
centralized_alerts = handler.get_errors_for_alerts_panel(count=50)
```

## Design Considerations
| Aspect | Integrated Footer | Screenshot Match Footer |
|--------|-------------------|-------------------------|
| Visual Cohesion | High | Medium |
| Authenticity to Reference | Medium | High |
| Vertical Space Efficiency | High | Medium |
| Implementation Complexity | Low | Low |
| Future Extensibility | High | Medium |

Decision: Prefer integrated footer rows for default dashboard mode; maintain awareness of alternative layout for future theming/toggle.

## Maintenance Notes
- All prior enhancement markdown artifacts archived (see archive path) to reduce docs clutter.
- Future UI tweaks should update this file rather than creating new one-off top-level docs.
- Consider adding screenshots (future) via a lightweight capture script to visually diff layout changes.

---
_Last updated: 2025-10-05_
