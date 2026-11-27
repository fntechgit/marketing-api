from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# The global tracer provider can only be set once per process. Nothing else in the test suite
# sets one (DjangoTelemetry.setup('test') skips it), so every tracing test shares this exporter.
span_exporter = InMemorySpanExporter()
_provider = TracerProvider()
_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
trace.set_tracer_provider(_provider)
