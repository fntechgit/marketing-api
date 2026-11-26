import logging
import os
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs import LoggingHandler
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter

from backend import otel

APP_LOGGERS = ('api', 'serializers', 'jobs')
PLATFORM_LOGGERS = ('audit', 'oauth2', 'django.request', 'django.server')
# ENV is pinned so the test still enables export where _is_enabled() skips ENV=test.
ENABLED_ENV = {'OTEL_SERVICE_ENABLED': 'true', 'ENV': 'local'}
REPO_ROOT = Path(__file__).resolve().parents[2]
# Boots Django in a fresh process and prints the requested loggers that hold the OTLP handler.
# os._exit skips the atexit flush, so nothing is exported to the unreachable endpoint.
COLD_START_SCRIPT = (
    'import logging, os, sys\n'
    'import django\n'
    'django.setup()\n'
    'from backend import otel\n'
    'handler = otel._otlp_logging_handler\n'
    'print(",".join(n for n in sys.argv[1:] if handler is not None and handler in logging.getLogger(n).handlers))\n'
    'sys.stdout.flush()\n'
    'os._exit(0)\n'
)


class OtelLoggingBridgeTest(SimpleTestCase):
    """Which stdlib loggers configure_otel_logging() ships to the OTLP exporter."""

    def setUp(self):
        otel._configured = False
        otel._otlp_logging_handler = None
        exporter = patch('opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter')
        self.exporter = exporter.start()
        self.addCleanup(exporter.stop)
        # The global provider can only be set once per process; keep it untouched so these tests
        # don't leave a mock-backed provider for later tests. The handler still gets the provider
        # explicitly.
        set_provider = patch('opentelemetry._logs.set_logger_provider')
        set_provider.start()
        self.addCleanup(set_provider.stop)
        self.addCleanup(self._detach_handler)

    @staticmethod
    def _detach_handler():
        handler = otel._otlp_logging_handler
        if handler is not None:
            for name in APP_LOGGERS + PLATFORM_LOGGERS + ('custom',):
                logging.getLogger(name).removeHandler(handler)
        otel._configured = False
        otel._otlp_logging_handler = None

    def _bridged(self, name):
        return otel._otlp_logging_handler in logging.getLogger(name).handlers

    def test_app_loggers_are_bridged_by_default(self):
        # Without them, the `api` errors of the config-values views and the `oauth2` introspection
        # failures never reach Loki.
        with patch.dict(os.environ, ENABLED_ENV, clear=False):
            os.environ.pop('OTEL_BRIDGE_LOGGERS', None)
            otel.configure_otel_logging()

        for name in APP_LOGGERS + PLATFORM_LOGGERS:
            with self.subTest(name):
                self.assertTrue(self._bridged(name), f'logger {name!r} must be shipped to OTLP')
        # A django.request record propagates to `django`; bridging the parent would export it twice.
        self.assertFalse(self._bridged('django'))

    def test_explicit_list_overrides_the_default(self):
        with patch.dict(os.environ, {**ENABLED_ENV, 'OTEL_BRIDGE_LOGGERS': 'custom'}):
            otel.configure_otel_logging()

        self.assertTrue(self._bridged('custom'))
        self.assertFalse(self._bridged('api'))

    def test_env_test_exports_nothing_even_with_the_flag_on(self):
        # A test run started from a .env with logs on would otherwise bridge a real exporter and
        # ship test logs to a collector.
        with patch.dict(os.environ, {'OTEL_SERVICE_ENABLED': 'true', 'ENV': 'test'}):
            os.environ.pop('OTEL_BRIDGE_LOGGERS', None)
            otel.configure_otel_logging()

        self.exporter.assert_not_called()
        self.assertFalse(otel._configured)
        self.assertIsNone(otel._otlp_logging_handler)
        for name in APP_LOGGERS + PLATFORM_LOGGERS:
            with self.subTest(name):
                self.assertFalse(
                    any(isinstance(h, LoggingHandler) for h in logging.getLogger(name).handlers),
                    f'logger {name!r} got an OTLP handler under ENV=test',
                )

    def test_bridge_survives_django_logging_setup_on_cold_start(self):
        # With the flag as a real process env var (a k8s `env:` entry, not the .env file), handlers
        # attached while `backend` is imported are dropped when Django applies LOGGING. This also
        # boots the app with ENV != test.
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


