from rest_framework import serializers
from rest_framework.serializers import ValidationError
from ..models import ConfigValue
from django.utils.translation import ugettext_lazy as _
from django.db.models import Q

from ..utils.validation import HexColorValidator


class ConfigValueWriteSerializer(serializers.ModelSerializer):

    def validate(self, data):
        value = data['value'] if 'value' in data else None
        type = data['type'] if 'type' in data else None
        file = data['file'] if 'file' in data else None
        show_id = data['show_id'] if 'show_id' in data else None
        selection_plan_id = data['selection_plan_id'] if 'selection_plan_id' in data else None
        key = data['key'] if 'key' in data else None

        is_update = self.instance is not None

        # only mandatory on add
        if not key and not is_update:
            raise ValidationError(_('Key is not set.'))

        # only mandatory on add
        if not type and not is_update:
            raise ValidationError(_('Type is not set.'))

        # only mandatory on add
        if not show_id and not is_update:
            raise ValidationError(_('Show Id is not set.'))

        if not file and type is not None and type == 'FILE' and not is_update:
            raise ValidationError(_('File is not set.'))

        if file and type is not None and type != 'FILE' and not is_update:
            raise ValidationError(_('You should remove the file first.'))

        if ((is_update and self.instance.type == 'HEX_COLOR') or (not is_update and type == 'HEX_COLOR')) \
                and not HexColorValidator.is_valid(value):
            raise ValidationError(_('Invalid hex color.'))

        # enforce unique IDX
        query = ConfigValue.objects.filter(show_id=show_id).filter(key=key)
        if selection_plan_id:
            query = query.filter(selection_plan_id=selection_plan_id)

        if is_update:
            query = query.filter(~Q(id=self.instance.id))

        if query.count() > 0:
            raise ValidationError(_('Already exits a combination of key/show id for another config value'))

        return data

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
            'show_id',
            'selection_plan_id',
        )
