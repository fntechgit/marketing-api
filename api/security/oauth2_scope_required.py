from django.utils.functional import wraps
from django.utils.translation import ugettext_lazy as _
from django.core.exceptions import PermissionDenied
import logging


def oauth2_scope_required(required_scope):
    def _decorator(view_func):
        def __decorator(view, *args, **kwargs):
            request = view.request
            token_info = request.auth

            if token_info is None:
                raise PermissionDenied(_("token info not present."))

            if 'scope' in token_info:
                current_scope = token_info['scope']

                logging.getLogger('oauth2')\
                    .debug('current scope {current} required scope {required}'.
                           format(current=current_scope, required=required_scope))
                # check scopes
                if set(required_scope.split()).issubset(current_scope.split()):
                    return view_func(view, *args, **kwargs)

            raise PermissionDenied(_("token scopes not present"))

        return wraps(view_func)(__decorator)
    return _decorator
