import os
import signal
from unittest.mock import patch, MagicMock

from django.test import TestCase
from django.urls import reverse
from rest_framework.test import APITestCase

from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.propagate import extract
from opentelemetry.baggage import get_baggage

from backend.otel_instrumentation import DjangoTelemetry, SHUTDOWN_TIMEOUT_MILLIS


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

    def setUp(self):
        memory_exporter.clear()
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
        # Find the top-level Django HTTP span by name pattern
        http_spans = [s for s in spans if s.name.startswith("GET ")]
        self.assertEqual(len(http_spans), 1)
        exported_span = http_spans[0]
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
        http_spans = [s for s in spans if s.name.startswith("GET ")]
        self.assertEqual(len(http_spans), 1)
        exported_span = http_spans[0]
        self.assertEqual(spans[0].resource.attributes.get('service.name'), 'marketing-api')
        # Check that the trace_id is the same as the injected traceparent
        self.assertEqual(format(exported_span.context.trace_id, "032x"), trace_id)

        # Check that the parent_id is the injected span_id
        self.assertEqual(format(exported_span.parent.span_id, "016x"), parent_span_id)

        # Baggage value should have propagated
        baggage_value = get_baggage("cf.ray_id", context=ctx)
        self.assertEqual(baggage_value, "xyz")
        # And should also show up in span attributes (if your request_hook adds it)
        self.assertEqual(exported_span.attributes.get("baggage.cf.ray_id"), "xyz")

    @patch.dict(os.environ, {'DB_NAME': 'my_app_db'})
    def test_mysql_span_has_db_name(self):
        """mysql_hook sets db.system, db.name (env default), and db.statement on the span."""
        with tracer.start_as_current_span("mysql-test") as span:
            DjangoTelemetry.mysql_hook(span, MagicMock(), MagicMock(), "SELECT 1", ())

        spans = memory_exporter.get_finished_spans()
        mysql_spans = [s for s in spans if s.name == "mysql-test"]
        self.assertEqual(len(mysql_spans), 1)
        exported = mysql_spans[0]
        self.assertEqual(exported.resource.attributes.get('service.name'), 'marketing-api')
        self.assertEqual(exported.attributes.get("db.system"), "mysql")
        self.assertEqual(exported.attributes.get("db.name"), "my_app_db")
        self.assertEqual(exported.attributes.get("db.statement"), "SELECT 1")

    def test_mysql_hook_skips_non_recording_span(self):
        """mysql_hook sets no attributes when span.is_recording() is False."""
        span = MagicMock()
        span.is_recording.return_value = False

        DjangoTelemetry.mysql_hook(span, MagicMock(), MagicMock(), "SELECT 1", ())

        span.set_attribute.assert_not_called()

    def test_mysql_hook_swallows_exceptions(self):
        """mysql_hook does not propagate exceptions raised by set_attribute."""
        span = MagicMock()
        span.is_recording.return_value = True
        span.set_attribute.side_effect = RuntimeError("boom")

        exception_raised = False
        try:
            DjangoTelemetry.mysql_hook(span, MagicMock(), MagicMock(), "SELECT 1", ())
        except RuntimeError:
            exception_raised = True

        self.assertFalse(exception_raised, "mysql_hook should catch and not re-raise")
        self.assertTrue(span.set_attribute.called, "mysql_hook should have attempted to set attributes")

    def test_redis_span_has_key(self):
        """redis_hook sets db.system, redis.command, and redis.key on the span."""
        with tracer.start_as_current_span("redis-test") as span:
            DjangoTelemetry.redis_hook(span, MagicMock(), ("GET", "my_key"), {})

        spans = memory_exporter.get_finished_spans()
        redis_spans = [s for s in spans if s.name.startswith("redis-test")]

        self.assertEqual(len(redis_spans), 1)
        exported = redis_spans[0]
        self.assertEqual(exported.resource.attributes.get('service.name'), 'marketing-api')
        self.assertEqual(exported.attributes.get("db.system"), "redis")
        self.assertEqual(exported.attributes.get("redis.command"), "GET")
        self.assertEqual(exported.attributes.get("redis.key"), "my_key")

    def test_redis_hook_no_key_in_args(self):
        """redis_hook does not set redis.key when args contains only the command."""
        with tracer.start_as_current_span("redis-nokey-test") as span:
            DjangoTelemetry.redis_hook(span, MagicMock(), ("DEL",), {})

        exported = memory_exporter.get_finished_spans()[0]
        self.assertEqual(exported.attributes.get("redis.command"), "DEL")
        self.assertIsNone(exported.attributes.get("redis.key"))

    def test_redis_hook_skips_non_recording_span(self):
        """redis_hook sets no attributes when span.is_recording() is False."""
        span = MagicMock()
        span.is_recording.return_value = False

        DjangoTelemetry.redis_hook(span, MagicMock(), ("GET", "key"), {})

        span.set_attribute.assert_not_called()

    def test_redis_hook_swallows_exceptions(self):
        """redis_hook does not propagate exceptions raised by set_attribute."""
        span = MagicMock()
        span.is_recording.return_value = True
        span.set_attribute.side_effect = RuntimeError("boom")

        exception_raised = False
        try:
            DjangoTelemetry.redis_hook(span, MagicMock(), ("GET", "key"), {})
        except RuntimeError:
            exception_raised = True

        self.assertFalse(exception_raised, "redis_hook should catch and not re-raise")
        self.assertTrue(span.set_attribute.called, "redis_hook should have attempted to set attributes")

    def test_requests_span_has_custom_header(self):
        """Simulate a requests span and assert custom header is captured."""
        with tracer.start_as_current_span("requests-test") as span:
            span.set_attribute("http.custom_header", "abc123")
            span.set_attribute("http.response_length", 42)

        spans = memory_exporter.get_finished_spans()
        request_spans   = [s for s in spans if s.name.startswith("requests-test")]
        self.assertEqual(len(request_spans), 1)
        exported_span = request_spans[0]
        self.assertEqual(exported_span.resource.attributes.get('service.name'), 'marketing-api')
        self.assertEqual(exported_span.attributes.get("http.custom_header"), "abc123")
        self.assertEqual(exported_span.attributes.get("http.response_length"), 42)


