"""Orders app models — Cart, Order, OrderItem."""
import uuid
from django.db import models
from django.conf import settings


class Cart(models.Model):
    """Temporary in-progress cart item before order is placed."""
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='cart_items'
    )
    table = models.ForeignKey(
        'tables.Table', on_delete=models.CASCADE, related_name='cart_items'
    )
    item = models.ForeignKey(
        'menu.MenuItem', on_delete=models.CASCADE, related_name='cart_items'
    )
    quantity = models.PositiveIntegerField(default=1)
    added_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'carts'
        unique_together = ['user', 'table', 'item']

    def line_total(self):
        return float(self.item.price) * self.quantity

    def __str__(self):
        return f"{self.user.phone_number} | Table {self.table.table_number} | {self.item.name} x{self.quantity}"


class Order(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('preparing', 'Preparing'),
        ('served', 'Served'),
        ('paid', 'Paid'),
        ('paid_by_points', 'Paid by Points'),
    ]
    PAYMENT_STATUS_CHOICES = [
        ('pending', 'Pending'),
        ('completed', 'Completed'),
    ]
    PAYMENT_METHOD_CHOICES = [
        ('cash', 'Cash'),
        ('online', 'Online'),
        ('loyalty_points', 'Loyalty Points'),
    ]

    order_number = models.CharField(max_length=20, unique=True, editable=False)
    table = models.ForeignKey(
        'tables.Table', on_delete=models.CASCADE, related_name='orders'
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='orders'
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='pending')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS_CHOICES, default='pending')
    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD_CHOICES, null=True, blank=True)
    total_amount = models.FloatField(default=0.0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'orders'
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if not self.order_number:
            self.order_number = f"ORD-{uuid.uuid4().hex[:8].upper()}"
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.order_number} — Table {self.table.table_number} [{self.status}]"


class OrderItem(models.Model):
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='items')
    item = models.ForeignKey('menu.MenuItem', on_delete=models.PROTECT, related_name='order_items')
    quantity = models.PositiveIntegerField()
    price = models.FloatField()  # Snapshot price at time of order

    class Meta:
        db_table = 'order_items'

    def line_total(self):
        return self.price * self.quantity

    def __str__(self):
        return f"{self.item.name} x{self.quantity} @ Rs{self.price}"
