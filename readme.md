# Virtual Env

````bash
$ python3.6 -m venv env

$ source env/bin/activate
````

# Install reqs

````
pip install -r requirements.txt 

pip freeze > requirements.txt

pip install gunicorn psycopg2-binary

python manage.py makemigrations

python manage.py migrate
````

https://docs.djangoproject.com/en/3.0/topics/migrations/

# create super user

python manage.py createsuperuser


# static files

see https://docs.djangoproject.com/en/3.0/howto/static-files/deployment

````
$ python manage.py  collectstatic
````

# locale

django-admin makemessages -l es
django-admin compilemessages

# dev server

python manage.py runserver

# kill debug process

sudo lsof -t -i tcp:8000 | xargs kill -9

# health check
Public, unauthenticated liveness endpoint that touches no database, Redis or storage:
```
GET /api/public/v1/health   ->  200 "ok" (text/plain)
```

# OpenTelemetry (logs and traces)
Both come from base-api-utils and are off by default; they are enabled through env vars only (see the OpenTelemetry block in `backend/.env.example`):

- Logs (`base_api_utils.otel_logging`): `OTEL_SERVICE_ENABLED=true` ships the bridged loggers over OTLP/HTTP: the platform loggers plus every logger `settings.LOGGING` declares, or the list in `OTEL_BRIDGE_LOGGERS`.
  Each record is exported redacted: no token, secret or query string credential leaves the process.
- Traces (`base_api_utils.otel_instrumentation`): `OTEL_INSTRUMENTATION_ENABLED=true` instruments Django, MySQL, Redis and `requests`;
  `OTEL_EXPORTER_MODE=otel_endpoint` exports the spans (`console` prints them).
- `OTEL_EXPORTER_OTLP_ENDPOINT` is the collector base URL; `/v1/logs` and `/v1/traces` are appended. Timeouts are milliseconds.
- `ENV=test` never exports.
- `LOG_HANDLERS` picks the local sinks (`file`, `console`, both by default). With the OTLP bridge on, an empty value leaves only OTLP.

Local collector (logs and traces pipelines, output in `logs/otel/`):
```
docker compose --env-file ./backend/.env --profile otel up -d otel-collector
```
