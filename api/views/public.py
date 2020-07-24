from django_filters.rest_framework import DjangoFilterBackend, FilterSet
from rest_framework.filters import  OrderingFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView
from ..models import ConfigValue
from ..serializers import ConfigValueReadSerializerList
import traceback


class ConfigValueFilter(FilterSet):
    class Meta:
        model = ConfigValue
        fields = {
            'key' : ['contains'],
            'type' : ['exact'],
            'show_id' : ['exact'],
        }


class ConfigValueFilterWithoutShow(FilterSet):
    class Meta:
        model = ConfigValue
        fields = {
            'key' : ['contains'],
            'type' : ['exact'],
        }


class ConfigValueListAPIView(ListAPIView):
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ConfigValueFilter
    # ordering
    ordering_fields = ['id', 'created', 'updated','show_id','key']
    ordering = ['id']

    def get_queryset(self):
        return ConfigValue.objects.get_queryset().order_by('id')

    def get_serializer_class(self):
        return ConfigValueReadSerializerList


class ConfigValueRetrieveAPIView(RetrieveAPIView):

    def get_queryset(self):
        return ConfigValue.objects.all()

    def get_serializer_class(self):
        return ConfigValueReadSerializerList


class ConfigValueAllListAPIView(ListAPIView):
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ConfigValueFilterWithoutShow
    # ordering
    ordering_fields = ['id', 'created', 'updated', 'key']
    ordering = ['id']

    def get_queryset(self):
        show_id = self.kwargs['show_id'] if 'show_id' in self.kwargs else 0
        return ConfigValue.objects.get_queryset().filter(show_id=show_id).order_by('id')

    def get_serializer_class(self):
        return ConfigValueReadSerializerList
