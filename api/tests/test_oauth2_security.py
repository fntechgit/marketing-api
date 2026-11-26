import copy
import json
import logging
import os
from contextlib import contextmanager
from unittest.mock import MagicMock, patch

import requests
from django.conf import settings
from django.test import override_settings
from rest_framework.response import Response
from rest_framework.test import APITestCase

# A fake token, long enough that a part of it in a log line cannot be a coincidence.
TOKEN = 'mk-FAKE-ZqXwVuTsRqPoNmLkJiHgYzWv'
GRANTED = 'config-values/test-granted'
# The loggers marketing-api and base_api_utils.security write to, plus django.request and urllib3.
# Not the root logger: while mail_admins renders its report for an ERROR logged inside an except
# block, django.template logs every missing template variable at DEBUG with the exception being
# handled as its context. That line is Django's, below the INFO level the image runs at.
LOGGERS = ('oauth2', 'api', 'django.request', 'urllib3')

# The private operations and the OAUTH2.CLIENT.ENDPOINTS entry that guards each one.
OPERATIONS = (
    ('post', '/api/v1/config-values', '/api/v1/config-values'),
    ('put', '/api/v1/config-values/1', '/api/v1/config-values/{id}'),
    ('delete', '/api/v1/config-values/1', '/api/v1/config-values/{id}'),
    ('post', '/api/v1/config-values/all/shows/1/clone/2',
     '/api/v1/config-values/all/shows/{show_id}/clone/{to_show_id}'),
)


def _oauth2_granting(scope):
    """settings.OAUTH2 with every endpoint requiring ``scope``; the routes and methods are kept."""
    oauth2 = copy.deepcopy(settings.OAUTH2)
    for methods in oauth2['CLIENT']['ENDPOINTS'].values():
        for endpoint in methods.values():
            endpoint['scopes'] = scope
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
        oauth2 = override_settings(OAUTH2=_oauth2_granting(GRANTED))
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
        # The mail_admins handler sends every ERROR line by email; keep what it would send.
        self.mails = []
        mail = patch('django.utils.log.AdminEmailHandler.send_mail', autospec=True,
                     side_effect=lambda handler, subject, message, *args, **kwargs: self.mails.append(f'{subject}\n{message}'))
        mail.start()
        self.addCleanup(mail.stop)

    def _call(self, method, url, introspection):
        with patch('base_api_utils.security.access_token_service.requests.post', introspection) as post:
            with _logs_at_debug() as lines:
                response = getattr(self.client, method)(url, HTTP_AUTHORIZATION=f'Bearer {TOKEN}')
        return response, post, '\n'.join(lines + self.mails)

    def _assert_no_token_in(self, logged):
        self.assertNotIn(TOKEN, logged)
        self.assertNotIn(TOKEN[8:20], logged, 'a part of the token was logged')

    def test_each_operation_lets_a_token_with_its_scope_through(self):
        for method, url, endpoint in OPERATIONS:
            with self.subTest(method=method, endpoint=endpoint):
                response, _, logged = self._call(method, url, MagicMock(return_value=_introspection(200, _token_info(GRANTED))))

                self.assertIn(response.status_code, (200, 201, 204), response.content)
                self._assert_no_token_in(logged)

    def test_each_operation_refuses_a_token_without_its_scope(self):
        for method, url, endpoint in OPERATIONS:
            with self.subTest(method=method, endpoint=endpoint):
                response, _, logged = self._call(method, url, MagicMock(return_value=_introspection(200, _token_info('other/scope'))))

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
        self._assert_no_token_in(logged)

    @override_settings(DEBUG=False)
    def test_the_introspection_verifies_tls_when_debug_is_off(self):
        _, post, _ = self._call('post', '/api/v1/config-values', MagicMock(return_value=_introspection(200, _token_info(GRANTED))))

        self.assertIs(post.call_args.kwargs['verify'], True)
