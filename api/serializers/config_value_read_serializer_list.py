from rest_framework import serializers
from ..models import ConfigValue
import time


class TimestampField(serializers.Field):
    def to_internal_value(self, data):
        pass

    def to_representation(self, value):
        return int(time.mktime(value.timetuple()))


class ConfigValueReadSerializerList(serializers.ModelSerializer):
    created = TimestampField()
    modified = TimestampField()

    class Meta:
        model = ConfigValue
        fields = (
            'id',
            'created',
            'modified',
            'key',
            'value',
            'type',
            'file',
            'show_id'
        )
