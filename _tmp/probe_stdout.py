import sys, os, io
sys.path.insert(0, os.getcwd())
from src.utils.output import OutputRouter, StdoutSink
buf = io.StringIO()
sink = StdoutSink(stream=buf)
r = OutputRouter([sink])
r.success('good', data={'ok': True})
print('OUT=', repr(buf.getvalue()))
