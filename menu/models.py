"""Menu app models — Category and MenuItem."""
from django.db import models


from django.conf import settings

class Category(models.Model):
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='categories', null=True)
    name = models.CharField(max_length=100)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'menu_categories'
        verbose_name_plural = 'categories'
        ordering = ['name']
        unique_together = ('admin', 'name')

    def __str__(self):
        return self.name


class MenuItem(models.Model):
    admin = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='menu_items', null=True)
    name = models.CharField(max_length=200)
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name='items')
    price = models.DecimalField(max_digits=10, decimal_places=2)
    discount_percentage = models.PositiveIntegerField(null=True, blank=True, help_text="Optional discount percentage (e.g. 20 for 20%)")
    discounted_price = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True, help_text="Final price after discount. Can be manually entered or auto-calculated.")
    image = models.ImageField(upload_to='menu_items/', null=True, blank=True)
    is_available = models.BooleanField(default=True)
    description = models.TextField(blank=True, default='')
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'menu_items'
        ordering = ['category', 'name']

    def save(self, *args, **kwargs):
        if self.discount_percentage and not self.discounted_price:
            # Calculate discount
            calc_price = float(self.price) * (1 - (self.discount_percentage / 100.0))
            # Round to nearest 5
            self.discounted_price = round(calc_price / 5.0) * 5.0
        elif not self.discount_percentage and not self.discounted_price:
            self.discounted_price = None
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.name} (Rs {self.price})"
