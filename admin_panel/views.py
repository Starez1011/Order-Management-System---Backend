"""Admin panel views — SystemConfig, dashboard summary, table clearing."""
from django.utils import timezone
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from django.db.models import Sum
from django.db.models.functions import TruncDay, TruncMonth, TruncYear

from admin_panel.models import SystemConfig, Banner, Offer
from orders.models import Order, OrderItem
from tables.models import Table, TableSession
from payments.models import Payment
from menu.models import MenuItem
from accounts.models import CustomUser
from accounts.permissions import IsAdminUserCustom, IsSuperAdminUserCustom, get_target_admin
from orders.views import broadcast_order_update


def success_response(data=None, message="Success", http_status=200):
    return Response({"success": True, "message": message, "data": data if data is not None else {}}, status=http_status)


def error_response(message, error_code="ERROR", http_status=400):
    return Response({"success": False, "message": message, "error_code": error_code}, status=http_status)


class SystemConfigView(APIView):
    """Admin: get/update loyalty config."""
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        config, _ = SystemConfig.objects.get_or_create(pk=1)
        return success_response({
            "loyalty_percentage": config.loyalty_percentage,
            "point_value": config.point_value,
            "updated_at": config.updated_at.isoformat(),
        })

    def patch(self, request):
        if not request.user.is_superuser:
            return error_response("Only superadmins can update system config.", "FORBIDDEN", 403)
        config, _ = SystemConfig.objects.get_or_create(pk=1)

        loyalty_pct = request.data.get("loyalty_percentage")
        point_val = request.data.get("point_value")

        if loyalty_pct is not None:
            try:
                loyalty_pct = float(loyalty_pct)
                if loyalty_pct < 0 or loyalty_pct > 100:
                    raise ValueError
                config.loyalty_percentage = loyalty_pct
            except (TypeError, ValueError):
                return error_response("loyalty_percentage must be between 0 and 100.", "INVALID_VALUE")

        if point_val is not None:
            try:
                point_val = float(point_val)
                if point_val <= 0:
                    raise ValueError
                config.point_value = point_val
            except (TypeError, ValueError):
                return error_response("point_value must be greater than 0.", "INVALID_VALUE")

        config.save()
        return success_response({
            "loyalty_percentage": config.loyalty_percentage,
            "point_value": config.point_value,
        }, "System config updated.")


class DashboardView(APIView):
    """Admin: live dashboard summary — tables, active orders, today revenue."""
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        target_admin = get_target_admin(request)
        tables = Table.objects.filter(admin=target_admin, is_active=True).prefetch_related('sessions', 'orders')
        today = timezone.now().date()

        table_data = []
        for t in tables:
            active_session = t.sessions.filter(is_active=True).first()
            pending_orders = t.orders.filter(status__in=['order_sent', 'order_received', 'order_served'], payment_status='pending')
            has_unpaid = pending_orders.exists()
            total_due = sum(o.total_amount for o in pending_orders)

            # Status logic
            if not active_session:
                table_status = 'empty'
            elif has_unpaid:
                table_status = 'needs_payment'
            else:
                table_status = 'active'

            table_data.append({
                "table_number": t.table_number,
                "qr_token": str(t.qr_token),
                "status": table_status,
                "has_active_session": active_session is not None,
                "pending_order_count": pending_orders.count(),
                "total_due": total_due,
            })

        # Today's revenue
        today_payments = Payment.objects.filter(admin=target_admin, created_at__date=today)
        today_revenue = sum(p.cash_paid for p in today_payments)
        today_orders = Order.objects.filter(admin=target_admin, created_at__date=today).exclude(status='cancelled').count()

        return success_response({
            "tables": table_data,
            "today_revenue": today_revenue,
            "today_orders": today_orders,
            "total_tables": len(table_data),
        })

