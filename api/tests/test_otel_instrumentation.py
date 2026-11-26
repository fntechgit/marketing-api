import os
import subprocess
import sys
from unittest.mock import patch

from django.test import SimpleTestCase
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.mysqlclient import MySQLClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.trace.export import ConsoleSpanExporter

from backend.otel_instrumentation import DjangoTelemetry, RedactingSpanExporter

INSTRUMENTORS = (DjangoInstrumentor, MySQLClientInstrumentor, RedisInstrumentor, RequestsInstrumentor)


class OtelInstrumentationTest(SimpleTestCase):
    """What DjangoTelemetry wires up. Instrumentors are singletons, so every test undoes them."""

    def setUp(self):
        self.addCleanup(self._uninstrument_all)

    @staticmethod
    def _uninstrument_all():
        for instrumentor in INSTRUMENTORS:
            if instrumentor().is_instrumented_by_opentelemetry:
                instrumentor().uninstrument()

    def test_setup_instruments_outgoing_http_calls(self):
        # The IDP introspection and the Swift calls go through `requests`; without this they get
        # no client spans.
        DjangoTelemetry.setup('test')

        self.assertTrue(RequestsInstrumentor().is_instrumented_by_opentelemetry)
        self.assertTrue(DjangoInstrumentor().is_instrumented_by_opentelemetry)
        self.assertTrue(RedisInstrumentor().is_instrumented_by_opentelemetry)
        self.assertTrue(MySQLClientInstrumentor().is_instrumented_by_opentelemetry)

    def test_span_exporter_posts_to_the_traces_path_of_the_base_endpoint(self):
        # OTEL_EXPORTER_OTLP_ENDPOINT is a base URL (backend/otel.py appends /v1/logs to it).
        # Passed verbatim as `endpoint`, the HTTP exporter would post spans to the collector root.
        with patch.dict(os.environ, {'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://otel-collector:4318'}):
            os.environ.pop('OTEL_EXPORTER_OTLP_TRACES_ENDPOINT', None)
            exporter = DjangoTelemetry.build_span_exporter('otel_endpoint')

        self.assertEqual(exporter._endpoint, 'http://otel-collector:4318/v1/traces')

    def test_span_exporter_honours_an_explicit_traces_endpoint(self):
        env = {
            'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://otel-collector:4318',
            'OTEL_EXPORTER_OTLP_TRACES_ENDPOINT': 'https://traces.example/otlp/v1/traces',
        }
        with patch.dict(os.environ, env):
            exporter = DjangoTelemetry.build_span_exporter('otel_endpoint')

        self.assertEqual(exporter._endpoint, 'https://traces.example/otlp/v1/traces')

    def test_span_exporter_timeout_is_read_in_milliseconds(self):
        # backend/otel.py gives the log exporter OTEL_EXPORTER_OTLP_TIMEOUT in milliseconds (the
        # OTLP spec unit); left to the SDK, the span exporter would read the same 10000 as seconds.
        with patch.dict(os.environ, {'OTEL_EXPORTER_OTLP_TIMEOUT': '10000'}):
            os.environ.pop('OTEL_EXPORTER_OTLP_TRACES_TIMEOUT', None)
            self.assertEqual(DjangoTelemetry.build_span_exporter('otel_endpoint')._timeout, 10.0)

        env = {'OTEL_EXPORTER_OTLP_TIMEOUT': '10000', 'OTEL_EXPORTER_OTLP_TRACES_TIMEOUT': '2500'}
        with patch.dict(os.environ, env):
            self.assertEqual(DjangoTelemetry.build_span_exporter('otel_endpoint')._timeout, 2.5)

        with patch.dict(os.environ, {'OTEL_EXPORTER_OTLP_TIMEOUT': 'soon'}):
            os.environ.pop('OTEL_EXPORTER_OTLP_TRACES_TIMEOUT', None)
            self.assertEqual(DjangoTelemetry.build_span_exporter('otel_endpoint')._timeout, 10.0)

    def test_span_exporter_console_and_disabled_modes(self):
        self.assertIsInstance(DjangoTelemetry.build_span_exporter('console'), ConsoleSpanExporter)
        self.assertIsNone(DjangoTelemetry.build_span_exporter(None))

    @patch.object(DjangoTelemetry, '_register_shutdown_hooks')
    @patch('backend.otel_instrumentation.RequestsInstrumentor')
    @patch('backend.otel_instrumentation.RedisInstrumentor')
    @patch('backend.otel_instrumentation.MySQLClientInstrumentor')
    @patch('backend.otel_instrumentation.DjangoInstrumentor')
    @patch('backend.otel_instrumentation.BatchSpanProcessor')
    @patch('backend.otel_instrumentation.trace')
    @patch('backend.otel_instrumentation.TracerProvider')
    def test_setup_under_env_test_exports_nothing(
            self, mock_provider_cls, mock_trace, mock_processor_cls, *_mocks):
        # ENV=test never exports, even with OTEL_EXPORTER_MODE set (a .env with tracing on), so
        # the suite drives the hooks without a collector.
        self.addCleanup(setattr, DjangoTelemetry, '_provider', None)
        with patch('backend.otel_instrumentation.OTEL_EXPORTER_MODE', 'otel_endpoint'):
            DjangoTelemetry.setup('test')

        mock_provider_cls.assert_not_called()
        mock_processor_cls.assert_not_called()
        mock_trace.set_tracer_provider.assert_not_called()
        DjangoTelemetry._register_shutdown_hooks.assert_not_called()
        self.assertIsNone(DjangoTelemetry._provider)

    @patch.object(DjangoTelemetry, '_register_shutdown_hooks')
    @patch('backend.otel_instrumentation.RequestsInstrumentor')
    @patch('backend.otel_instrumentation.RedisInstrumentor')
    @patch('backend.otel_instrumentation.MySQLClientInstrumentor')
    @patch('backend.otel_instrumentation.DjangoInstrumentor')
    @patch('backend.otel_instrumentation.BatchSpanProcessor')
    @patch('backend.otel_instrumentation.trace')
    @patch('backend.otel_instrumentation.TracerProvider')
    def test_setup_outside_the_test_env_builds_and_registers_the_provider(
            self, mock_provider_cls, mock_trace, mock_processor_cls, *_mocks):
        # The production purpose of setup(): resource + sampler -> provider -> exporter -> global.
        self.addCleanup(setattr, DjangoTelemetry, '_provider', None)
        env = {'ENV': 'staging', 'OTEL_SERVICE_NAME': 'svc-under-test'}
        with patch.dict(os.environ, env), patch('backend.otel_instrumentation.OTEL_EXPORTER_MODE', 'console'):
            DjangoTelemetry.setup('staging')

        provider_kwargs = mock_provider_cls.call_args.kwargs
        resource = provider_kwargs['resource'].attributes
        self.assertEqual(resource['service.name'], 'svc-under-test')
        self.assertEqual(resource['deployment.environment'], 'staging')
        self.assertIn('DropOrphanClientSpans', provider_kwargs['sampler'].get_description())
        provider = mock_provider_cls.return_value
        exporter = mock_processor_cls.call_args.args[0]
        self.assertIsInstance(exporter, RedactingSpanExporter)
        self.assertIsInstance(exporter._exporter, ConsoleSpanExporter)
        provider.add_span_processor.assert_called_once_with(mock_processor_cls.return_value)
        mock_trace.set_tracer_provider.assert_called_once_with(provider)
        self.assertIs(DjangoTelemetry._provider, provider)
        DjangoTelemetry._register_shutdown_hooks.assert_called_once()

    @patch.object(DjangoTelemetry, '_register_shutdown_hooks')
    @patch('backend.otel_instrumentation.RequestsInstrumentor')
    @patch('backend.otel_instrumentation.RedisInstrumentor')
    @patch('backend.otel_instrumentation.MySQLClientInstrumentor')
    @patch('backend.otel_instrumentation.DjangoInstrumentor')
    @patch('backend.otel_instrumentation.BatchSpanProcessor')
    @patch('backend.otel_instrumentation.trace')
    @patch('backend.otel_instrumentation.TracerProvider')
    def test_service_name_defaults_to_the_repo_name(self, mock_provider_cls, *_mocks):
        self.addCleanup(setattr, DjangoTelemetry, '_provider', None)
        with patch.dict(os.environ, {'ENV': 'staging'}), \
                patch('backend.otel_instrumentation.OTEL_EXPORTER_MODE', 'console'):
            os.environ.pop('OTEL_SERVICE_NAME', None)
            DjangoTelemetry.setup('staging')

        self.assertEqual(mock_provider_cls.call_args.kwargs['resource'].attributes['service.name'], 'marketing-api')


class OtelColdStartTest(SimpleTestCase):
    """Booting Django with tracing enabled must leave the OTel middleware in MIDDLEWARE.

    Regression (seen in sponsor-pages-api): when setup() ran before MIDDLEWARE was defined in
    settings.py, the nested settings load it triggered was replaced by the final one and
    requests were never traced.
    """

    def test_tracing_enabled_at_startup_keeps_the_otel_middleware(self):
        code = (
            "import django; django.setup()\n"
            "from django.conf import settings\n"
            "print('otel_middleware_present=%s' % any('opentelemetry' in m for m in settings.MIDDLEWARE))\n"
        )
        env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'backend.settings',
               'OTEL_INSTRUMENTATION_ENABLED': 'true', 'OTEL_EXPORTER_MODE': ''}
        result = subprocess.run([sys.executable, '-c', code], env=env, capture_output=True, text=True, timeout=180)

        self.assertEqual(result.returncode, 0, result.stderr[-3000:])
        self.assertIn('otel_middleware_present=True', result.stdout)
