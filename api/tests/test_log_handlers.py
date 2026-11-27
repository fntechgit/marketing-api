import json
import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parents[2]
LOGGERS = ('', 'django', 'api', 'serializers', 'oauth2', 'jobs', 'test')

# Boots Django in a fresh process (settings apply LOGGING once, at import), logs one line on the
# api logger and prints, per logger, the classes of its handlers and the filters of each.
PROBE = '''
import json, logging, os, sys
import django
django.setup()
logging.getLogger("api").warning("probe line")
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
    """LOG_HANDLERS selects the local sinks of every logger this service's LOGGING declares.

    build_logging itself (a single sink, unknown names, no require_debug_true) is tested in
    base-api-utils. These boot this service's settings.
    """

    def _boot(self, **env):
        run_env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'backend.settings', **env}
        if 'LOG_HANDLERS' not in env:
            run_env.pop('LOG_HANDLERS', None)
        result = subprocess.run(
            [sys.executable, '-c', PROBE, *LOGGERS],
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