class RevenueAnalyticsView(APIView):
    """Admin: detailed historical revenue analytics grouped by day, month, and year."""
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        target_admin = get_target_admin(request)
        # We look at all payments, grouped by different time truncations
        
        # Daywise (last 30 days)
        thirty_days_ago = timezone.now() - timezone.timedelta(days=30)
        daywise = Payment.objects.filter(admin=target_admin, created_at__gte=thirty_days_ago) \
            .annotate(date=TruncDay('created_at')) \
            .values('date') \
            .annotate(revenue=Sum('cash_paid')) \
            .order_by('-date')
            
        # Monthwise (last 12 months)
        twelve_months_ago = timezone.now() - timezone.timedelta(days=365)
        monthwise = Payment.objects.filter(admin=target_admin, created_at__gte=twelve_months_ago) \
            .annotate(month=TruncMonth('created_at')) \
            .values('month') \
            .annotate(revenue=Sum('cash_paid')) \
            .order_by('-month')
            
        # Yearwise (all time)
        yearwise = Payment.objects.filter(admin=target_admin).annotate(year=TruncYear('created_at')) \
            .values('year') \
            .annotate(revenue=Sum('cash_paid')) \
            .order_by('-year')

        # Format dates for JSON
        def format_day(d):
            return { "period": d['date'].strftime('%Y-%m-%d'), "revenue": d['revenue'] or 0 }
            
        def format_month(m):
            return { "period": m['month'].strftime('%Y-%m'), "revenue": m['revenue'] or 0 }
            
        def format_year(y):
            return { "period": y['year'].strftime('%Y'), "revenue": y['revenue'] or 0 }

        return success_response({
            "daywise": [format_day(d) for d in daywise],
            "monthwise": [format_month(m) for m in monthwise],
            "yearwise": [format_year(y) for y in yearwise]
        })

class ClearTableView(APIView):
    """Admin: clear a table after payment — close session, reset status."""
    permission_classes = [IsAdminUserCustom]

    def post(self, request, table_number):
        target_admin = get_target_admin(request)
        try:
            table = Table.objects.get(admin=target_admin, table_number=table_number)
        except Table.DoesNotExist:
            return error_response("Table not found.", "TABLE_NOT_FOUND", 404)

        # Verify no unpaid orders
        unpaid = Order.objects.filter(
            table=table, payment_status='pending'
        ).exclude(status='cancelled').exists()
        if unpaid:
            return error_response(
                "Cannot clear table with unpaid orders. Process payment first.",
                "UNPAID_ORDERS"
            )

        with transaction.atomic():
            TableSession.objects.filter(table=table, is_active=True).update(
                is_active=False,
                ended_at=timezone.now()
            )
            Order.objects.filter(
                table=table, payment_status='completed'
            ).exclude(status='cancelled').update(status='paid')

        # Broadcast update so UI refreshes
        from orders.views import broadcast_order_update
        broadcast_order_update(table)

        return success_response({"table_number": table_number}, "Table cleared successfully.")


class TransferTableView(APIView):
    """Admin: Transfer active session and orders from one table to an empty table."""
    permission_classes = [IsAdminUserCustom]

    def post(self, request, table_number):
        target_admin = get_target_admin(request)
        to_table_number = request.data.get("to_table")
        if not to_table_number:
            return error_response("Destination table (to_table) is required.", "MISSING_DESTINATION")
            
        try:
            from_table = Table.objects.get(admin=target_admin, table_number=table_number)
        except Table.DoesNotExist:
            return error_response("Source table not found.", "TABLE_NOT_FOUND", 404)
            
        try:
            to_table = Table.objects.get(admin=target_admin, table_number=to_table_number)
        except Table.DoesNotExist:
            return error_response("Destination table not found.", "TABLE_NOT_FOUND", 404)

        if from_table.table_number == to_table.table_number:
            return error_response("Cannot transfer a table to itself.", "INVALID_TRANSFER")

        # Verify source table has no paid orders
        has_paid_orders = Order.objects.filter(
            table=from_table,
            payment_status='completed'
        ).exclude(status='cancelled').exists()
        
        if has_paid_orders:
            return error_response("Cannot transfer a table after a payment has been processed.", "PAYMENT_ALREADY_PROCESSED")

        # Verify target table is completely empty
        has_active_session = TableSession.objects.filter(table=to_table, is_active=True).exists()
        has_pending_orders = Order.objects.filter(
            table=to_table, 
            status__in=['order_sent', 'order_received', 'order_served'],
            payment_status='pending'
        ).exists()
        
        if has_active_session or has_pending_orders:
            return error_response("Destination table must be completely empty to accept a transfer.", "TABLE_OCCUPIED")

        # Perform atomic transfer
        with transaction.atomic():
            # Move the active session
            TableSession.objects.filter(table=from_table, is_active=True).update(table=to_table)
            
            # Move active and unpaid orders
            Order.objects.filter(
                table=from_table,
                status__in=['order_sent', 'order_received', 'order_served'],
                payment_status='pending'
            ).update(table=to_table)

        # Broadcast update for both tables
        from orders.views import broadcast_order_update
        broadcast_order_update(from_table)
        broadcast_order_update(to_table)

        return success_response({
            "from_table": from_table.table_number,
            "to_table": to_table.table_number
        }, "Table transferred successfully.")



