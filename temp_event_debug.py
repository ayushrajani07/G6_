import os,time,threading
os.environ['G6_SSE_HTTP']='1'
from scripts.summary.plugins.sse import SSEPublisher
from scripts.summary.unified_loop import UnifiedLoop
pub=SSEPublisher(diff=True)
loop=UnifiedLoop([pub],panels_dir='data/panels',refresh=0.1)
threading.Thread(target=lambda: loop.run(cycles=3),daemon=True).start()
for i in range(10):
    time.sleep(0.2)
    print('t',i,'events',len(pub.events))
print('final events sample', pub.events[:2])
