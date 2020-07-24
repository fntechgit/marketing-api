from rest_framework.exceptions import ValidationError
from rest_framework.generics import CreateAPIView, GenericAPIView
from rest_framework.parsers import MultiPartParser, JSONParser
from rest_framework.response import Response
from rest_framework import status
from rest_framework import mixins
from ..models import ConfigValue
from ..security import OAuth2Authentication, oauth2_scope_required
from ..serializers import ConfigValueWriteSerializer
from ..services import ConfigValuesService
from ..utils import config
import logging
import traceback


class ConfigValueCreateAPIView(CreateAPIView):
    authentication_classes = [OAuth2Authentication]
    parser_classes = (MultiPartParser,)
    queryset = ConfigValue.objects.all()

    def get_serializer_class(self):
        return ConfigValueWriteSerializer

    @oauth2_scope_required(required_scope=config('OAUTH2_ADD_SCOPE'))
    def post(self, request, *args, **kwargs):
        try:
            logging.getLogger('api').debug('calling ConfigValueCreateAPIView::post')
            return self.create(request, *args, **kwargs)
        except ValidationError as e:
            logging.getLogger('api').warning(e)
            return Response(e.detail, status=status.HTTP_412_PRECONDITION_FAILED)
        except:
            logging.getLogger('api').error(traceback.format_exc())
            return Response('server error', status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ConfigValueUpdateDestroyAPIView(mixins.UpdateModelMixin,
                                      mixins.DestroyModelMixin,
                                      GenericAPIView):
    parser_classes = (MultiPartParser, JSONParser)
    authentication_classes = [OAuth2Authentication]
    queryset = ConfigValue.objects.all()

    def get_serializer_class(self):
        return ConfigValueWriteSerializer

    def patch(self, request, *args, **kwargs):
        pass

    @oauth2_scope_required(required_scope=config('OAUTH2_UPDATE_SCOPE'))
    def put(self, request, *args, **kwargs):
        try:
            logging.getLogger('api').debug('calling ConfigValueCreateAPIView::put')
            return self.partial_update(request, *args, **kwargs)
        except ValidationError as e:
            logging.getLogger('api').warning(e)
            return Response(e.detail, status=status.HTTP_412_PRECONDITION_FAILED)
        except:
            logging.getLogger('api').error(traceback.format_exc())
            return Response('server error', status=status.HTTP_500_INTERNAL_SERVER_ERROR)

    @oauth2_scope_required(required_scope=config('OAUTH2_DELETE_SCOPE'))
    def delete(self, request, *args, **kwargs):
        try:
            logging.getLogger('api').debug('calling ConfigValueCreateAPIView::delete')
            return self.destroy(request, *args, **kwargs)
        except ValidationError as e:
            logging.getLogger('api').warning(e)
            return Response(e.detail, status=status.HTTP_412_PRECONDITION_FAILED)
        except:
            logging.getLogger('api').error(traceback.format_exc())
            return Response('server error', status=status.HTTP_500_INTERNAL_SERVER_ERROR)


class ConfigValueCloneAPIView(GenericAPIView):
    authentication_classes = [OAuth2Authentication]

    def get_serializer_class(self):
        return ConfigValueWriteSerializer

    @oauth2_scope_required(required_scope=config('OAUTH2_CLONE_SCOPE'))
    def post(self, request, show_id, to_show_id, *args, **kwargs):
        try:
            service = ConfigValuesService()
            service.clone_from_to(show_id, to_show_id)
            return Response('', status=status.HTTP_201_CREATED)
        except:
            logging.getLogger('api').error(traceback.format_exc())
            return Response('server error', status=status.HTTP_500_INTERNAL_SERVER_ERROR)
