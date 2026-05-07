from ftn_audit.base_formatter import AbstractAuditLogFormatter
from ftn_audit.registry import register_audit_formatter

from .models import ConfigValue


@register_audit_formatter(model=ConfigValue)
class ConfigValueAuditFormatter(AbstractAuditLogFormatter):
    def get_description(self) -> str:
        subject = self.subject
        return (
            f"ConfigValue {self.event_type}: key={subject.key}, "
            f"show_id={subject.show_id}, selection_plan_id={subject.selection_plan_id}"
        )

    def get_attributes(self):
        subject = self.subject
        attrs = super().get_attributes()
        attrs.update(
            {
                "subject.key": subject.key,
                "subject.show_id": subject.show_id,
                "subject.selection_plan_id": subject.selection_plan_id,
                "subject.type": subject.type,
            }
        )
        return attrs
