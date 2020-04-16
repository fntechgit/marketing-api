from rest_framework import serializers
from rest_framework.serializers import ValidationError
from ..models import ConfigValue
from django.utils.translation import ugettext_lazy as _


class ConfigValueWriteSerializer(serializers.ModelSerializer):

    def validate(self, data):
        value = data['value'] if 'value' in data else None
        type  = data['type'] if 'type' in data else None
        file  = data['file'] if 'file' in data else None
        show_id = data['show_id'] if 'show_id' in data else None

        if not type:
            raise ValidationError(_('Type is not set.'))

        if not show_id:
            raise ValidationError(_('Show Id is not set.'))

        if not value and type != 'FILE':
            raise ValidationError(_('Value is not set.'))

        if not file and type == 'FILE':
            raise ValidationError(_('File is not set.'))

        if file and type != 'FILE':
            raise ValidationError(_('You should remove the file first.'))

        return data

    class Meta:
        model = ConfigValue
        fields = (
            'key',
            'value',
            'type',
            'file',
            'show_id'
        )
