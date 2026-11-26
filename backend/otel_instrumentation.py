import atexit
import logging
import os
import re
import signal
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from opentelemetry import baggage as baggage_api
from opentelemetry import trace
from opentelemetry.instrumentation.django import DjangoInstrumentor
from opentelemetry.instrumentation.mysqlclient import MySQLClientInstrumentor
from opentelemetry.instrumentation.redis import RedisInstrumentor
from opentelemetry.instrumentation.requests import RequestsInstrumentor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import Event, ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor, ConsoleSpanExporter, SpanExporter
from opentelemetry.sdk.trace.sampling import Decision, ParentBased, Sampler, SamplingResult
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.trace import SpanKind, Status


OTEL_EXPORTER_MODE = os.getenv('OTEL_EXPORTER_MODE')

SHUTDOWN_TIMEOUT_MILLIS = 5000
DEFAULT_EXPORT_TIMEOUT_MILLIS = 10000

# OAuth bearer tokens travel as a query param: `access_token` on incoming requests (read by
# OAuth2Authentication from GET/POST), `token` on the IDP introspection POST that
# OAuth2Authentication makes on every cache miss. OpenTelemetry only redacts a few
# cloud-signature params, so spans would export them.
SENSITIVE_QUERY_PARAMS = frozenset({"access_token", "token"})
URL_ATTRIBUTES = ("http.url", "url.full")
REDACTED = "REDACTED"

logger = logging.getLogger(__name__)


class DropOrphanClientSpans(Sampler):
    """Drop root CLIENT spans; everything else goes to the delegate.

    A CLIENT span with no parent is a db/redis/http call made outside any request, task
    or job span. The Celery worker's broker polling alone produces about one such
    single-span trace per second, which only adds cost and buries the real traces.
    """

    def __init__(self, delegate):
        self._delegate = delegate

    def should_sample(self, parent_context, trace_id, name, kind=None, attributes=None, links=None,
                      trace_state=None):
        if kind == SpanKind.CLIENT:
            return SamplingResult(Decision.DROP, trace_state=trace_state)
        return self._delegate.should_sample(parent_context, trace_id, name, kind, attributes, links, trace_state)

    def get_description(self):
        return f"DropOrphanClientSpans({self._delegate.get_description()})"


def _redact_url(url):
    """Replace the value of every sensitive query param in ``url``; leave other URLs untouched."""
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    if not any(key in SENSITIVE_QUERY_PARAMS for key, _ in query):
        return url
    query = [(key, REDACTED if key in SENSITIVE_QUERY_PARAMS else value) for key, value in query]
    return urlunsplit(parts._replace(query=urlencode(query)))


_SENSITIVE_QUERY_RE = re.compile(r"(?i)\b(access_token|token)=[^&\s'\"\)\]]+")


def _redact_text(value):
    return _SENSITIVE_QUERY_RE.sub(lambda match: f"{match.group(1)}={REDACTED}", value)


def _redact_attributes(attributes):
    return {key: _redact_text(value) if isinstance(value, str) else value for key, value in attributes.items()}


class RedactingSpanExporter(SpanExporter):
    """Strip OAuth tokens from everything the hooks cannot reach before spans are exported.

    The hooks redact ``http.url`` early, but a failed outgoing request records the exception
    text (which urllib3 builds from the URL, token included) as an ``exception`` event and as
    the span status description after the hooks ran. Spans without a token pass through as is.
    """

    def __init__(self, exporter):
        self._exporter = exporter

    def export(self, spans):
        return self._exporter.export([self._redact(span) if self._has_token(span) else span for span in spans])

    def shutdown(self):
        return self._exporter.shutdown()

    def force_flush(self, timeout_millis=30000):
        return self._exporter.force_flush(timeout_millis)

    @staticmethod
    def _has_token(span):
        texts = [str(value) for value in (span.attributes or {}).values()]
        texts += [str(value) for event in span.events for value in (event.attributes or {}).values()]
        texts.append(span.status.description or "")
        return any(_SENSITIVE_QUERY_RE.search(text) for text in texts)

    @staticmethod
    def _redact(span):
        status = span.status
        if status.description:
            status = Status(status.status_code, _redact_text(status.description))
        return ReadableSpan(
            name=span.name,
            context=span.context,
            parent=span.parent,
            resource=span.resource,
            attributes=_redact_attributes(span.attributes or {}),
            events=[Event(event.name, _redact_attributes(event.attributes or {}), event.timestamp) for event in span.events],
            links=span.links,
            kind=span.kind,
            status=status,
            start_time=span.start_time,
            end_time=span.end_time,
            instrumentation_scope=span.instrumentation_scope,
        )


