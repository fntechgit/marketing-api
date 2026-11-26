import os
from unittest.mock import patch

from django.core.cache import cache
from django.test import SimpleTestCase
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import SpanKind

from backend.otel_instrumentation import DjangoTelemetry


class OtelSamplingTest(SimpleTestCase):
    """A db/redis/http call made outside any request, task or job is not a trace of its own.

    The Celery worker's broker polling alone produced ~1 such single-span trace per second.
    """

    def setUp(self):
        self.exporter = InMemorySpanExporter()
        self.provider = self._provider()
        RedisInstrumentor().instrument(tracer_provider=self.provider)
        self.addCleanup(RedisInstrumentor().uninstrument)

    def _provider(self, sampler_env=None):
        with patch.dict(os.environ, {'OTEL_TRACES_SAMPLER': sampler_env} if sampler_env else {}):
            if not sampler_env:
                os.environ.pop('OTEL_TRACES_SAMPLER', None)
            provider = TracerProvider(sampler=DjangoTelemetry.build_sampler())
        provider.add_span_processor(SimpleSpanProcessor(self.exporter))
        return provider

    def _exported(self):
        return [(span.kind, span.name, span.parent is None) for span in self.exporter.get_finished_spans()]

    def test_a_redis_call_outside_any_span_is_dropped(self):
        cache.get('orphan-probe')

        self.assertEqual(self._exported(), [])

    def test_calls_inside_a_root_span_are_kept_as_its_children(self):
        tracer = self.provider.get_tracer('test')
        for kind, name in ((SpanKind.INTERNAL, 'job probe'), (SpanKind.CONSUMER, 'consume probe'),
                           (SpanKind.SERVER, 'GET /probe')):
            with self.subTest(kind.name):
                self.exporter.clear()
                with tracer.start_as_current_span(name, kind=kind):
                    cache.get('child-probe')

                self.assertEqual(self._exported(), [(SpanKind.CLIENT, 'GET', False), (kind, name, True)])

    def test_a_publish_without_a_parent_is_kept(self):
        with self.provider.get_tracer('test').start_as_current_span('apply_async/x', kind=SpanKind.PRODUCER):
            pass

        self.assertEqual(self._exported(), [(SpanKind.PRODUCER, 'apply_async/x', True)])

    def test_the_env_configured_sampler_still_rules_the_other_roots(self):
        provider = self._provider(sampler_env='always_off')

        with provider.get_tracer('test').start_as_current_span('GET /probe', kind=SpanKind.SERVER):
            pass

        self.assertEqual(self._exported(), [])
        self.assertIn('AlwaysOffSampler', provider.sampler.get_description())