FORK_PROBE_LOGGER = 'otel.fork_probe'


class _ExportRecorder(BaseHTTPRequestHandler):
    """OTLP/HTTP stand-in that keeps connections alive, like the collector, and records the
    client port of every export request."""

    protocol_version = 'HTTP/1.1'
    client_ports = []

    def do_POST(self):
        self.rfile.read(int(self.headers.get('Content-Length', 0)))
        self.client_ports.append(self.client_address[1])
        self.send_response(200)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def log_message(self, *args):
        pass


class OtelLoggingForkTest(SimpleTestCase):
    """A forked worker (gunicorn prefork) must not export over the HTTP connection its parent opened."""

    def setUp(self):
        _ExportRecorder.client_ports = []
        server = ThreadingHTTPServer(('127.0.0.1', 0), _ExportRecorder)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.endpoint = f'http://127.0.0.1:{server.server_address[1]}/v1/logs'
        # Keep the process-wide provider untouched; the mock hands the test the real provider.
        set_provider = patch('opentelemetry._logs.set_logger_provider')
        self.set_provider = set_provider.start()
        self.addCleanup(set_provider.stop)
        otel._configured = False
        otel._otlp_logging_handler = None
        self.addCleanup(self._detach_handler)
        probe = logging.getLogger(FORK_PROBE_LOGGER)
        self.addCleanup(setattr, probe, 'propagate', probe.propagate)
        probe.propagate = False

    @staticmethod
    def _detach_handler():
        handler = otel._otlp_logging_handler
        if handler is not None:
            logging.getLogger(FORK_PROBE_LOGGER).removeHandler(handler)
        otel._configured = False
        otel._otlp_logging_handler = None

    def _configure(self):
        """Configure the bridge against the stand-in; return the provider and the exporter's session."""
        exporter_kwargs = {}

        def exporter_spy(**kwargs):
            exporter_kwargs.update(kwargs)
            return OTLPLogExporter(**kwargs)

        env = {**ENABLED_ENV, 'OTEL_EXPORTER_OTLP_LOGS_ENDPOINT': self.endpoint,
               'OTEL_BRIDGE_LOGGERS': FORK_PROBE_LOGGER}
        with patch.dict(os.environ, env), \
                patch('opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter', side_effect=exporter_spy):
            otel.configure_otel_logging()
        return self.set_provider.call_args.args[0], exporter_kwargs['session']

    @staticmethod
    def _exit_code(pid, timeout):
        """The child's exit code, or None after killing it if it is still running at the timeout."""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            done, status = os.waitpid(pid, os.WNOHANG)
            if done:
                return os.waitstatus_to_exitcode(status)
            time.sleep(0.05)
        os.kill(pid, signal.SIGKILL)
        os.waitpid(pid, 0)
        return None

    def test_forked_child_opens_its_own_export_connection(self):
        # Prefork workers (gunicorn) fork after the parent exported its startup logs. Children
        # reusing that keep-alive connection interleave their requests on one socket, which the
        # collector sees as malformed or duplicated exports.
        provider, _ = self._configure()
        probe = logging.getLogger(FORK_PROBE_LOGGER)
        probe.warning('exported by the parent')
        self.assertTrue(provider.force_flush())

        pid = os.fork()
        if pid == 0:
            try:
                probe.warning('exported by the child')
                provider.force_flush()
            finally:
                os._exit(0)
        os.waitpid(pid, 0)

        self.assertEqual(len(_ExportRecorder.client_ports), 2, _ExportRecorder.client_ports)
        parent_port, child_port = _ExportRecorder.client_ports
        self.assertNotEqual(child_port, parent_port, 'the child reused the connection its parent opened')

    def test_forked_child_exports_although_a_transport_lock_was_held_at_fork(self):
        # A lock another thread holds when the process forks stays held forever in the child. The
        # parent's export thread takes the pool manager lock and the cookie jar lock on every
        # request, so a child that closes or reuses the inherited transport can hang for good.
        provider, session = self._configure()
        probe = logging.getLogger(FORK_PROBE_LOGGER)
        probe.warning('exported by the parent')
        self.assertTrue(provider.force_flush())
        locks = (session.adapters['http://'].poolmanager.pools.lock, session.cookies._cookies_lock)
        held, release = threading.Event(), threading.Event()

        def hold_locks():
            for lock in locks:
                lock.acquire()
            held.set()
            release.wait()
            for lock in reversed(locks):
                lock.release()

        threading.Thread(target=hold_locks, daemon=True).start()
        held.wait()
        pid = os.fork()
        if pid == 0:
            try:
                probe.warning('exported by the child')
                os._exit(0 if provider.force_flush(timeout_millis=5000) else 1)
            finally:
                os._exit(1)
        release.set()

        self.assertEqual(self._exit_code(pid, timeout=15), 0, 'the child hung on a lock inherited from its parent')
        self.assertEqual(len(_ExportRecorder.client_ports), 2, _ExportRecorder.client_ports)


