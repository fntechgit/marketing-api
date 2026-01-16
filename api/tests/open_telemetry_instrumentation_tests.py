import os
import random
import string

from django.urls import reverse
from rest_framework.test import APITestCase

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.propagate import extract
from opentelemetry.baggage import get_baggage


class InMemorySpanExporter(SpanExporter):
    """InMemorySpanExporter to validate the instrumentation since we cant pull it from the console"""
    def __init__(self):
        super().__init__()
        self._finished_spans = []

    def export(self, spans):
        self._finished_spans.extend(spans)
        return SpanExportResult.SUCCESS

    def shutdown(self):
        self._finished_spans.clear()

    def clear(self):
        self._finished_spans.clear()

    def get_finished_spans(self):
        return list(self._finished_spans)


class DjangoCarrier:
    """Wrap Django headers to behave like a carrier for `extract`."""

    def __init__(self, headers):
        self.headers = headers

    def get(self, key, default=None):
        key = key.lower()
        for k, v in self.headers.items():
            if k.lower().replace("_", "-").endswith(key):
                return v
        return default


# Global provider setup
memory_exporter = InMemorySpanExporter()
provider = TracerProvider()
provider.add_span_processor(SimpleSpanProcessor(memory_exporter))
trace.set_tracer_provider(provider)
tracer = trace.get_tracer(__name__)


class OpenTelemetryInstrumentationTest(APITestCase):
    def randomString(self, str_len):
        letters = string.ascii_letters
        return ''.join(random.choice(letters) for i in range(str_len))

    def setUp(self):
        memory_exporter.clear()
        self.access_token = os.environ.get('ACCESS_TOKEN', 'TEST')
        self.url = reverse('config-values-read:index')

    def test_cf_ray_header(self):
        """Inject only CF-RAY header → new trace is started, cf.ray_id attribute set."""
        response = self.client.get(
            f"{self.url}", **{"HTTP_CF_RAY": "abc123"}
        )
        self.assertEqual(response.status_code, 200)

        carrier = DjangoCarrier(response.wsgi_request.META)
        ctx = extract(carrier)
        span = trace.get_current_span(ctx)
        span_ctx = span.get_span_context()

        # No parent span because no traceparent → new trace created
        self.assertEqual(span_ctx.is_valid, False)

        # Exported spans should exist
        spans = memory_exporter.get_finished_spans()
        self.assertEqual(spans[0].resource.attributes.get('service.name'), 'marketing-api')
        self.assertEqual(len(spans), 6)
        exported_span = spans[5]
        # Since no traceparent was injected, parent should be INVALID
        self.assertEqual(exported_span.parent, None)
        # Our CF-RAY header should be recorded in span attributes
        self.assertEqual(exported_span.attributes.get("cf.ray_id"), "abc123")

    def test_traceparent_and_baggage(self):
        """Inject TRACEPARENT + BAGGAGE headers → exported span should have parent_id set + baggage propagated."""
        trace_id = "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        parent_span_id = "bbbbbbbbbbbbbbbb"
        traceparent = f"00-{trace_id}-{parent_span_id}-01"
        baggage = "cf.ray_id=xyz"

        response = self.client.get(
            f"{self.url}",
            **{
                "HTTP_TRACEPARENT": traceparent,
                "HTTP_BAGGAGE": baggage,
            }
        )
        self.assertEqual(response.status_code, 200)
        # Extracted context should match
        carrier = DjangoCarrier(response.wsgi_request.META)
        ctx = extract(carrier)
        span = trace.get_current_span(ctx)
        span_ctx = span.get_span_context()
        self.assertTrue(span_ctx.is_valid)

        # Verify a span was exported
        spans = memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 6)
        self.assertEqual(spans[0].resource.attributes.get('service.name'), 'marketing-api')
        exported_span = spans[5]
        # Check that the trace_id is the same as the injected traceparent
        self.assertEqual(format(exported_span.context.trace_id, "032x"), trace_id)

        # Check that the parent_id is the injected span_id
        self.assertEqual(format(exported_span.parent.span_id, "016x"), parent_span_id)

        # Baggage value should have propagated
        baggage_value = get_baggage("cf.ray_id", context=ctx)
        self.assertEqual(baggage_value, "xyz")
        # And should also show up in span attributes (if your request_hook adds it)
        self.assertEqual(exported_span.attributes.get("baggage.cf.ray_id"), "xyz")

    def test_mysql_span_has_db_name(self):
        """Simulate a MySQL query and assert db.name attribute is added."""
        with tracer.start_as_current_span("mysql-test") as span:
            span.set_attribute("db.name", "test_db")
            span.set_attribute("db.statement", "SELECT 1")

        spans = memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        exported = spans[0]
        self.assertEqual(exported.resource.attributes.get('service.name'), 'marketing-api')
        self.assertEqual(exported.attributes.get("db.name"), "test_db")
        self.assertIn("SELECT", exported.attributes.get("db.statement"))

    def test_redis_span_has_key(self):
        """Simulate a Redis command and assert db.redis.key is added."""
        with tracer.start_as_current_span("redis-test") as span:
            span.set_attribute("db.redis.command", "GET")
            span.set_attribute("db.redis.key", "my_key")

        spans = memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        exported = spans[0]
        self.assertEqual(exported.resource.attributes.get('service.name'), 'marketing-api')
        self.assertEqual(exported.attributes.get("db.redis.command"), "GET")
        self.assertEqual(exported.attributes.get("db.redis.key"), "my_key")

    def test_requests_span_has_custom_header(self):
        """Simulate a requests span and assert custom header is captured."""
        with tracer.start_as_current_span("requests-test") as span:
            span.set_attribute("http.custom_header", "abc123")
            span.set_attribute("http.response_length", 42)

        spans = memory_exporter.get_finished_spans()
        self.assertEqual(len(spans), 1)
        exported = spans[0]
        self.assertEqual(exported.resource.attributes.get('service.name'), 'marketing-api')
        self.assertEqual(exported.attributes.get("http.custom_header"), "abc123")
        self.assertEqual(exported.attributes.get("http.response_length"), 42)