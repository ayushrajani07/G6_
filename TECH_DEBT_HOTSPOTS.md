# Tech Debt Hotspots Analyzer

The `scripts/coverage_hotspots.py` utility surfaces low-coverage modules ranked by a simple risk heuristic so refactoring & test authoring effort can be directed where it matters most.

## Rationale
A global coverage percentage hides concentrated risk: a handful of large, untested modules can dominate defect likelihood even if the overall average is acceptable. The hotspot analyzer pinpoints those modules by combining *uncovered line count* with a logarithmic size weighting.

```
risk_score = uncovered_lines * log(total_lines + 1)
```

This favors:
- Large files with many uncovered lines.
- Medium files with proportionally big gaps.
While not over‑penalizing very large files with modest (expected) uncovered regions.

## Quick Wins
Files flagged `QuickWin=Y` in the table satisfy:
- coverage_pct < `--quick-win-threshold` (default 65%) AND
- total lines <= `--quick-win-max-lines` (default 220).

These are typically small/medium modules where adding a handful of tests produces an outsized improvement in both local risk and global coverage.

## Usage
Generate XML (if not already produced by your workflow):
```bash
coverage xml  # or: pytest --cov=src --cov-report=xml
```
Run analyzer:
```bash
python scripts/coverage_hotspots.py --xml coverage.xml --prefix src/ --top 25
```
JSON output for tooling / dashboards:
```bash
python scripts/coverage_hotspots.py --json > hotspots.json
```
Show per-file risk delta vs previous run:
```bash
python scripts/coverage_hotspots.py --json > prev.json
# ... add tests / refactor ...
python scripts/coverage_hotspots.py --json --baseline prev.json > new.json
```
Table with ΔRisk column:
```bash
python scripts/coverage_hotspots.py --baseline prev.json --top 15
```
Fail CI if any module < 55% (stricter than global threshold):
```bash
python scripts/coverage_hotspots.py --fail-under 55 || exit 1
```

## CLI Options
| Flag | Description | Default |
|------|-------------|---------|
| --xml | Coverage XML path | coverage.xml |
| -p / --prefix | Only include files starting with prefix | src/ |
| -e / --exclude | Regex exclusion (repeatable) | (none) |
| --top | Table rows to show | 25 |
| --sort | risk or miss | risk |
| --min-lines | Ignore very small modules (< lines) | 10 |
| --max-file-lines | Ignore huge generated modules | 5000 |
| --quick-win-threshold | Coverage % for quick win flag | 65.0 |
| --quick-win-max-lines | Max lines for quick win | 220 |
| --json | Emit JSON instead of table | off |
| --baseline | Previous hotspots JSON for risk deltas | (unset) |
| --fail-under | Exit 4 if any module below % | (unset) |

## Interpreting Output
```
Rank  File                                                     Tot  Miss   Cov%     Risk QuickWin
   1  src/example/data_loader.py                               420   260   38.1   1445.6        Y
   2  src/example/processor.py                                 800   300   62.5   2076.5
```
- `Miss` = uncovered executable lines.
- `Risk` = `Miss * log(Tot + 1)`.
- `QuickWin` = Y if below threshold & within size cap.

## Recommended Remediation Strategy
1. Triage top 5 risk items: decide refactor vs direct test addition.
2. Pick 1–2 Quick Wins per iteration (fast morale & coverage boost).
3. Track deltas over time (export JSON → build chart of risk score sum). Use `--baseline` to view per‑file ΔRisk inline while iterating locally.
4. After initial burn-down, raise global coverage threshold in `.coveragerc` by small increments (1–2%).

## Extensibility Roadmap
Future enhancements (pull requests welcome):
- Cyclomatic complexity weighting (radon) to prioritize complex uncovered code.
- Git churn weighting: multiply risk by recent commit count (e.g., last 30 days), focusing on actively changing code.
- Enhanced trend analytics beyond current `--baseline` (aggregate risk sum delta, new/removed module classification).
- HTML report generation with color coding.
- Ownership mapping (module → team) for distributed accountability.

## Integration Ideas
- Nightly CI job posts top 10 hotspots to Slack.
- Failing thresholds per package (e.g., core orchestration must remain >70%).
- Combine with mutation testing results (files with high mutation escapes & low coverage jump to top of queue).

## Caveats
- Risk heuristic is deliberately simple; do not treat absolute values as precise risk probabilities.
- Generated / vendored code should be excluded with `--exclude` patterns to avoid skew.
- Extremely large modules (>5k lines) are filtered by default (consider refactoring them first before chasing coverage).

## See Also
- `.coveragerc` for global fail-under and omit settings.
- `README.md` (Coverage Strategy section) for governance.
- `tests/test_coverage_hotspots.py` for expected parser behavior.
