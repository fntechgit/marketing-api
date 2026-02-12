import atexit
import logging
import os
import signal

from opentelemetry import baggage as baggage_api
from opentelemetry import trace
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.mysqlclient import MySQLClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter


OTEL_EXPORTER_OTLP_ENDPOINT = os.getenv('OTEL_EXPORTER_OTLP_ENDPOINT')
OTEL_EXPORTER_MODE = os.getenv('OTEL_EXPORTER_MODE')

SHUTDOWN_TIMEOUT_MILLIS = 5000

logger = logging.getLogger(__name__)


class DjangoTelemetry:

    _provider = None
    _shutdown_called = False

    @staticmethod
    def request_hook(span, request):
        if not span.is_recording():
            return

        # Attach CF-Ray header
        span.set_attribute("cf.ray_id", request.headers.get("Cf-Ray", ""))

        # Attach baggage if present
        baggage_val = baggage_api.get_baggage("cf.ray_id")
        if baggage_val:
            span.set_attribute("baggage.cf.ray_id", baggage_val)

    @staticmethod
    def response_hook(span, request, response):
        if span.is_recording() and hasattr(response, "content"):
            span.set_attribute("http.response.length", len(response.content))

    @staticmethod
    def mysql_hook(span, instance, cursor, statement, parameters):
        """Enrich MySQL spans with DB info"""
        if not span.is_recording():
            return
        try:
            span.set_attribute("db.system", "mysql")
            span.set_attribute("db.name", os.getenv('DB_NAME', 'db'))
            span.set_attribute("db.statement", statement)
        except Exception:
            pass

    @staticmethod
    def redis_hook(span, instance, args, kwargs):
        """Enrich Redis spans with command + keys"""
        if not span.is_recording():
            return
        try:
            cmd = args[0] if args else ""
            span.set_attribute("db.system", "redis")
            span.set_attribute("redis.command", cmd)
            if len(args) > 1:
                # Add first key only (avoid leaking big payloads)
                span.set_attribute("redis.key", str(args[1]))
        except Exception:
            pass

    @classmethod
    def setup(cls, environment):
        if environment != "test":
            if OTEL_EXPORTER_MODE:
                resource = Resource.create({
                    "service.name": os.getenv("OTEL_SERVICE_NAME", "marketing-api")
                })
                # Provider with resource
                provider = TracerProvider(resource=resource)
                trace.set_tracer_provider(provider)
                cls._provider = provider
                if OTEL_EXPORTER_MODE == "otel_endpoint":
                    exporter = OTLPSpanExporter(endpoint=OTEL_EXPORTER_OTLP_ENDPOINT)
                    provider.add_span_processor(BatchSpanProcessor(exporter))
                elif OTEL_EXPORTER_MODE == "console":
                    exporter = ConsoleSpanExporter()
                    provider.add_span_processor(BatchSpanProcessor(exporter))
                cls._register_shutdown_hooks()

        # Django
        DjangoInstrumentor().instrument(
            request_hook=cls.request_hook,
            response_hook=cls.response_hook,
        )
        # MySQL
        MySQLClientInstrumentor().instrument(
            enable_commenter=True,
            cursor_instrumentation_enabled=True,
            span_callback=cls.mysql_hook,
        )
        # Redis
        RedisInstrumentor().instrument(
            tracer_provider=trace.get_tracer_provider(),
            request_hook=cls.redis_hook,
        )

    @classmethod
    def _register_shutdown_hooks(cls):
        """Register atexit and SIGTERM handlers for graceful span flushing."""
        atexit.register(cls.shutdown)

        previous_handler = signal.getsignal(signal.SIGTERM)

        def _sigterm_handler(signum, frame):
            cls.shutdown()
            if callable(previous_handler) and previous_handler not in (
                signal.SIG_DFL, signal.SIG_IGN
            ):
                previous_handler(signum, frame)
            elif previous_handler == signal.SIG_DFL:
                signal.signal(signal.SIGTERM, signal.SIG_DFL)
                signal.raise_signal(signal.SIGTERM)

        signal.signal(signal.SIGTERM, _sigterm_handler)

    @classmethod
    def shutdown(cls):
        """Flush and shut down the TracerProvider."""
        if cls._shutdown_called:
            return
        cls._shutdown_called = True

        provider = cls._provider
        if provider is None:
            return

        try:
            logger.info("DjangoTelemetry::shutdown - flushing spans before shutdown.")
            flushed = provider.force_flush(timeout_millis=SHUTDOWN_TIMEOUT_MILLIS)
            if not flushed:
                logger.warning(
                    "DjangoTelemetry::shutdown - force_flush timed out after %d ms.",
                    SHUTDOWN_TIMEOUT_MILLIS,
                )
        except Exception:
            logger.exception("DjangoTelemetry::shutdown - error during force_flush.")

        try:
            provider.shutdown()
        except Exception:
            logger.exception("DjangoTelemetry::shutdown - error during provider shutdown.")