class AdminOrderHistoryView(APIView):
    """Admin: full order history with filters."""
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        target_admin = get_target_admin(request)
        qs = Order.objects.filter(admin=target_admin).select_related('table', 'user').prefetch_related('items__item')

        # Filters
        table_number = request.GET.get("table_number")
        date_str = request.GET.get("date")

        if table_number:
            qs = qs.filter(table__table_number=table_number)
        if date_str:
            try:
                from datetime import date
                filter_date = date.fromisoformat(date_str)
                qs = qs.filter(created_at__date=filter_date)
            except ValueError:
                return error_response("Invalid date format. Use YYYY-MM-DD.", "INVALID_DATE")

        qs = qs.order_by('-created_at')[:200]

        data = [
            {
                "order_number": o.order_number,
                "table_number": o.table.table_number,
                "user_name": o.user.get_full_name(),
                "phone_number": o.user.phone_number,
                "status": o.status,
                "payment_status": o.payment_status,
                "payment_method": o.get_payment_method_display() if o.payment_method else None,
                "branch_name": o.admin.cafelocation.branch_name if hasattr(o.admin, 'cafelocation') else 'Unknown',
                "total_amount": o.total_amount,
                "created_at": o.created_at.isoformat(),
                "items": [
                    {"name": oi.item.name, "quantity": oi.quantity, "price": oi.price}
                    for oi in o.items.all()
                ],
            }
            for o in qs
        ]
        return success_response(data)

class AdminOrderCreateView(APIView):
    """Admin manually creates an order for a table."""
    permission_classes = [IsAdminUserCustom]

    @transaction.atomic
    def post(self, request, table_number):
        try:
            table = Table.objects.get(table_number=table_number)
        except Table.DoesNotExist:
            return error_response("Table not found.", "TABLE_NOT_FOUND", 404)

        items_data = request.data.get("items", [])
        if not items_data or not isinstance(items_data, list):
            return error_response("Items are required and must be a list.", "INVALID_ITEMS")

        phone_number = request.data.get("phone_number", "").strip()
        if phone_number:
            user, created = CustomUser.objects.get_or_create(
                phone_number=phone_number,
                defaults={'first_name': 'Walk-in', 'last_name': 'Customer', 'is_verified': False}
            )
        else:
            user, created = CustomUser.objects.get_or_create(
                phone_number="0000000000",
                defaults={'first_name': 'Walk-in', 'last_name': 'Customer', 'is_verified': False}
            )

        # Create order
        order = Order.objects.create(
            admin=request.user,
            table=table,
            user=user,
            status='order_sent',
            total_amount=0.0
        )

        total = 0.0
        for item_data in items_data:
            try:
                menu_item = MenuItem.objects.get(pk=item_data["item_id"])
            except MenuItem.DoesNotExist:
                return error_response(f"Menu item {item_data.get('item_id')} not found.", "ITEM_NOT_FOUND")
            
            qty = int(item_data.get("quantity", 1))
            if qty <= 0:
                continue
            
            actual_price = menu_item.discounted_price if menu_item.discounted_price else menu_item.price
            OrderItem.objects.create(
                order=order,
                item=menu_item,
                quantity=qty,
                price=actual_price
            )
            total += float(actual_price) * qty
        
        if total == 0:
            order.delete()
            return error_response("Order must have valid items.", "EMPTY_ORDER")

        order.total_amount = total
        order.save()

        # Activate table session if not active
        session, _ = TableSession.objects.get_or_create(table=table, is_active=True)

        broadcast_order_update(table)
        return success_response({"order_number": order.order_number, "total_amount": order.total_amount}, "Order created.", 201)


