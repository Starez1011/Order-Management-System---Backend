"""Payments app models — Payment record."""
from django.db import models
from django.conf import settings
import uuid


class Payment(models.Model):
    table = models.ForeignKey(
        'tables.Table', on_delete=models.SET_NULL, null=True, related_name='payments'
    )
    orders = models.ManyToManyField(
        'orders.Order', related_name='payment_records'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='payments'
    )
    points_used = models.FloatField(default=0.0)
    cash_paid = models.FloatField(default=0.0)
    discount_amount = models.FloatField(default=0.0)
    final_amount = models.FloatField()          # cash_paid portion
    points_earned = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payments'

    def __str__(self):
        return f"Payment for {self.order.order_number} | Cash: Rs{self.cash_paid} | Points: {self.points_used}"

class PaymentRequest(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    table = models.ForeignKey('tables.Table', on_delete=models.CASCADE, related_name='payment_requests')
    amount_requested = models.FloatField()
    points_required = models.FloatField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'payment_requests'

    def __str__(self):
        return f"PaymentReq {self.id} | Order: {self.order.order_number} | Points: {self.points_required}"
