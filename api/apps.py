from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'
    verbose_name = "Marketing Api"

    def ready(self):
        # After Django applied LOGGING; attached earlier, dictConfig would drop the OTLP handlers.
        from backend.otel import configure_otel_logging
        configure_otel_logging()
