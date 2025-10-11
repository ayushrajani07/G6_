# Grafana provisioning & governance checklist

Generated dashboards live in `grafana/dashboards/generated/`, tracked by `manifest.json`.
Provisioning file: `grafana/provisioning/dashboards/dashboards.yml` (file provider with folder `G6`).
Before pushing changes:
  - Run `python scripts/gen_dashboards_modular.py --verify`.
  - If it fails, regenerate and commit updated dashboards and `manifest.json`.
  - If available, run `python scripts/gen_recording_rules.py --check` and commit `prometheus_recording_rules_generated.yml` if drift detected.
In Grafana, ensure the provisioning path resolves correctly (use repo root as working directory or make the path absolute).