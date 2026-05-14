import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "backend.settings")
django.setup()

from accounts.models import CustomUser
from tables.models import CafeLocation, Table
from menu.models import Category, MenuItem
from orders.models import Order
from payments.models import Payment, PaymentRequest

# Get the first admin user
admin_user = CustomUser.objects.filter(is_staff=True).first()

if not admin_user:
    print("No admin user found to assign records to.")
else:
    print(f"Assigning records to admin: {admin_user.phone_number}")

    # Assign CafeLocation
    cafe_location = CafeLocation.objects.first()
    if cafe_location:
        cafe_location.admin = admin_user
        cafe_location.save()
    else:
        CafeLocation.objects.create(admin=admin_user)

    # Assign Categories & MenuItems
    Category.objects.update(admin=admin_user)
    MenuItem.objects.update(admin=admin_user)

    # Assign Tables
    Table.objects.update(admin=admin_user)

    # Assign Orders
    Order.objects.update(admin=admin_user)

    # Assign Payments
    Payment.objects.update(admin=admin_user)
    PaymentRequest.objects.update(admin=admin_user)

    print("Data successfully assigned to admin.")
