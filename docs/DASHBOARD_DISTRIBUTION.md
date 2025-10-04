# Dashboard Distribution Bundle

The packaging script `scripts/package_dashboards.py` creates a versioned, integrity-verifiable archive of all production Grafana dashboards.

## Outputs
Run:
```
python scripts/package_dashboards.py --version 1.0.0 --out dist
```
Produces in `dist/`:
- `dashboards_1.0.0.tar.gz` – Compressed archive containing each JSON under `grafana/dashboards/`
- `dashboards_1.0.0.tar.gz.sha256` – SHA-256 checksum file
- `dashboards_manifest_1.0.0.json` – Machine-readable manifest (paths, per-file hashes, sizes)

## Version Resolution
Order of precedence:
1. `--version` CLI
2. `G6_DASHBOARD_VERSION` environment variable
3. `git describe --tags --always`
4. Fallback: `dev`

## Integrity Verification
On recipient side:
```
sha256sum -c dashboards_1.0.0.tar.gz.sha256
# or (macOS)
shasum -a 256 -c dashboards_1.0.0.tar.gz.sha256
```
To verify individual dashboard integrity:
```
cat dashboards_manifest_1.0.0.json | jq -r '.files[] | "\(.sha256)  \(.file)"' > manifest_files.sha256
sha256sum -c manifest_files.sha256
```

## CI / Release Integration
A GitHub Actions workflow can produce & attach the bundle on tag push:
```
name: Dashboards Package
on:
  push:
    tags: ['v*']
  workflow_dispatch:
jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: '3.11' }
      - run: python scripts/package_dashboards.py --out dist
      - uses: actions/upload-artifact@v4
        with:
          name: dashboards-bundle
          path: dist/
```
Extend with a release upload step (GitHub Release) when ready.

## Manifest Schema
```json
{
  "version": "1.0.0",
  "created_utc": "2025-10-03T10:15:00Z",
  "count": 12,
  "files": [
    {
      "path": "grafana/dashboards/g6_perf_latency.json",
      "file": "g6_perf_latency.json",
      "sha256": "...",
      "size_bytes": 4523,
      "uid": "g6-perf-001",
      "title": "G6 Performance Latency"
    }
  ]
}
```

## Exclusions
Files containing `placeholder` in their name are excluded automatically.
Adjust `SKIP_SUBSTRINGS` inside the script for additional filters (e.g., experimental or private dashboards).

## Best Practices
- Increment dashboard JSON `version` fields when structurally modifying panels.
- Keep UIDs stable; create new UID suffix for major redesigns.
- Regenerate bundle on each release candidate tag.
- Store manifest in release assets for audit reproducibility.

## Future Enhancements (Optional)
- Signature support (cosign / minisign) for tamper-evident distribution.
- Automatic changelog generation comparing previous manifest.
- JSON Schema for manifest validation.
- Per-dashboard semantic version embedding.
