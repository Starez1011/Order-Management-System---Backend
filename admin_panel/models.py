"""Admin panel models — SystemConfig."""
from django.db import models


class SystemConfig(models.Model):
    """
    Singleton config model.
    Always use pk=1. Use get_or_create(pk=1).
    """
    loyalty_percentage = models.FloatField(default=5.0, help_text="% of bill earned as points")
    point_value = models.FloatField(default=1.0, help_text="1 point = Rs X")
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'system_config'

    def __str__(self):
        return f"SystemConfig | {self.loyalty_percentage}% | 1pt=Rs{self.point_value}"
