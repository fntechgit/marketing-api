#!/bin/bash
set -e
export DOCKER_SCAN_SUGGEST=false

docker compose --env-file ./backend/.env up -d
docker compose --env-file ./backend/.env exec app /bin/bash