import importlib, traceback
mods=[
 ('providers_interface','src.collectors.providers_interface'),
 ('composite_provider','src.providers.composite_provider'),
 ('factory','src.providers.factory'),
 ('csv_sink','src.storage.csv_sink'),
 ('health_monitor','src.health.monitor'),
 ('resilience','src.utils.resilience'),
 ('circuit_breaker','src.utils.circuit_breaker'),
 ('retry','src.utils.retry'),
 ('circuit_registry','src.utils.circuit_registry'),
]
for name,path in mods:
    try:
        m=importlib.import_module(path)
        print('OK',name,getattr(m,'__file__','?'))
    except Exception as e:
        print('FAIL',name,type(e).__name__,e)
        traceback.print_exc(limit=2)
