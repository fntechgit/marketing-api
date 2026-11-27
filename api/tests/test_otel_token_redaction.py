from base_api_utils.otel_instrumentation import DjangoTelemetry
from django.core.cache import cache
from django.test import SimpleTestCase
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.mysqlclient import MySQLClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor

from api.tests.otel_test_provider import span_exporter as _exporter

# The hooks and the exporter wrapper (outgoing calls, the introspection URL, failed requests) are
# tested in base-api-utils. These tests go through this service's request cycle and cache.
TOKEN = 'eaLtmOBlE-test-bearer-token'
INSTRUMENTORS = (DjangoInstrumentor, MySQLClientInstrumentor, RedisInstrumentor, RequestsInstrumentor)


class OtelTokenRedactionTest(SimpleTestCase):
    """No exported span attribute may carry an OAuth access token."""

    def setUp(self):
        _exporter.clear()
        DjangoTelemetry.setup('test', service_name='marketing-api', celery=False)
        self.addCleanup(self._uninstrument_all)

    @staticmethod
    def _uninstrument_all():
        for instrumentor in INSTRUMENTORS:
            if instrumentor().is_instrumented_by_opentelemetry:
                instrumentor().uninstrument()

    def _attributes_with_token(self):
        return [
            (span.name, key, value)
            for span in _exporter.get_finished_spans()
            for key, value in span.attributes.items()
            if TOKEN in str(value)
        ]

    def test_incoming_request_url_is_redacted(self):
        # summit-admin sends access_token as a query param (uicore getRequest).
        self.client.get(f'/api/v1/not-a-route?access_token={TOKEN}&expand=values')

        server_spans = [s for s in _exporter.get_finished_spans() if s.kind.name == 'SERVER']
        self.assertTrue(server_spans)
        self.assertEqual(self._attributes_with_token(), [])
        self.assertIn('expand=values', server_spans[0].attributes['http.url'])

    def test_cache_keys_are_not_recorded(self):
        # AccessTokenService caches token info under the raw access token.
        cache.set(TOKEN, {'user_id': 1}, 5)
        cache.get(TOKEN)
        cache.delete(TOKEN)

        self.assertTrue(_exporter.get_finished_spans())
        self.assertEqual(self._attributes_with_token(), [])
