import os
import subprocess
import sys
from pathlib import Path

from django.test import SimpleTestCase

REPO_ROOT = Path(__file__).resolve().parents[2]
# Fake tokens, long enough that a part of one in a log line cannot be a coincidence.
ACCEPTED = 'mk-FAKE-accepted-ZqXwVuTsRqPoNm'
REFUSED = 'mk-FAKE-refused-LkJiHgYzWvUtSr'

# Boots Django in a fresh process with the configured LOGGING, and validates tokens through
# base_api_utils against an IDP stub on localhost, over real HTTP: requests, urllib3 and their
# DEBUG lines run as in a pod. One token is accepted, one is refused the way OpenStackID refuses
# it (the token in error_description), and one goes to a port nobody listens on.
PROBE = r'''
import json, socket, sys, threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

import django

ACCEPTED, REFUSED = sys.argv[1:3]


class IDP(BaseHTTPRequestHandler):
    def do_POST(self):
        token = parse_qs(urlsplit(self.path).query).get('token', [''])[0]
        if token == ACCEPTED:
            status, body = 200, {'access_token': token, 'scope': 'config-values/add', 'expires_in': 3600,
                                 'client_id': 'client', 'user_id': 1}
        else:
            status, body = 400, {'error': 'invalid_token', 'error_description': f'Access token {token} is expired!'}
        payload = json.dumps(body).encode()
        self.send_response(status)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):
        # The stub's own access log is not the service's.
        pass


django.setup()
import logging
# Root is at WARNING (build_logging), so urllib3's DEBUG request line is raised here: it carries the
# query string, token included, and has to go through the console sink to be tested.
logging.getLogger('urllib3').setLevel(logging.DEBUG)
from django.conf import settings
from base_api_utils.security.access_token_service import AccessTokenService

idp = HTTPServer(('127.0.0.1', 0), IDP)
threading.Thread(target=idp.serve_forever, daemon=True).start()
closed = socket.socket()
closed.bind(('127.0.0.1', 0))
closed_port = closed.getsockname()[1]
closed.close()

with patch('base_api_utils.security.access_token_service.cache') as cache:
    cache.get.return_value = None
    for port, token in ((idp.server_port, ACCEPTED), (idp.server_port, REFUSED), (closed_port, ACCEPTED)):
        settings.OAUTH2['IDP'].update(BASE_URL=f'http://127.0.0.1:{port}',
                                      INTROSPECTION_ENDPOINT='oauth2/token/introspection')
        # validate() returns (user, token info), (None, the IDP's error) or None when the IDP is unreachable.
        result = AccessTokenService().validate(token)
        outcome = 'unreachable' if result is None else 'accepted' if result[0] is not None else 'refused'
        print('OUTCOME', outcome)
sys.stdout.flush()
'''


class IntrospectionLogsTest(SimpleTestCase):
    """What the console sink writes while tokens are introspected over real HTTP, at DEBUG."""

    def test_the_console_carries_no_part_of_an_introspected_token(self):
        env = {**os.environ, 'DJANGO_SETTINGS_MODULE': 'backend.settings', 'ENV': 'local',
               'LOG_HANDLERS': 'console', 'DJANGO_LOG_LEVEL': 'DEBUG', 'API_LOG_LEVEL': 'DEBUG',
               'OAUTH2_LOG_LEVEL': 'DEBUG'}
        result = subprocess.run([sys.executable, '-c', PROBE, ACCEPTED, REFUSED],
                                cwd=REPO_ROOT, env=env, capture_output=True, text=True, timeout=120)
        written = result.stdout + result.stderr

        self.assertEqual(result.returncode, 0, result.stderr)
        outcomes = [line.split()[1] for line in result.stdout.splitlines() if line.startswith('OUTCOME ')]
        self.assertEqual(outcomes, ['accepted', 'refused', 'unreachable'])
        # urllib3 logs the request line at DEBUG, query string included: the path was exercised.
        self.assertIn('"POST /oauth2/token/introspection?token=', result.stderr)
        for token in (ACCEPTED, REFUSED):
            with self.subTest(token=token):
                self.assertNotIn(token, written)
                self.assertNotIn(token[8:20], written, 'a part of the token was written')
