"""Admin panel models — SystemConfig, Banner, Offer."""
from django.db import models
from django.conf import settings


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


class Banner(models.Model):
    """Auto-scrolling promotional banners shown in the mobile app dashboard."""
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='banners',
        null=True, blank=True,
        help_text="Leave blank for global banners shown to all branches."
    )
    title = models.CharField(max_length=200)
    subtitle = models.CharField(max_length=300, blank=True, default='')
    image = models.ImageField(upload_to='banners/', null=True, blank=True)
    image_url = models.URLField(blank=True, default='', help_text="External URL — used if no image file is uploaded.")
    is_active = models.BooleanField(default=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'banners'
        ordering = ['display_order', '-created_at']

    def __str__(self):
        return self.title


class Offer(models.Model):
    """Discount / promotional offers shown on the mobile app dashboard."""
    admin = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='offers',
        null=True, blank=True,
        help_text="Leave blank for global offers."
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True, default='')
    discount_text = models.CharField(max_length=60, help_text='e.g. "20% OFF" or "Buy 1 Get 1"')
    image = models.ImageField(upload_to='offers/', null=True, blank=True)
    is_active = models.BooleanField(default=True)
    valid_until = models.DateField(null=True, blank=True)
    display_order = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'offers'
        ordering = ['display_order', '-created_at']

    def __str__(self):
        return f"{self.title} — {self.discount_text}"

