import os

from celery import Celery
from ftn_audit import configure_celery_audit


os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")

app = Celery("backend")
app.config_from_object("django.conf:settings", namespace="CELERY")
configure_celery_audit(app)
