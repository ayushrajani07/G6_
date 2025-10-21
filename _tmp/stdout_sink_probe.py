import io
from src.utils.output import OutputRouter, StdoutSink
buf = io.StringIO()
sink = StdoutSink(stream=buf)
r = OutputRouter([sink])
r.success('good', data={'ok': True})
print(buf.getvalue())
