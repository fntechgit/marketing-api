from django_filters.rest_framework import DjangoFilterBackend, FilterSet
from rest_framework.filters import  OrderingFilter
from rest_framework.generics import ListAPIView, RetrieveAPIView
from ..models import ConfigValue
from ..serializers import ConfigValueReadSerializerList


class ConfigValueFilter(FilterSet):
    class Meta:
        model = ConfigValue
        fields = {
            'key' : ['contains'],
            'type' : ['exact'],
            'show_id' : ['exact'],
            'selection_plan_id': ['exact'],
        }


class ConfigValueFilterWithoutShow(FilterSet):
    class Meta:
        model = ConfigValue
        fields = {
            'key' : ['contains'],
            'type' : ['exact'],
            'selection_plan_id': ['exact'],
        }


class ConfigValueListAPIView(ListAPIView):
    filter_backends = [DjangoFilterBackend, OrderingFilter]
    filterset_class = ConfigValueFilter
    # ordering
    ordering_fields = ['id', 'created', 'updated','show_id','key','selection_plan_id']
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
    ordering_fields = ['id', 'created', 'updated', 'key','selection_plan_id']
    ordering = ['id']

    def get_queryset(self):
        show_id = self.kwargs['show_id'] if 'show_id' in self.kwargs else 0
        selection_plan_id = self.kwargs['selection_plan_id'] if 'selection_plan_id' in self.kwargs else 0
        query_set = ConfigValue.objects.get_queryset().filter(show_id=show_id)
        if selection_plan_id > 0:
            query_set = query_set.filter(selection_plan_id=selection_plan_id)

        return query_set.order_by('id')

    def get_serializer_class(self):
        return ConfigValueReadSerializerList
