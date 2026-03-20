from drf_spectacular.openapi import AutoSchema
from drf_spectacular.extensions import OpenApiSerializerFieldExtension
from drf_spectacular.plumbing import build_basic_type
from drf_spectacular.utils import Direction
from rest_framework import serializers as drf_serializers
from api.security import OAuth2Authentication
from api.serializers.config_value_read_serializer_list import TimestampField


class TimestampFieldExtension(OpenApiSerializerFieldExtension):
    target_class = TimestampField

    def map_serializer_field(self, auto_schema, direction: Direction):
        return build_basic_type(int)


class MarketingAutoSchema(AutoSchema):
    def get_tags(self):
        is_private = OAuth2Authentication in getattr(self.view, 'authentication_classes', [])
        return ['Private'] if is_private else ['Public']

    def get_auth(self):
        if OAuth2Authentication not in getattr(self.view, 'authentication_classes', []):
            return []
        return [{'OAuth2': []}]
