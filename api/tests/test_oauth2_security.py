import copy
import json
import logging
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import requests
from django.conf import settings
from django.core.cache import cache as token_info_cache
from django.test import override_settings
from rest_framework.response import Response
from rest_framework.test import APITestCase

# A fake token, long enough that a part of it in a log line cannot be a coincidence.
TOKEN = 'mk-FAKE-ZqXwVuTsRqPoNmLkJiHgYzWv'
# Every logger a line about a request can reach: marketing-api's and base_api_utils.security's,
# Django's (django.template included), urllib3's and the root logger. All of them run at DEBUG.
LOGGERS = ('', 'oauth2', 'api', 'django', 'django.request', 'django.template', 'urllib3')
# As in the chart, every operation also accepts the shared write scope.
WRITE = 'config-values/write'

# The private operations: method, a URL, the OAUTH2.CLIENT.ENDPOINTS entry that guards it, its own scope.
OPERATIONS = (
    ('post', '/api/v1/config-values', '/api/v1/config-values', 'config-values/add'),
    ('put', '/api/v1/config-values/1', '/api/v1/config-values/{id}', 'config-values/update'),
    ('delete', '/api/v1/config-values/1', '/api/v1/config-values/{id}', 'config-values/delete'),
    ('post', '/api/v1/config-values/all/shows/1/clone/2',
     '/api/v1/config-values/all/shows/{show_id}/clone/{to_show_id}', 'config-values/clone'),
)
ADD_SCOPE = OPERATIONS[0][3]


def _oauth2_with_operation_scopes():
    """settings.OAUTH2 with each operation requiring its own scope or the shared write scope."""
    oauth2 = copy.deepcopy(settings.OAUTH2)
    for method, _, endpoint, scope in OPERATIONS:
        oauth2['CLIENT']['ENDPOINTS'][endpoint][method]['scopes'] = f'{scope} {WRITE}'
    oauth2['IDP'].update(BASE_URL='https://idp.example.org', INTROSPECTION_ENDPOINT='oauth2/token/introspection')
    return oauth2


def _introspection(status_code, body):
    response = MagicMock(status_code=status_code)
    response.json.return_value = body
    response.content = json.dumps(body).encode()
    return response


def _token_info(scope):
    return {'access_token': TOKEN, 'scope': scope, 'expires_in': 3600, 'client_id': 'client', 'user_id': 1}


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(self.format(record))


@contextmanager
def _logs_at_debug():
    capture = _Capture()
    capture.setFormatter(logging.Formatter('%(name)s %(levelname)s %(message)s'))
    saved = []
    for name in LOGGERS:
        logger = logging.getLogger(name)
        saved.append((logger, logger.level))
        logger.setLevel(logging.DEBUG)
        logger.addHandler(capture)
    try:
        yield capture.lines
    finally:
        for logger, level in saved:
            logger.removeHandler(capture)
            logger.setLevel(level)


