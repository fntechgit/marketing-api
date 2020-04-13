from django import forms
from django.contrib import admin
from django.core.validators import RegexValidator

from .models import ConfigValue
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

# custom models


class ConfigValueForm(forms.ModelForm):
    class Meta:
        model = ConfigValue
        fields = '__all__'

    def clean(self):
        key = self.cleaned_data.get('key')
        type = self.cleaned_data.get('type')
        value = self.cleaned_data.get('value')
        file = self.cleaned_data.get('file')
        show_id = self.cleaned_data.get('show_id')

        if not key:
            raise ValidationError(_('Key is not set.'))
        # test key format

        val = RegexValidator(
            regex=r'^[\d\w]*$',
            message=_('Key must be Alphanumeric'),
            code='invalid_key'
        )

        val(key)

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

        return self.cleaned_data


class ConfigValueAdmin(admin.ModelAdmin):
    form = ConfigValueForm


admin.site.register(ConfigValue, ConfigValueAdmin)


admin.site.site_header = _('Marketing API Admin')