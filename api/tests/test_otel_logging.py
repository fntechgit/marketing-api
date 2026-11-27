import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from base_api_utils import otel_logging
from base_api_utils.security import OAuth2Authentication
from django.test import SimpleTestCase
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter
from requests.models import Response
from rest_framework.request import Request
from rest_framework.test import APIRequestFactory

# The bridge itself (exporter, endpoint, headers, fork safety, redaction) is tested in
# base-api-utils. These tests cover what depends on this service: its LOGGING, its loggers and
# its boot order.
APP_LOGGERS = ('api', 'serializers', 'jobs')
PLATFORM_LOGGERS = ('audit', 'oauth2', 'django.request', 'django.server')
# ENV is pinned so the test still enables export where is_enabled() skips ENV=test.
ENABLED_ENV = {'OTEL_SERVICE_ENABLED': 'true', 'ENV': 'local'}
REPO_ROOT = Path(__file__).resolve().parents[2]
# Boots Django in a fresh process and prints the requested loggers that hold the OTLP handler.
# os._exit skips the atexit flush, so nothing is exported to the unreachable endpoint.
COLD_START_SCRIPT = (
    'import logging, os, sys\n'
    'import django\n'
    'django.setup()\n'
    'from base_api_utils import otel_logging\n'
    'handler = otel_logging._otlp_logging_handler\n'
    'print(",".join(n for n in sys.argv[1:] if handler is not None and handler in logging.getLogger(n).handlers))\n'
    'sys.stdout.flush()\n'
    'os._exit(0)\n'
)


class _BridgeTestCase(SimpleTestCase):
    """Configures the bridge against an in-memory exporter and detaches it afterwards."""

    def setUp(self):
        otel_logging._reset_for_tests()
        self.addCleanup(otel_logging._reset_for_tests)
        self.exported = InMemoryLogRecordExporter()
        exporter = patch('opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter',
                         return_value=self.exported)
        exporter.start()
        self.addCleanup(exporter.stop)
        # The global provider can only be set once per process; keep it untouched so these tests
        # don't leave a test provider for later tests. The handler still gets the provider
        # explicitly.
        set_provider = patch('opentelemetry._logs.set_logger_provider')
        self.set_provider = set_provider.start()
        self.addCleanup(set_provider.stop)

    def _configure(self, **env):
        with patch.dict(os.environ, {**ENABLED_ENV, **env}):
            if 'OTEL_BRIDGE_LOGGERS' not in env:
                os.environ.pop('OTEL_BRIDGE_LOGGERS', None)
            otel_logging.configure_otel_logging(service_name='marketing-api')
        return self.set_provider.call_args.args[0]


class OtelLoggingBridgeTest(_BridgeTestCase):
    """Which loggers of this service configure_otel_logging() ships to the OTLP exporter."""

    def test_app_loggers_are_bridged_by_default(self):
        # Without them, the `api` errors of the config-values views and the `oauth2` introspection
        # failures never reach Loki.
        self._configure()

        for name in APP_LOGGERS + PLATFORM_LOGGERS:
            with self.subTest(name):
                self.assertIn(name, otel_logging.bridged_loggers(), f'logger {name!r} must be shipped to OTLP')

    def test_bridge_survives_django_logging_setup_on_cold_start(self):
        # With the flag as a real process env var (a k8s `env:` entry, not the .env file), handlers
        # attached while `backend` is imported are dropped when Django applies LOGGING.
        env = {
            **os.environ,
            **ENABLED_ENV,
            'DJANGO_SETTINGS_MODULE': 'backend.settings',
            'OTEL_EXPORTER_OTLP_ENDPOINT': 'http://127.0.0.1:9',
            'OTEL_EXPORTER_OTLP_LOGS_ENDPOINT': 'http://127.0.0.1:9/v1/logs',
        }
        env.pop('OTEL_BRIDGE_LOGGERS', None)
        names = APP_LOGGERS + PLATFORM_LOGGERS
        result = subprocess.run(
            [sys.executable, '-c', COLD_START_SCRIPT, *names],
            cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120,
        )

        self.assertEqual(result.returncode, 0, result.stderr)
        last_line = result.stdout.strip().splitlines()[-1] if result.stdout.strip() else ''
        self.assertEqual(set(filter(None, last_line.split(','))), set(names), result.stderr)


# A fake token, long enough that a part of it in an export cannot be a coincidence.
TOKEN = 'mk-FAKE-otlp-ZqXwVuTsRqPoNmLkJi'


class OtelLogRedactionTest(_BridgeTestCase):
    """What the OTLP handler exports when this service validates a bearer token."""

    def test_an_introspection_exports_no_part_of_the_token(self):
        # base-api-utils logs each validation on the oauth2 logger at DEBUG. Up to 1.1.120 those
        # lines held the bare token, which no redaction pattern can tell from other text.
        provider = self._configure(OTEL_BRIDGE_LOGGERS='oauth2')
        introspection = Response()
        introspection.status_code = 200
        introspection._content = b'{"expires_in": 60, "scope": "read", "client_id": "client", "user_id": 1}'
        request = Request(APIRequestFactory().get(f'/api/v1/config-values?access_token={TOKEN}'))
        oauth2 = logging.getLogger('oauth2')
        self.addCleanup(oauth2.setLevel, oauth2.level)
        oauth2.setLevel(logging.DEBUG)

        # Only the OTLP handler: the local sinks are not under test here.
        with patch.object(oauth2, 'handlers', [otel_logging._otlp_logging_handler]), \
                patch('base_api_utils.security.access_token_service.cache') as cache, \
                patch('base_api_utils.security.access_token_service.requests.post', return_value=introspection):
            cache.get.return_value = None
            OAuth2Authentication().authenticate(request)

        self.assertTrue(provider.force_flush())
        exported = [f'{data.log_record.body} {dict(data.log_record.attributes or {})}'
                    for data in self.exported.get_finished_logs()]
        self.assertTrue(exported, 'the introspection logged nothing on the oauth2 logger')
        for line in exported:
            self.assertNotIn(TOKEN[8:20], line)