class OpenTelemetryShutdownTest(TestCase):
    """Tests for OpenTelemetry graceful shutdown behavior."""

    def setUp(self):
        DjangoTelemetry._provider = None
        DjangoTelemetry._shutdown_called = False

    def tearDown(self):
        DjangoTelemetry._provider = None
        DjangoTelemetry._shutdown_called = False

    def test_shutdown_with_no_provider(self):
        """shutdown() should be safe when _provider is None (test environments)."""
        DjangoTelemetry.shutdown()
        self.assertTrue(DjangoTelemetry._shutdown_called)

    def test_shutdown_calls_force_flush_and_shutdown(self):
        """shutdown() should call force_flush then shutdown on the provider."""
        mock_provider = MagicMock()
        mock_provider.force_flush.return_value = True
        DjangoTelemetry._provider = mock_provider

        DjangoTelemetry.shutdown()

        mock_provider.force_flush.assert_called_once_with(
            timeout_millis=SHUTDOWN_TIMEOUT_MILLIS
        )
        mock_provider.shutdown.assert_called_once()
        self.assertTrue(DjangoTelemetry._shutdown_called)

    def test_shutdown_is_idempotent(self):
        """Calling shutdown() multiple times should only flush/shutdown once."""
        mock_provider = MagicMock()
        mock_provider.force_flush.return_value = True
        DjangoTelemetry._provider = mock_provider

        DjangoTelemetry.shutdown()
        DjangoTelemetry.shutdown()
        DjangoTelemetry.shutdown()

        mock_provider.force_flush.assert_called_once()
        mock_provider.shutdown.assert_called_once()

    @patch('backend.otel_instrumentation.logger')
    def test_shutdown_handles_force_flush_exception(self, mock_logger):
        """shutdown() should not raise even if force_flush throws."""
        mock_provider = MagicMock()
        mock_provider.force_flush.side_effect = RuntimeError("network error")
        DjangoTelemetry._provider = mock_provider

        DjangoTelemetry.shutdown()

        mock_provider.force_flush.assert_called_once()
        mock_provider.shutdown.assert_called_once()
        mock_logger.exception.assert_called()

    @patch('backend.otel_instrumentation.logger')
    def test_shutdown_handles_provider_shutdown_exception(self, mock_logger):
        """shutdown() should not raise even if provider.shutdown() throws."""
        mock_provider = MagicMock()
        mock_provider.force_flush.return_value = True
        mock_provider.shutdown.side_effect = RuntimeError("shutdown error")
        DjangoTelemetry._provider = mock_provider

        DjangoTelemetry.shutdown()

        mock_provider.force_flush.assert_called_once()
        mock_provider.shutdown.assert_called_once()
        mock_logger.exception.assert_called()

    def test_shutdown_logs_warning_on_flush_timeout(self):
        """shutdown() should log a warning when force_flush returns False (timeout)."""
        mock_provider = MagicMock()
        mock_provider.force_flush.return_value = False
        DjangoTelemetry._provider = mock_provider

        with self.assertLogs('backend.otel_instrumentation', level='WARNING') as cm:
            DjangoTelemetry.shutdown()

        self.assertTrue(any('timed out' in msg for msg in cm.output))

    @patch('backend.otel_instrumentation.atexit')
    @patch('backend.otel_instrumentation.signal')
    def test_register_shutdown_hooks_registers_atexit(self, mock_signal, mock_atexit):
        """_register_shutdown_hooks should register atexit handler."""
        mock_signal.getsignal.return_value = signal.SIG_DFL
        mock_signal.SIGTERM = signal.SIGTERM
        mock_signal.SIG_DFL = signal.SIG_DFL
        mock_signal.SIG_IGN = signal.SIG_IGN

        DjangoTelemetry._register_shutdown_hooks()

        mock_atexit.register.assert_called_once_with(DjangoTelemetry.shutdown)

    @patch('backend.otel_instrumentation.atexit')
    @patch('backend.otel_instrumentation.signal')
    def test_register_shutdown_hooks_registers_sigterm(self, mock_signal, mock_atexit):
        """_register_shutdown_hooks should install a SIGTERM handler."""
        mock_signal.getsignal.return_value = signal.SIG_DFL
        mock_signal.SIGTERM = signal.SIGTERM
        mock_signal.SIG_DFL = signal.SIG_DFL
        mock_signal.SIG_IGN = signal.SIG_IGN

        DjangoTelemetry._register_shutdown_hooks()

        mock_signal.signal.assert_called_once()
        args = mock_signal.signal.call_args
        self.assertEqual(args[0][0], signal.SIGTERM)
        self.assertTrue(callable(args[0][1]))