import pytest

pytest.skip(
    "Tombstone: synthetic fallback unit tests removed with feature deprecation (2025-10-08). "
    "Delete file after 2025-12-01 if no replacement tests introduced.",
    allow_module_level=True,
)

class TraceRecorder:
    def __init__(self):
        self.events = []
    def __call__(self, event, **fields):  # retain class for any historical introspection
        self.events.append((event, fields))
