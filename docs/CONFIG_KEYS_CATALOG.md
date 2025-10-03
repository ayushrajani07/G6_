# G6 Configuration Keys Catalog

Generated: 2025-10-02T08:29:05.181714Z
Source file: config/_config.json (do not edit generated catalog manually).

Key | Type | Default | Section
--- | --- | --- | ---
index_params.BANKNIFTY.exchange | str | NSE | index_params
index_params.BANKNIFTY.expiry_rules | list | ["this_month","next_month"] | index_params
index_params.BANKNIFTY.offsets | list | [0,1,-1,2,-2] | index_params
index_params.BANKNIFTY.segment | str | NFO-OPT | index_params
index_params.BANKNIFTY.strike_step | int | 100 | index_params
index_params.FINNIFTY.exchange | str | NSE | index_params
index_params.FINNIFTY.expiry_rules | list | ["this_month","next_month"] | index_params
index_params.FINNIFTY.offsets | list | [0,1,-1,2,-2] | index_params
index_params.FINNIFTY.segment | str | NFO-OPT | index_params
index_params.FINNIFTY.strike_step | int | 50 | index_params
index_params.NIFTY.exchange | str | NSE | index_params
index_params.NIFTY.expiry_rules | list | ["this_week","next_week","this_month","next_month"] | index_params
index_params.NIFTY.offsets | list | [0,1,-1,2,-2] | index_params
index_params.NIFTY.segment | str | NFO-OPT | index_params
index_params.NIFTY.strike_step | int | 50 | index_params
index_params.SENSEX.exchange | str | BSE | index_params
index_params.SENSEX.expiry_rules | list | ["this_week","next_week","this_month","next_month"] | index_params
index_params.SENSEX.offsets | list | [0,1,-1,2,-2] | index_params
index_params.SENSEX.segment | str | BFO-OPT | index_params
index_params.SENSEX.strike_step | int | 100 | index_params
kite.default_exchanges | list | ["NSE","NFO","BSE","BFO"] | kite
kite.http_timeout | int | 10 | kite
kite.instrument_cache_path | str | .cache/kite_instruments.json | kite
kite.instrument_ttl_hours | int | 6 | kite
kite.max_retries | int | 5 | kite
kite.rate_limit_per_sec | float | 5.0 | kite
orchestration.log_level | str | INFO | orchestration
orchestration.market_end_time | str | 15:30 | orchestration
orchestration.market_start_time | str | 09:15 | orchestration
orchestration.prometheus_port | int | 9108 | orchestration
orchestration.redis_enabled | bool | False | orchestration
orchestration.redis_host | str | localhost | orchestration
orchestration.redis_port | int | 6379 | orchestration
orchestration.run_interval_sec | int | 60 | orchestration
orchestration.run_offset_sec | int | 0 | orchestration
storage.csv_dir | str | data/csv | storage
storage.influx_bucket | str | your-bucket | storage
storage.influx_enabled | bool | False | storage
storage.influx_org | str | your-org | storage
storage.influx_url | str | http://localhost:8086 | storage
