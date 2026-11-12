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