class OAuth2SecurityTest(APITestCase):
    """The private endpoints go through base_api_utils.security, with the scope check enabled."""

    def setUp(self):
        # ENV=test short-circuits the library's scope check; these tests need it to run.
        env = patch.dict(os.environ, {'ENV': 'local'})
        env.start()
        self.addCleanup(env.stop)
        cache = patch('base_api_utils.security.access_token_service.cache')
        self.cache = cache.start()
        self.addCleanup(cache.stop)
        self.cache.get.return_value = None
        oauth2 = override_settings(OAUTH2=_oauth2_with_operation_scopes())
        oauth2.enable()
        self.addCleanup(oauth2.disable)
        # What runs once the scope check lets a request through is not under test here.
        for target, result in (
                ('api.views.private.ConfigValueCreateAPIView.create', Response(status=201)),
                ('api.views.private.ConfigValueUpdateDestroyAPIView.partial_update', Response(status=200)),
                ('api.views.private.ConfigValueUpdateDestroyAPIView.destroy', Response(status=204)),
                ('api.views.private.ConfigValuesService.clone_from_to', None)):
            view = patch(target, return_value=result)
            view.start()
            self.addCleanup(view.stop)

    def _call(self, method, url, introspection):
        with patch('base_api_utils.security.access_token_service.requests.post', introspection) as post:
            with _logs_at_debug() as lines:
                response = getattr(self.client, method)(url, HTTP_AUTHORIZATION=f'Bearer {TOKEN}')
        return response, post, '\n'.join(lines)

    def _call_with_scope(self, method, url, scope):
        return self._call(method, url, MagicMock(return_value=_introspection(200, _token_info(scope))))

    def _assert_no_token_in(self, logged):
        self.assertNotIn(TOKEN, logged)
        self.assertNotIn(TOKEN[8:20], logged, 'a part of the token was logged')

    def test_the_endpoint_entries_are_the_four_private_operations(self):
        # A route or method missing from OAUTH2.CLIENT.ENDPOINTS is refused with a 403.
        configured = {(path, method) for path, methods in settings.OAUTH2['CLIENT']['ENDPOINTS'].items()
                      for method in methods}

        self.assertEqual(configured, {(endpoint, method) for method, _, endpoint, _ in OPERATIONS})

    def test_each_operation_lets_a_token_with_its_own_scope_through(self):
        for method, url, endpoint, scope in OPERATIONS:
            with self.subTest(method=method, endpoint=endpoint):
                response, _, logged = self._call_with_scope(method, url, scope)

                self.assertIn(response.status_code, (200, 201, 204), response.content)
                self._assert_no_token_in(logged)

    def test_each_operation_lets_the_shared_write_scope_through(self):
        for method, url, endpoint, _ in OPERATIONS:
            with self.subTest(method=method, endpoint=endpoint):
                response, _, _ = self._call_with_scope(method, url, WRITE)

                self.assertIn(response.status_code, (200, 201, 204), response.content)

    def test_each_operation_refuses_the_scopes_of_the_other_operations(self):
        for method, url, endpoint, scope in OPERATIONS:
            others = ' '.join(other for *_, other in OPERATIONS if other != scope)
            with self.subTest(method=method, endpoint=endpoint):
                response, _, logged = self._call_with_scope(method, url, others)

                self.assertEqual(response.status_code, 403, response.content)
                self._assert_no_token_in(logged)

    def test_a_request_without_a_token_is_refused(self):
        response = self.client.post('/api/v1/config-values')

        self.assertEqual(response.status_code, 403)

    def test_a_token_the_idp_refuses_is_refused_and_not_logged(self):
        # OpenStackID writes the refused token into error_description.
        refused = _introspection(400, {'error': 'invalid_token', 'error_description': f'Access token {TOKEN} is expired!'})

        response, _, logged = self._call('post', '/api/v1/config-values', MagicMock(return_value=refused))

        self.assertEqual(response.status_code, 403)
        self._assert_no_token_in(logged)

    def test_an_unreachable_idp_refuses_the_request_and_logs_no_part_of_the_token(self):
        # requests puts the introspection URL, ?token=<token> included, into the exception message.
        unreachable = MagicMock(side_effect=requests.exceptions.ConnectionError(
            f"HTTPSConnectionPool(host='idp.example.org', port=443): Max retries exceeded with url: "
            f"/oauth2/token/introspection?token={TOKEN}"))

        response, _, logged = self._call('post', '/api/v1/config-values', unreachable)

        self.assertEqual(response.status_code, 403)
        self.assertIn('oauth2', logged, 'the failed introspection was not logged at all')
        self._assert_no_token_in(logged)

    @override_settings(DEBUG=False)
    def test_the_introspection_verifies_tls_when_debug_is_off(self):
        _, post, _ = self._call_with_scope('post', '/api/v1/config-values', ADD_SCOPE)

        self.assertIs(post.call_args.kwargs['verify'], True)


class TokenInfoCacheTest(APITestCase):
    """The token info is kept in the cache (Redis) for 30 seconds, not for the token's whole lifetime."""

    # OAuth2Authentication reads the Authorization header as bytes (DRF's get_authorization_header),
    # and the token info is cached under the token as read.
    CACHE_KEY = TOKEN.encode()

    def setUp(self):
        env = patch.dict(os.environ, {'ENV': 'local'})
        env.start()
        self.addCleanup(env.stop)
        oauth2 = override_settings(OAUTH2=_oauth2_with_operation_scopes())
        oauth2.enable()
        self.addCleanup(oauth2.disable)
        view = patch('api.views.private.ConfigValueCreateAPIView.create', return_value=Response(status=201))
        view.start()
        self.addCleanup(view.stop)
        token_info_cache.delete(self.CACHE_KEY)
        self.addCleanup(token_info_cache.delete, self.CACHE_KEY)

    def test_a_token_is_introspected_again_after_30_seconds(self):
        # The IDP says the token lives one more hour; a token revoked in the meantime must stop
        # working within 30 seconds, as in purchases-api.
        introspection = MagicMock(return_value=_introspection(200, _token_info(ADD_SCOPE)))

        with patch('base_api_utils.security.access_token_service.requests.post', introspection):
            response = self.client.post('/api/v1/config-values', HTTP_AUTHORIZATION=f'Bearer {TOKEN}')

        self.assertEqual(response.status_code, 201, response.content)
        introspection.assert_called_once()
        ttl = token_info_cache.ttl(self.CACHE_KEY)
        self.assertTrue(0 < ttl <= 30, f'the token info is cached for {ttl} seconds')
