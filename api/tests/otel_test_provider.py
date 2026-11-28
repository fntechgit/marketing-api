from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

# The global tracer provider can only be set once per process. Under ENV=test nothing else sets one
# (DjangoTelemetry.setup('test') skips it). With tracing on outside ENV=test, settings has already
# installed one, so the exporter is added to that provider instead. Either way every tracing test
# shares this exporter.
span_exporter = InMemorySpanExporter()
_provider = trace.get_tracer_provider()
if not isinstance(_provider, TracerProvider):
    _provider = TracerProvider()
    trace.set_tracer_provider(_provider)
_provider.add_span_processor(SimpleSpanProcessor(span_exporter))
