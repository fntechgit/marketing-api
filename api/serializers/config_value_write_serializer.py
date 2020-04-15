from rest_framework import serializers
from ..models import ConfigValue


class ConfigValueWriteSerializer(serializers.ModelSerializer):
    class Meta:
            model = ConfigValue
            fields = (
                'key',
                'value',
                'type',
                'file',
                'show_id'
            )
