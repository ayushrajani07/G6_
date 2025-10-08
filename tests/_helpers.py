import os

def fast_mode() -> bool:
    """Return True when fast-mode test reductions should apply.

    Controlled by env var G6_FAST (default '1'). Set G6_FAST=0 to disable
    cycle/time reductions for full / nightly or CI thorough runs.
    """
    return os.getenv('G6_FAST', '1') not in ('0', 'false', 'False')
