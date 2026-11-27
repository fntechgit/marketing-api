import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parents[2]
LOGGERS = ('', 'django', 'api', 'serializers', 'oauth2', 'jobs', 'test')
# The OTLP bridge's own loggers: backend/otel.py logs on audit.otlp, the SDK under opentelemetry.
DIAGNOSTICS = ('audit.otlp', 'opentelemetry')

# Boots Django in a fresh process (settings apply LOGGING once, at import), logs one line on the
# api logger and on the bridge's own loggers, and prints, per logger, the classes of its handlers
# and the filters of each.
PROBE = '''
import json, logging, os, sys
import django
django.setup()
logging.getLogger("api").warning("probe line")
logging.getLogger("audit.otlp").warning("otlp diagnostic")
logging.getLogger("opentelemetry.exporter.otlp.proto.http._log_exporter").error("export failure")
logging.getLogger("opentelemetry.sdk").info("sdk chatter")
for handler in logging.getLogger("").handlers + logging.getLogger("api").handlers:
    handler.flush()
report = {
    name: [[type(h).__name__, [type(f).__name__ for f in h.filters]] for h in logging.getLogger(name).handlers]
    for name in sys.argv[1:]
}
print(json.dumps(report))
sys.stdout.flush()
os._exit(0)
'''


class LogHandlersTest(SimpleTestCase):
    """LOG_HANDLERS selects the local sinks of every logger LOGGING declares."""

    def _boot(self, **env):
        run_env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'backend.settings', **env}
        if 'LOG_HANDLERS' not in env:
            run_env.pop('LOG_HANDLERS', None)
        result = subprocess.run(
            [sys.executable, '-c', PROBE, *LOGGERS, *DIAGNOSTICS],
            cwd=REPO_ROOT, env=run_env, capture_output=True, text=True, timeout=120,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout.strip().splitlines()[-1]), result.stderr

    def test_by_default_every_logger_writes_to_the_file_and_the_console(self):
        report, _ = self._boot()

        for name in LOGGERS:
            with self.subTest(logger=name or 'root'):
                self.assertEqual(sorted(cls for cls, _ in report[name]), ['RedactingFileHandler', 'RedactingStreamHandler'])

    def test_an_empty_value_leaves_every_logger_without_local_sinks(self):
        # What a deployed image sets once the OTLP bridge ships: the process writes neither a file nor stdout.
        report, stderr = self._boot(LOG_HANDLERS='')

        for name in LOGGERS:
            with self.subTest(logger=name or 'root'):
                self.assertEqual(report[name], [['NullHandler', []]])
        # Not even through logging.lastResort, which writes to stderr for a logger with no handler.
        self.assertNotIn('probe line', stderr)

    def test_a_single_sink_can_be_chosen(self):
        report, stderr = self._boot(LOG_HANDLERS='console')

        self.assertEqual(report['api'], [['RedactingStreamHandler', []]])
        self.assertEqual(stderr.count('probe line'), 1, 'the api line reached the console more than once')

    def test_no_logger_emails_errors_to_the_admins(self):
        report, _ = self._boot(LOG_HANDLERS='file,console,mail_admins')

        self.assertNotIn('AdminEmailHandler', json.dumps(report))

    def test_the_console_does_not_depend_on_debug(self):
        # It used to carry require_debug_true, so ENV=production silenced it.
        report, _ = self._boot(LOG_HANDLERS='console', ENV='production')

        self.assertEqual(report['api'], [['RedactingStreamHandler', []]])

    def test_the_bridge_diagnostics_keep_the_console_whatever_the_value(self):
        # With no local sink the app's lines leave only through OTLP. When that export fails, the
        # error that says so cannot travel through it: audit.otlp and opentelemetry are never
        # bridged and always write to the console, once.
        for value in ('', 'file,console'):
            with self.subTest(LOG_HANDLERS=value):
                report, stderr = self._boot(LOG_HANDLERS=value)

                for name in DIAGNOSTICS:
                    self.assertEqual(report[name], [['RedactingStreamHandler', []]])
                self.assertEqual(stderr.count('otlp diagnostic'), 1)
                self.assertEqual(stderr.count('export failure'), 1)
                # opentelemetry is held at WARNING: the SDK's routine lines stay out.
                self.assertNotIn('sdk chatter', stderr)
