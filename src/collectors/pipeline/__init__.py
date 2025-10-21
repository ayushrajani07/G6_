"""Pipeline package exports.

Expose pipeline entrypoints required by tests without forcing them to
import the legacy monolithic module path. Tests reference
`from src.collectors.pipeline import build_default_pipeline, ExpiryWorkItem`.
The factory + dataclass currently live in the flat module
`src.collectors.pipeline` (transitional location). Re-export here for a
stable package-style import path.
"""
from src.collectors.pipeline_root import (
	CollectorPipeline,
	EnrichedExpiry,
	ExpiryWorkItem,
	PersistOutcome,
	build_default_pipeline,
)

__all__ = [
	'build_default_pipeline',
	'ExpiryWorkItem',
	'EnrichedExpiry',
	'PersistOutcome',
	'CollectorPipeline',
]