class DjangoTelemetry:

    _provider = None
    _shutdown_called = False

    @staticmethod
    def _get_cf_ray(request):
        # Accept canonical CF-Ray plus common variants seen through proxies.
        header_candidates = ("Cf-Ray", "cf-ray", "CFRay", "cf_ray")

        headers = getattr(request, "headers", None)
        if headers:
            for key in header_candidates:
                value = headers.get(key)
                if value:
                    return value

        meta = getattr(request, "META", {}) or {}
        meta_candidates = ("HTTP_CF_RAY", "HTTP_CFRAY")
        for key in meta_candidates:
            value = meta.get(key)
            if value:
                return value

        return None

    @staticmethod
    def redact_span_urls(span):
        """Strip OAuth tokens from the URL attributes the instrumentation already recorded."""
        attributes = getattr(span, "attributes", None) or {}
        for key in URL_ATTRIBUTES:
            value = attributes.get(key)
            if isinstance(value, str):
                redacted = _redact_url(value)
                if redacted != value:
                    span.set_attribute(key, redacted)

    @staticmethod
    def request_hook(span, request):
        if not span.is_recording():
            return

        DjangoTelemetry.redact_span_urls(span)

        # Attach CF-Ray header
        cf_ray = DjangoTelemetry._get_cf_ray(request)
        if cf_ray:
            span.set_attribute("cf.ray_id", cf_ray)
            span.set_attribute("http.request.header.cf-ray", cf_ray)

        # Attach baggage if present
        baggage_val = baggage_api.get_baggage("cf.ray_id")
        if baggage_val:
            if not cf_ray:
                span.set_attribute("cf.ray_id", baggage_val)
            span.set_attribute("baggage.cf.ray_id", baggage_val)

    @staticmethod
    def response_hook(span, request, response):
        if not span.is_recording():
            return
        try:
            if hasattr(response, "content"):
                span.set_attribute("http.response.length", len(response.content))
        except Exception:
            logger.debug("DjangoTelemetry::response_hook - could not record the response length", exc_info=True)


    @staticmethod
    def outgoing_request_hook(span, request):
        if not span.is_recording():
            return
        DjangoTelemetry.redact_span_urls(span)

    @staticmethod
    def redis_hook(span, instance, args, kwargs):
        """Enrich Redis spans with the command name.

        Keys are deliberately not recorded: OAuth2Authentication caches token info under the
        raw bearer token, so the key of every token lookup is a credential.
        """
        if not span.is_recording():
            return
        try:
            cmd = args[0] if args else ""
            span.set_attribute("db.system", "redis")
            span.set_attribute("redis.command", cmd)
        except Exception:
            logger.debug("DjangoTelemetry::redis_hook - could not record the command", exc_info=True)

    @staticmethod
    def build_sampler():
        """The OTEL_TRACES_SAMPLER-configured sampler, minus orphan CLIENT spans.

        Only root spans reach DropOrphanClientSpans; children follow their parent's decision.
        """
        env_sampler = TracerProvider(shutdown_on_exit=False).sampler
        return ParentBased(root=DropOrphanClientSpans(env_sampler))

    @staticmethod
    def span_export_timeout_seconds():
        """OTEL_EXPORTER_OTLP_TRACES_TIMEOUT, else OTEL_EXPORTER_OTLP_TIMEOUT, read in milliseconds.

        Milliseconds is the OTLP spec unit and what backend/otel.py gives the log exporter from
        the same variables. Left to the SDK, the span exporter reads them as seconds, so the
        documented OTEL_EXPORTER_OTLP_TIMEOUT=10000 became a 10000 s request timeout.
        """
        raw = os.getenv("OTEL_EXPORTER_OTLP_TRACES_TIMEOUT") or os.getenv("OTEL_EXPORTER_OTLP_TIMEOUT") or ""
        try:
            millis = int(raw)
        except ValueError:
            millis = DEFAULT_EXPORT_TIMEOUT_MILLIS
        if millis <= 0:
            millis = DEFAULT_EXPORT_TIMEOUT_MILLIS
        return millis / 1000.0

    @staticmethod
    def build_span_exporter(mode):
        """Span exporter for OTEL_EXPORTER_MODE, or None when spans are not exported."""
        if mode == "otel_endpoint":
            # No explicit endpoint: the exporter then reads OTEL_EXPORTER_OTLP_TRACES_ENDPOINT, or
            # appends /v1/traces to the OTEL_EXPORTER_OTLP_ENDPOINT base (as backend/otel.py does
            # with /v1/logs). Passing the base as `endpoint` would post spans to the collector root.
            return OTLPSpanExporter(timeout=DjangoTelemetry.span_export_timeout_seconds())
        if mode == "console":
            return ConsoleSpanExporter()
        return None

    @classmethod
    def setup(cls, environment):
        if environment != "test":
            # set the OTEL_EXPORTER_MODE to null
            # No Exporter setup if the env is dev and you want to run the tests locally
            if OTEL_EXPORTER_MODE:
                resource = Resource.create({
                    "service.name": os.getenv("OTEL_SERVICE_NAME", "marketing-api"),
                    # Same identity as the logging resource in backend/otel.py.
                    "deployment.environment": os.getenv("ENV", "local"),
                })
                # Provider with resource
                provider = TracerProvider(resource=resource, sampler=cls.build_sampler())
                trace.set_tracer_provider(provider)
                cls._provider = provider
                exporter = cls.build_span_exporter(OTEL_EXPORTER_MODE)
                if exporter is not None:
                    provider.add_span_processor(BatchSpanProcessor(RedactingSpanExporter(exporter)))
                cls._register_shutdown_hooks()

        # The instrumentors are installed regardless of OTEL_EXPORTER_MODE: with no provider
        # configured their spans are no-ops, and the tests drive the hooks through setup("test").
        # Django
        DjangoInstrumentor().instrument(
            request_hook=cls.request_hook,
            response_hook=cls.response_hook,
        )
        # MySQL
        MySQLClientInstrumentor().instrument(
            enable_commenter=True,
            cursor_instrumentation_enabled=True,
        )
        # Redis
        RedisInstrumentor().instrument(
            tracer_provider=trace.get_tracer_provider(),
            request_hook=cls.redis_hook,
        )
        # Outgoing HTTP (IDP introspection, Swift and keystoneauth, any other `requests` client)
        RequestsInstrumentor().instrument(request_hook=cls.outgoing_request_hook)

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
