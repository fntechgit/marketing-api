from rest_framework.exceptions import ValidationError
from rest_framework.generics import CreateAPIView, DestroyAPIView, UpdateAPIView
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.response import Response
from rest_framework import status
from ..security import OAuth2Authentication, oauth2_scope_required
from ..serializers import ConfigValueWriteSerializer
from ..utils import setting
import logging, sys


class ConfigValueCreateAPIView(CreateAPIView):
    authentication_classes = [OAuth2Authentication]
    parser_classes = (MultiPartParser,)

    def get_serializer_class(self):
        return ConfigValueWriteSerializer

    @oauth2_scope_required(required_scope=setting('OAUTH2_ADD_SCOPE'))
    def post(self, request, *args, **kwargs):
        try:
            return self.create(request, *args, **kwargs)
        except ValidationError as e:
            logging.getLogger('api').warning(e)
            return Response(e.detail, status=status.HTTP_412_PRECONDITION_FAILED)
        except:
            logging.getLogger('api').error(sys.exc_info()[0])
            return Response('server error', status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ConfigValueUpdateAPIView(UpdateAPIView):
    parser_classes = (MultiPartParser,)
    authentication_classes = [OAuth2Authentication]

    def get_serializer_class(self):
        return ConfigValueWriteSerializer

    def patch(self, request, *args, **kwargs):
        pass

    @oauth2_scope_required(required_scope=setting('OAUTH2_UPDATE_SCOPE'))
    def put(self, request, *args, **kwargs):
        return self.update(request, *args, **kwargs)


class ConfigValueDestroyAPIView(DestroyAPIView):
    authentication_classes = [OAuth2Authentication]
    parser_classes = (JSONParser,)

    @oauth2_scope_required(required_scope=setting('OAUTH2_DELETE_SCOPE'))
    def delete(self, request, *args, **kwargs):
        return self.destroy(request, *args, **kwargs)


