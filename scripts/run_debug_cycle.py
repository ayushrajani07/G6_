import os
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

os.environ.setdefault('G6_LEAN_MODE','1')
os.environ.setdefault('G6_TRACE_COLLECTOR','1')
os.environ.setdefault('G6_STRIKE_CLUSTER','1')
os.environ.setdefault('G6_KITE_TIMEOUT','9')
os.environ.setdefault('G6_DEBUG_SHORT_TTL','1')

from src import debug_mode

if __name__ == '__main__':
    rc = debug_mode.main()
    print('run_debug_cycle exit code', rc)
