import atexit
import logging
import os

from backend.env_var_eval import env_bool

_configured = False
_otlp_logging_handler = None
_logger_provider = None


def _is_enabled() -> bool:
    if os.getenv("ENV") == "test":
        return False
    return env_bool("OTEL_SERVICE_ENABLED", False)


def _parse_headers(raw_headers: str) -> dict[str, str]:
    headers: dict[str, str] = {}
    if not raw_headers:
        return headers

    for pair in raw_headers.split(","):
        item = pair.strip()
        if not item or "=" not in item:
            continue
        key, value = item.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key:
            headers[key] = value

    return headers


def _parse_timeout_ms() -> int:
    raw_timeout = os.getenv("OTEL_EXPORTER_OTLP_LOGS_TIMEOUT", os.getenv("OTEL_EXPORTER_OTLP_TIMEOUT", "10000"))
    try:
        return int(raw_timeout)
    except (TypeError, ValueError):
        logging.getLogger("audit.otlp").warning(
            "Invalid OTLP timeout value '%s'. Falling back to default 10000ms.",
            raw_timeout,
        )
        return 10000


# Transport objects a forked child inherited; kept referenced so they are never collected.
_inherited_transports = []


def _reset_session_after_fork(session) -> None:
    """Give a forked child its own connection pools and cookie jar.

    Any lock another thread held at the fork stays held forever in the child, and the parent's
    export thread takes the pool manager, connection queue and cookie jar locks on every request.
    The inherited objects are therefore replaced, never closed, and stay referenced so urllib3's
    pool finalizers (which drain the queue) never run either.
    """
    from requests.adapters import HTTPAdapter
    from requests.cookies import RequestsCookieJar

    _inherited_transports.append((dict(session.adapters), session.cookies))
    session.cookies = RequestsCookieJar()
    for prefix in ("https://", "http://"):
        session.mount(prefix, HTTPAdapter())


def configure_otel_logging() -> None:
    global _configured, _otlp_logging_handler, _logger_provider

    if _configured or not _is_enabled():
        return

    try:
        import requests
        from base_api_utils.utils import RedactingHandlerMixin
        from opentelemetry import _logs
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
        from opentelemetry.sdk.resources import Resource
    except Exception as exc:
        logging.getLogger("audit.otlp").warning(
            "OTLP logging disabled: missing OpenTelemetry logging dependencies (%s)", exc
        )
        return

    class RedactingLoggingHandler(RedactingHandlerMixin, LoggingHandler):
        """Exports a redacted copy of each record (base_api_utils.utils.redact_log_record).

        From SDK 1.39 LoggingHandler exports every extra, and the request Django passes on each 4xx
        and 5xx response goes out as str(request), query string included.
        """

    base_endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4318").rstrip("/")
    logs_endpoint = os.getenv("OTEL_EXPORTER_OTLP_LOGS_ENDPOINT", f"{base_endpoint}/v1/logs")
    timeout_ms = _parse_timeout_ms()
    headers = _parse_headers(os.getenv("OTEL_EXPORTER_OTLP_LOGS_HEADERS", os.getenv("OTEL_EXPORTER_OTLP_HEADERS", "")))

    resource = Resource.create(
        {
            "service.name": os.getenv("OTEL_SERVICE_NAME", "marketing-api"),
            "deployment.environment": os.getenv("ENV", "local"),
        }
    )

    provider = LoggerProvider(resource=resource)
    # Prefork workers (Celery, gunicorn) inherit the exporter's HTTP session together with the
    # keep-alive connection the parent opened, and children writing to that one socket garble or
    # duplicate exports. Each child gets a fresh transport (_reset_session_after_fork).
    session = requests.Session()
    os.register_at_fork(after_in_child=lambda: _reset_session_after_fork(session))
    exporter = OTLPLogExporter(endpoint=logs_endpoint, headers=headers, timeout=timeout_ms / 1000.0, session=session)
    provider.add_log_record_processor(BatchLogRecordProcessor(exporter))
    atexit.register(provider.shutdown)
    _logs.set_logger_provider(provider)

    # Bridge stdlib logging -> OpenTelemetry logs exporter.
    # This is required so existing logger calls (audit/oauth2/django) are shipped as OTLP logs.
    _otlp_logging_handler = RedactingLoggingHandler(level=logging.NOTSET, logger_provider=provider)
    # The app loggers (see LOGGING in settings.py) are bridged too: without them, view and
    # service logs such as the `api` errors of the config-values views never reach the collector.
    bridge_loggers = os.getenv(
        "OTEL_BRIDGE_LOGGERS",
        "audit,oauth2,django.request,django.server,api,serializers,jobs",
    )
    for logger_name in [name.strip() for name in bridge_loggers.split(",") if name.strip()]:
        logger = logging.getLogger(logger_name)
        if _otlp_logging_handler not in logger.handlers:
            logger.addHandler(_otlp_logging_handler)

    _logger_provider = provider
    _configured = True

    logging.getLogger("audit.otlp").info("OTLP logging enabled. endpoint=%s", logs_endpoint)


def shutdown_otel_logging(timeout_millis: int = 5000) -> None:
    """Flush the queued log records and shut the provider down; a no-op when logs are not exported.

    The atexit hook registered in configure_otel_logging() does this when a process exits normally.
    A process that leaves through os._exit (a prefork Celery child) skips atexit and has to call
    this from its own exit hook; marketing-api runs no such process today.
    """
    global _logger_provider
    provider, _logger_provider = _logger_provider, None
    if provider is None:
        return
    try:
        if not provider.force_flush(timeout_millis=timeout_millis):
            logging.getLogger("audit.otlp").warning("OTLP logging: force_flush timed out after %d ms.", timeout_millis)
        provider.shutdown()
    except Exception:
        logging.getLogger("audit.otlp").exception("OTLP logging: error while flushing the log provider.")
