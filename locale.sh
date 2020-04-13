#!/bin/bash

source env/bin/activate

cd api

django-admin makemessages -l en

django-admin compilemessages