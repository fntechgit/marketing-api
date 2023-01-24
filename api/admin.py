from django import forms
from django.contrib import admin
from django.core.validators import RegexValidator
from .models import ConfigValue
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _

# custom models


class ConfigValueForm(forms.ModelForm):
    value = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'ckeditor'})
    )

    class Meta:
        model = ConfigValue
        fields = ['key', 'type','show_id','selection_plan_id', 'value', 'file']

    def clean(self):

        key = self.cleaned_data.get('key')
        type = self.cleaned_data.get('type')
        value = self.cleaned_data.get('value')
        file = self.cleaned_data.get('file')
        show_id = self.cleaned_data.get('show_id')
        selection_plan_id = self.cleaned_data['selection_plan_id'] if 'selection_plan_id' in self.cleaned_data else None
        if not key:
            raise ValidationError(_('Key is not set.'))
        # test key format

        val = RegexValidator(
            regex=r'^[\d\w\.]*$',
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

        # enforce unique IDX
        id = self.instance.id if not self.instance is None else 0
        query_set = ConfigValue.objects.filter(show_id=show_id).filter(key=key).exclude(id=id)
        if selection_plan_id:
            query_set = query_set.filter(selection_plan_id=selection_plan_id)
        if query_set.count() > 0:
            raise ValidationError(_('Already exits a combination of key/( show id | selection plan ) for another config value'))

        return self.cleaned_data


class ConfigValueAdmin(admin.ModelAdmin):
    form = ConfigValueForm

    # https://docs.djangoproject.com/en/3.0/ref/contrib/admin/#modeladmin-asset-definitions
    class Media:
        # css fix for chkeditor
        # recall to run $ python manage.py  collectstatic
        css = {
            "all": ("admin/css/config_values.css",)
        }
        js = ('//cdn.ckeditor.com/4.14.0/standard/ckeditor.js',)


admin.site.register(ConfigValue, ConfigValueAdmin)


admin.site.site_header = _('Marketing API Admin')