class AdminOrderEditView(APIView):
    """Admin edits an existing unpaid order."""
    permission_classes = [IsAdminUserCustom]

    @transaction.atomic
    def patch(self, request, order_number):
        try:
            order = Order.objects.get(order_number=order_number, admin=request.user)
        except Order.DoesNotExist:
            return error_response("Order not found.", "ORDER_NOT_FOUND", 404)

        if order.status in ['paid', 'paid_by_points'] or order.payment_status == 'completed':
            return error_response("Cannot edit a paid order.", "ORDER_ALREADY_PAID")

        items_data = request.data.get("items", [])
        if not items_data or not isinstance(items_data, list):
            return error_response("Items are required and must be a list.", "INVALID_ITEMS")

        # Validate all items first
        valid_items = []
        for item_data in items_data:
            try:
                menu_item = MenuItem.objects.get(pk=item_data["item_id"])
            except MenuItem.DoesNotExist:
                return error_response(f"Menu item {item_data.get('item_id')} not found.", "ITEM_NOT_FOUND")
            
            qty = int(item_data.get("quantity", 1))
            if qty > 0:
                valid_items.append({"menu_item": menu_item, "quantity": qty})

        if not valid_items:
            return error_response("Order must have valid items.", "EMPTY_ORDER")

        # Now apply changes
        with transaction.atomic():
            order.items.all().delete()
            total = 0.0
            
            for v_item in valid_items:
                actual_price = v_item["menu_item"].discounted_price if v_item["menu_item"].discounted_price else v_item["menu_item"].price
                OrderItem.objects.create(
                    order=order,
                    item=v_item["menu_item"],
                    quantity=v_item["quantity"],
                    price=actual_price
                )
                total += float(actual_price) * v_item["quantity"]
            
            order.total_amount = total
            order.save()

        broadcast_order_update(order.table)
        return success_response({"order_number": order.order_number, "total_amount": order.total_amount}, "Order updated.")

from accounts.models import CustomUser

class UserByPhoneView(APIView):
    """Admin checks if a user exists by phone and gets name."""
    permission_classes = [IsAdminUserCustom]

    def get(self, request, phone_number):
        try:
            user = CustomUser.objects.get(phone_number=phone_number)
            # Differentiate a registered user from an auto-created walk-in
            if not user.is_verified and user.first_name == 'Walk-in':
                return error_response("User not found.", "NOT_FOUND", 404)
            
            return success_response({
                "first_name": user.first_name,
                "last_name": user.last_name,
                "loyalty_points": user.loyalty_points
            })
        except CustomUser.DoesNotExist:
            return error_response("User not found.", "NOT_FOUND", 404)


# ─── Promotions: Banners ────────────────────────────────────────────────────

class BannerListView(APIView):
    """Public GET (branch_id param), superadmin POST."""

    def get(self, request):
        qs = Banner.objects.filter(is_active=True)
        data = []
        for b in qs:
            img = None
            if b.image:
                img = b.image.url
            elif b.image_url:
                img = b.image_url
            data.append({
                "id": b.id,
                "title": b.title,
                "subtitle": b.subtitle,
                "image_url": img,
                "display_order": b.display_order,
            })
        return success_response(data)

    def post(self, request):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return error_response("Superadmin access required.", "FORBIDDEN", 403)
        title = request.data.get("title", "").strip()
        if not title:
            return error_response("title is required.")
        banner = Banner.objects.create(
            title=title,
            subtitle=request.data.get("subtitle", ""),
            image_url=request.data.get("image_url", ""),
            display_order=int(request.data.get("display_order", 0)),
            is_active=bool(request.data.get("is_active", True)),
            image=request.FILES.get("image"),
        )
        return success_response({"id": banner.id}, "Banner created.", 201)


class BannerDetailView(APIView):
    """Superadmin PATCH / DELETE a single banner."""

    def _get_banner(self, pk):
        try:
            return Banner.objects.get(pk=pk)
        except Banner.DoesNotExist:
            return None

    def patch(self, request, banner_id):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return error_response("Superadmin access required.", "FORBIDDEN", 403)
        banner = self._get_banner(banner_id)
        if not banner:
            return error_response("Banner not found.", "NOT_FOUND", 404)
        banner.title = request.data.get("title", banner.title)
        banner.subtitle = request.data.get("subtitle", banner.subtitle)
        banner.image_url = request.data.get("image_url", banner.image_url)
        banner.display_order = int(request.data.get("display_order", banner.display_order))
        banner.is_active = request.data.get("is_active", banner.is_active)
        if request.FILES.get("image"):
            banner.image = request.FILES["image"]
        banner.save()
        return success_response(message="Banner updated.")

    def delete(self, request, banner_id):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return error_response("Superadmin access required.", "FORBIDDEN", 403)
        banner = self._get_banner(banner_id)
        if not banner:
            return error_response("Banner not found.", "NOT_FOUND", 404)
        banner.delete()
        return success_response(message="Banner deleted.")


