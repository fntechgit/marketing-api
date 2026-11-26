import copy
import json
from unittest.mock import patch

import requests
from django.conf import settings
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.mysqlclient import MySQLClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from requests.adapters import BaseAdapter
from requests.models import Response
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory
from urllib3.exceptions import MaxRetryError

from base_api_utils.security import OAuth2Authentication

from api.tests.otel_test_provider import span_exporter as _exporter
from backend.otel_instrumentation import URL_ATTRIBUTES, DjangoTelemetry, RedactingSpanExporter

TOKEN = 'eaLtmOBlE-test-bearer-token'
INSTRUMENTORS = (DjangoInstrumentor, MySQLClientInstrumentor, RedisInstrumentor, RequestsInstrumentor)


def _oauth2_with_test_idp():
    oauth2 = copy.deepcopy(settings.OAUTH2)
    oauth2['IDP'].update(BASE_URL='https://idp.example', INTROSPECTION_ENDPOINT='oauth2/token/introspection')
    oauth2['CLIENT'].update(ID='client-id', SECRET='client-secret')
    return oauth2


class _AcceptAllAdapter(BaseAdapter):
    def send(self, request, **kwargs):
        response = Response()
        response.status_code = 202
        response._content = b'{}'
        response.url = request.url
        response.request = request
        return response

    def close(self):
        pass


class _DownAdapter(BaseAdapter):
    """The IDP is unreachable: urllib3's MaxRetryError message carries the full URL."""

    def send(self, request, **kwargs):
        raise requests.ConnectionError(MaxRetryError(None, request.url, 'connection refused'), request=request)

    def close(self):
        pass


class OtelTokenRedactionTest(SimpleTestCase):
    """No exported span attribute may carry an OAuth access token."""

    def setUp(self):
        _exporter.clear()
        DjangoTelemetry.setup('test')
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
        self.client.get(f'/api/v1/not-a-route?access_token={TOKEN}&expand=forms')

        server_spans = [s for s in _exporter.get_finished_spans() if s.kind.name == 'SERVER']
        self.assertTrue(server_spans)
        self.assertEqual(self._attributes_with_token(), [])
        self.assertIn('expand=forms', server_spans[0].attributes['http.url'])

    def test_outgoing_request_url_is_redacted(self):
        session = requests.Session()
        session.mount('http://', _AcceptAllAdapter())
        session.post('http://sibling-api/api/v1/resource', params={'access_token': TOKEN}, json={})

        client_spans = [s for s in _exporter.get_finished_spans() if s.kind.name == 'CLIENT']
        self.assertTrue(client_spans)
        self.assertEqual(self._attributes_with_token(), [])

    def test_idp_introspection_url_is_redacted(self):
        # OAuth2Authentication posts the bearer token as the `token` query param (requests puts
        # `params` in the URL even for POST) on every cache miss.
        session = requests.Session()
        session.mount('https://', _AcceptAllAdapter())
        session.post('https://idp.example/oauth2/token/introspection', params={'token': TOKEN},
                     auth=('client-id', 'client-secret'))

        client_spans = [s for s in _exporter.get_finished_spans() if s.kind.name == 'CLIENT']
        self.assertTrue(client_spans)
        self.assertEqual(self._attributes_with_token(), [])

    def test_failed_outgoing_request_exports_neither_token_in_events_nor_status(self):
        # urllib3 builds the exception text from the URL, token included; the instrumentation
        # records it as an `exception` event and as the status description after the hooks ran,
        # so the exporter wrapper is the only place left to strip it.
        exported = InMemorySpanExporter()
        provider = TracerProvider()
        provider.add_span_processor(SimpleSpanProcessor(RedactingSpanExporter(exported)))
        RequestsInstrumentor().uninstrument()
        RequestsInstrumentor().instrument(tracer_provider=provider, request_hook=DjangoTelemetry.outgoing_request_hook)
        session = requests.Session()
        session.mount('https://', _DownAdapter())

        for param in ('token', 'access_token'):
            with self.subTest(param), self.assertRaises(requests.ConnectionError):
                session.post('https://idp.example/oauth2/token/introspection', params={param: TOKEN})

        spans = exported.get_finished_spans()
        self.assertEqual(len(spans), 2)
        for span in spans:
            self.assertEqual(span.status.status_code.name, 'ERROR')
            self.assertEqual([event.name for event in span.events], ['exception'])
            exported_text = ' '.join([str(dict(span.attributes)), str(span.status.description),
                                      str([dict(event.attributes) for event in span.events])])
            self.assertNotIn(TOKEN, exported_text)
            self.assertIn('token=REDACTED', exported_text)

    def test_cache_keys_are_not_recorded(self):
        # OAuth2Authentication caches token info under the raw access token.
        cache.set(TOKEN, {'user_id': 1}, 5)
        cache.get(TOKEN)
        cache.delete(TOKEN)

        self.assertTrue(_exporter.get_finished_spans())
        self.assertEqual(self._attributes_with_token(), [])

    @override_settings(OAUTH2=_oauth2_with_test_idp())
    def test_oauth2_authentication_records_the_token_nowhere(self):
        # The real flow: a request with ?access_token= is introspected on the cache miss (POST
        # with params={'token': ...}) and the token info is cached under the raw token; the
        # second request is served from that cache entry.
        token_info = {'expires_in': 60, 'scope': 'config-values/write'}

        def idp_send(request, **kwargs):
            response = Response()
            response.status_code = 200
            response._content = json.dumps(token_info).encode()
            response.encoding = 'utf-8'
            response.url = request.url
            response.request = request
            return response

        cache.delete(TOKEN)
        self.addCleanup(cache.delete, TOKEN)
        _exporter.clear()
        request = Request(APIRequestFactory().get(f'/api/v1/config-values?access_token={TOKEN}'))
        with patch('requests.adapters.HTTPAdapter.send', side_effect=idp_send) as send:
            first = OAuth2Authentication().authenticate(request)
            second = OAuth2Authentication().authenticate(request)

        self.assertEqual(first[1], token_info)
        self.assertEqual(second[1], token_info)
        send.assert_called_once()
        spans = _exporter.get_finished_spans()
        http_spans = [s for s in spans if s.kind.name == 'CLIENT' and s.name == 'POST']
        self.assertEqual(len(http_spans), 1)
        url = next(http_spans[0].attributes[key] for key in URL_ATTRIBUTES if key in http_spans[0].attributes)
        self.assertIn('token=REDACTED', url)
        redis_commands = [s.attributes.get('redis.command') for s in spans if s.attributes.get('db.system') == 'redis']
        # cache miss (GET), cache fill (SET), cache hit (GET)
        self.assertEqual(redis_commands, ['GET', 'SET', 'GET'])
        self.assertEqual(self._attributes_with_token(), [])
