"""Tables app models — Table, CafeLocation, TableSession."""
import uuid
from django.db import models
from django.conf import settings


class CafeLocation(models.Model):
    """Single record storing the café's GPS location and valid radius."""
    name = models.CharField(max_length=100, default="Main Café")
    address = models.CharField(max_length=255, blank=True, default="")
    phone_number = models.CharField(max_length=20, blank=True, default="")
    latitude = models.FloatField()
    longitude = models.FloatField()
    radius_meters = models.FloatField(default=100.0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'cafe_location'

    def __str__(self):
        return f"{self.name} ({self.latitude}, {self.longitude}) ±{self.radius_meters}m"


class Table(models.Model):
    """Represents a physical table in the cafe."""
    table_number = models.CharField(max_length=50, unique=True)
    qr_token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'tables'
        ordering = ['table_number']

    def __str__(self):
        return f"Table {self.table_number}"


class TableSession(models.Model):
    """Active customer session at a table."""
    table = models.ForeignKey(Table, on_delete=models.CASCADE, related_name='sessions')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='table_sessions'
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = 'table_sessions'

    def __str__(self):
        return f"Session: Table {self.table.table_number} — active={self.is_active}"