# ─── Promotions: Offers ─────────────────────────────────────────────────────

class OfferListView(APIView):
    """Public GET, superadmin POST."""

    def get(self, request):
        qs = Offer.objects.filter(is_active=True)
        data = []
        for o in qs:
            img = None
            if o.image:
                img = o.image.url
            data.append({
                "id": o.id,
                "title": o.title,
                "description": o.description,
                "discount_text": o.discount_text,
                "image_url": img,
                "valid_until": o.valid_until.isoformat() if o.valid_until else None,
                "display_order": o.display_order,
            })
        return success_response(data)

    def post(self, request):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return error_response("Superadmin access required.", "FORBIDDEN", 403)
        title = request.data.get("title", "").strip()
        discount_text = request.data.get("discount_text", "").strip()
        if not title or not discount_text:
            return error_response("title and discount_text are required.")
        valid_until = request.data.get("valid_until") or None
        offer = Offer.objects.create(
            title=title,
            description=request.data.get("description", ""),
            discount_text=discount_text,
            display_order=int(request.data.get("display_order", 0)),
            is_active=bool(request.data.get("is_active", True)),
            valid_until=valid_until,
            image=request.FILES.get("image"),
        )
        return success_response({"id": offer.id}, "Offer created.", 201)


class OfferDetailView(APIView):
    """Superadmin PATCH / DELETE a single offer."""

    def _get_offer(self, pk):
        try:
            return Offer.objects.get(pk=pk)
        except Offer.DoesNotExist:
            return None

    def patch(self, request, offer_id):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return error_response("Superadmin access required.", "FORBIDDEN", 403)
        offer = self._get_offer(offer_id)
        if not offer:
            return error_response("Offer not found.", "NOT_FOUND", 404)
        offer.title = request.data.get("title", offer.title)
        offer.description = request.data.get("description", offer.description)
        offer.discount_text = request.data.get("discount_text", offer.discount_text)
        offer.display_order = int(request.data.get("display_order", offer.display_order))
        offer.is_active = request.data.get("is_active", offer.is_active)
        valid_until = request.data.get("valid_until")
        if valid_until is not None:
            offer.valid_until = valid_until or None
        if request.FILES.get("image"):
            offer.image = request.FILES["image"]
        offer.save()
        return success_response(message="Offer updated.")

    def delete(self, request, offer_id):
        if not request.user.is_authenticated or not request.user.is_superuser:
            return error_response("Superadmin access required.", "FORBIDDEN", 403)
        offer = self._get_offer(offer_id)
        if not offer:
            return error_response("Offer not found.", "NOT_FOUND", 404)
        offer.delete()
        return success_response(message="Offer deleted.")


# ─── Promotions: Popular Items ───────────────────────────────────────────────

class PopularItemsView(APIView):
    """Public: top 8 most-ordered items, optionally filtered by branch."""

    def get(self, request):
        from django.db.models import Count
        from tables.models import CafeLocation

        branch_id = request.GET.get('branch_id')

        qs = OrderItem.objects.all()

        if branch_id:
            # Filter to orders placed at tables belonging to this branch's admin
            try:
                branch = CafeLocation.objects.get(pk=branch_id)
                qs = qs.filter(order__admin=branch.admin)
            except CafeLocation.DoesNotExist:
                pass  # fall back to global popular items

        top_items = (
            qs
            .values('item__id', 'item__name', 'item__price', 'item__image', 'item__discount_percentage', 'item__discounted_price')
            .annotate(total_ordered=Count('id'))
            .order_by('-total_ordered')[:8]
        )
        data = []
        for row in top_items:
            img = None
            if row['item__image']:
                try:
                    item_obj = MenuItem.objects.get(pk=row['item__id'])
                    img = item_obj.image.url if item_obj.image else None
                except Exception:
                    pass
            data.append({
                "id": row['item__id'],
                "name": row['item__name'],
                "price": str(row['item__price']),
                "discount_percentage": row.get('item__discount_percentage'),
                "discounted_price": str(row['item__discounted_price']) if row.get('item__discounted_price') else None,
                "image_url": img,
                "total_ordered": row['total_ordered'],
            })
        return success_response(data)
