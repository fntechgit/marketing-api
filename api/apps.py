from django.apps import AppConfig


class ApiConfig(AppConfig):
    name = 'api'
    verbose_name = "Marketing Api"

    def ready(self):
        # Ensure formatter registration side effects are loaded at startup.
        import api.audit_formatters  # noqa: F401
