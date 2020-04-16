from django.contrib.auth.models import AnonymousUser
from ..utils import config
from rest_framework import exceptions
from rest_framework.authentication import get_authorization_header, BaseAuthentication
import requests, logging, sys
from django.core.cache import cache


class OAuth2Authentication(BaseAuthentication):

    def authenticate(self, request):

        auth = get_authorization_header(request).split()

        if len(auth) == 1:
            msg = 'Invalid bearer header. No credentials provided.'
            raise exceptions.AuthenticationFailed(msg)
        elif len(auth) > 2:
            msg = 'Invalid bearer header. Token string should not contain spaces.'
            raise exceptions.AuthenticationFailed(msg)

        if auth and auth[0].lower() == b'bearer':
            access_token = auth[1]
        elif 'access_token' in request.POST:
            access_token = request.POST['access_token']
        elif 'access_token' in request.GET:
            access_token = request.GET['access_token']
        else:
            return None

        return OAuth2Authentication.authenticate_credentials(request, access_token)

    @staticmethod
    def authenticate_credentials(request, access_token):
        """
        Authenticate the request, given the access token.
        """
        cached_token_info = None

        # try get access_token from DB and check if not expired
        cached_token_info = cache.get(access_token)

        if cached_token_info is None:
            try:
                response = requests.post(
                    '{base_url}/{endpoint}'.format
                        (
                        base_url=config('OAUTH2_IDP_BASE_URL', None),
                        endpoint=config('OAUTH2_IDP_INTROSPECTION_ENDPOINT', None)
                    ),
                    auth=(config('OAUTH2_CLIENT_ID', None), config('OAUTH2_CLIENT_SECRET', None),),
                    params={'token': access_token},
                    verify=config('DEBUG', False)
                )

                if response.status_code == requests.codes.ok:
                    cached_token_info = response.json()
                    cache.set(access_token, cached_token_info, timeout=cached_token_info['expires_in'])
                else:
                    logging.getLogger('oauth2').warning(
                        'http code {code} http content {content}'.format(code=response.status_code,
                                                                         content=response.content))
                    return None
            except requests.exceptions.RequestException as e:
                logging.getLogger('oauth2').error(e)
                return None
            except:
                logging.getLogger('oauth2').error(sys.exc_info())
                return None

        return AnonymousUser, cached_token_info
