"""Admin panel views — SystemConfig, dashboard summary, table clearing."""
from django.utils import timezone
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response

from .models import SystemConfig
from orders.models import Order
from tables.models import Table, TableSession
from payments.models import Payment
from accounts.permissions import IsAdminUserCustom


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
        tables = Table.objects.prefetch_related('sessions', 'orders').filter(is_active=True)
        today = timezone.now().date()

        table_data = []
        for t in tables:
            active_session = t.sessions.filter(is_active=True).first()
            pending_orders = t.orders.filter(status__in=['pending', 'preparing', 'served'])
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
        today_payments = Payment.objects.filter(created_at__date=today)
        today_revenue = sum(p.cash_paid for p in today_payments)
        today_orders = Order.objects.filter(created_at__date=today).count()

        return success_response({
            "tables": table_data,
            "today_revenue": today_revenue,
            "today_orders": today_orders,
            "total_tables": len(table_data),
        })


class ClearTableView(APIView):
    """Admin: clear a table after payment — close session, reset status."""
    permission_classes = [IsAdminUserCustom]

    def post(self, request, table_number):
        try:
            table = Table.objects.get(table_number=table_number)
        except Table.DoesNotExist:
            return error_response("Table not found.", "TABLE_NOT_FOUND", 404)

        # Verify no unpaid orders
        unpaid = Order.objects.filter(
            table=table, status__in=['pending', 'preparing', 'served']
        ).exists()
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

        return success_response({"table_number": table_number}, "Table cleared successfully.")


class AdminOrderHistoryView(APIView):
    """Admin: full order history with filters."""
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        qs = Order.objects.select_related('table', 'user').prefetch_related('items__item')

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
