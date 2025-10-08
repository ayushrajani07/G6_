import time, logging
from src.collectors.cycle_context import CycleContext

logging.basicConfig(level=logging.INFO, format='%(message)s')
ctx = CycleContext(index_params={}, providers=None, csv_sink=None, influx_sink=None, metrics=None)
for ph in ['fetch','process','emit']:
    with ctx.time_phase(ph):
        time.sleep(0.01)
ctx.emit_consolidated_log()
