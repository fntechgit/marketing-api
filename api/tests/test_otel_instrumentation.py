import os
import subprocess
import sys

from django.test import SimpleTestCase

# DjangoTelemetry itself (instrumentors, sampler, exporters, shutdown) is tested in base-api-utils.
# This test covers how this service wires it: settings.py.


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
