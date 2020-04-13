from django.core.validators import RegexValidator
from django.db import models
from model_utils.models import TimeStampedModel
from django.utils.translation import ugettext_lazy as _


class ConfigValue(TimeStampedModel):

    ConfigType = models.TextChoices('ConfigType', 'TEXT TEXTAREA FILE')
    # unique per show
    key = models.CharField(max_length=128, validators=[
        RegexValidator(
            regex=r'^[\d\w]*$',
            message=_('Key must be Alphanumeric'),
            code='invalid_key'
        ),
    ])
    # could be text_area or file
    type = models.CharField(blank=False, null=False, choices=ConfigType.choices, max_length=12)
    value = models.TextField(blank=True, null=True)
    file = models.FileField(blank=True, null=True, max_length=255)
    show_id = models.IntegerField(default=0)

    class Meta:
        db_table = 'config_value'
        constraints = [
            models.UniqueConstraint(fields=['key', 'show_id'], name='unique_key_show'),
        ]