# A fake token, long enough that a part of it in an export cannot be a coincidence.
TOKEN = 'mk-FAKE-otlp-ZqXwVuTsRqPoNmLkJi'


class _Request:
    """What Django passes as the `request` extra on every 4xx and 5xx response."""

    def __str__(self):
        return f"<WSGIRequest: GET '/api/v1/config-values?access_token={TOKEN}'>"


class OtelLogRedactionTest(SimpleTestCase):
    """What the OTLP handler exports for a record that carries a token."""

    def setUp(self):
        otel._configured = False
        otel._otlp_logging_handler = None
        self.exported = InMemoryLogRecordExporter()
        exporter = patch('opentelemetry.exporter.otlp.proto.http._log_exporter.OTLPLogExporter',
                         return_value=self.exported)
        exporter.start()
        self.addCleanup(exporter.stop)
        set_provider = patch('opentelemetry._logs.set_logger_provider')
        self.set_provider = set_provider.start()
        self.addCleanup(set_provider.stop)
        self.addCleanup(self._detach_handler)
        with patch.dict(os.environ, {**ENABLED_ENV, 'OTEL_BRIDGE_LOGGERS': 'oauth2,django.request'}):
            otel.configure_otel_logging()
        self.provider = self.set_provider.call_args.args[0]

    @staticmethod
    def _detach_handler():
        handler = otel._otlp_logging_handler
        if handler is not None:
            for name in ('oauth2', 'django.request'):
                logging.getLogger(name).removeHandler(handler)
        otel._configured = False
        otel._otlp_logging_handler = None

    def _export(self, logger, *args, **kwargs):
        # Only the OTLP handler: the local sinks are not under test here.
        with patch.object(logging.getLogger(logger), 'handlers', [otel._otlp_logging_handler]):
            logging.getLogger(logger).warning(*args, **kwargs)
        self.assertTrue(self.provider.force_flush())
        (exported,) = self.exported.get_finished_logs()
        record = exported.log_record
        return f'{record.body} {dict(record.attributes or {})}'

    def test_a_token_in_the_message_is_not_exported(self):
        # urllib3 and requests write the introspection URL, ?token= included.
        exported = self._export('oauth2', 'POST /oauth2/token/introspection?token=%s', TOKEN)

        self.assertIn('?token=', exported)
        self.assertNotIn(TOKEN[8:20], exported)

    def test_the_query_string_of_the_django_request_extra_is_not_exported(self):
        # From SDK 1.39 the handler exports the request extra as str(request).
        exported = self._export('django.request', 'Forbidden: %s', '/api/v1/config-values', extra={'request': _Request()})

        self.assertIn('WSGIRequest', exported)
        self.assertNotIn(TOKEN[8:20], exported)
