"""Orders app views — Cart and Order management."""
import json
from django.db import transaction
from django.utils import timezone
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from channels.layers import get_channel_layer
from asgiref.sync import async_to_sync

from .models import Cart, Order, OrderItem
from tables.models import Table, TableSession
from menu.models import MenuItem
from accounts.permissions import IsAuthenticatedUserCustom, IsAdminUserCustom


def success_response(data=None, message="Success", http_status=200):
    return Response({"success": True, "message": message, "data": data if data is not None else {}}, status=http_status)


def error_response(message, error_code="ERROR", http_status=400):
    return Response({"success": False, "message": message, "error_code": error_code}, status=http_status)


def broadcast_order_update(table_number):
    """Push live update to per-table WebSocket group AND the global dashboard group."""
    try:
        channel_layer = get_channel_layer()
        # Notify the per-table listener (TableDetail page)
        async_to_sync(channel_layer.group_send)(
            f"table_{table_number}",
            {"type": "order_update", "table_number": table_number}
        )
        # Notify the global dashboard listener (Dashboard page)
        async_to_sync(channel_layer.group_send)(
            "dashboard",
            {"type": "dashboard_update", "table_number": table_number}
        )
    except Exception:
        pass


def serialize_order(order):
    return {
        "order_number": order.order_number,
        "table_number": order.table.table_number,
        "user_name": order.user.get_full_name(),
        "phone_number": order.user.phone_number,
        "status": order.status,
        "total_amount": order.total_amount,
        "created_at": order.created_at.isoformat(),
        "items": [
            {
                "name": oi.item.name,
                "quantity": oi.quantity,
                "price": oi.price,
                "line_total": oi.line_total(),
            }
            for oi in order.items.select_related('item').all()
        ],
    }


# ─────────────────────── Cart Views ───────────────────────

class CartView(APIView):
    """Get / add / update / clear cart items."""
    permission_classes = [IsAuthenticatedUserCustom]

    def get(self, request):
        qr_token = request.GET.get("qr_token", "").strip()
        if not qr_token:
            return error_response("qr_token is required.", "MISSING_QR_TOKEN")
        try:
            table = Table.objects.get(qr_token=qr_token, is_active=True)
        except Table.DoesNotExist:
            return error_response("Invalid table.", "INVALID_TABLE", 404)

        cart_items = (
            Cart.objects
            .filter(user=request.user, table=table)
            .select_related('item', 'item__category')
        )
        items = [
            {
                "item_id": ci.item.id,
                "name": ci.item.name,
                "price": str(ci.item.price),
                "quantity": ci.quantity,
                "line_total": ci.line_total(),
            }
            for ci in cart_items
        ]
        total = sum(i["line_total"] for i in items)
        return success_response({"items": items, "total": total})

    def post(self, request):
        """Add or update item in cart."""
        qr_token = request.data.get("qr_token", "").strip()
        item_id = request.data.get("item_id")
        quantity = request.data.get("quantity", 1)

        if not all([qr_token, item_id]):
            return error_response("qr_token and item_id are required.", "MISSING_FIELDS")

        try:
            quantity = int(quantity)
            if quantity < 1:
                raise ValueError
        except (TypeError, ValueError):
            return error_response("Quantity must be a positive integer.", "INVALID_QUANTITY")

        try:
            table = Table.objects.get(qr_token=qr_token, is_active=True)
        except Table.DoesNotExist:
            return error_response("Invalid table.", "INVALID_TABLE", 404)

        try:
            item = MenuItem.objects.get(pk=item_id, is_available=True)
        except MenuItem.DoesNotExist:
            return error_response("Item not found or unavailable.", "ITEM_NOT_FOUND", 404)

        cart_item, created = Cart.objects.update_or_create(
            user=request.user, table=table, item=item,
            defaults={"quantity": quantity}
        )
        msg = "Item added to cart." if created else "Cart item updated."
        return success_response({"item_id": item.id, "quantity": cart_item.quantity}, msg, 201 if created else 200)

    def delete(self, request):
        """Remove a single item or clear entire cart."""
        qr_token = request.data.get("qr_token", "").strip()
        item_id = request.data.get("item_id")

        try:
            table = Table.objects.get(qr_token=qr_token, is_active=True)
        except Table.DoesNotExist:
            return error_response("Invalid table.", "INVALID_TABLE", 404)

        if item_id:
            Cart.objects.filter(user=request.user, table=table, item_id=item_id).delete()
            return success_response(message="Item removed from cart.")
        else:
            Cart.objects.filter(user=request.user, table=table).delete()
            return success_response(message="Cart cleared.")


# ─────────────────────── Order Views ───────────────────────

class PlaceOrderView(APIView):
    """Place order from current cart items."""
    permission_classes = [IsAuthenticatedUserCustom]

    def post(self, request):
        qr_token = request.data.get("qr_token", "").strip()
        if not qr_token:
            return error_response("qr_token is required.", "MISSING_QR_TOKEN")

        try:
            table = Table.objects.get(qr_token=qr_token, is_active=True)
        except Table.DoesNotExist:
            return error_response("Invalid table.", "INVALID_TABLE", 404)

        cart_items = (
            Cart.objects
            .filter(user=request.user, table=table)
            .select_related('item')
        )
        if not cart_items.exists():
            return error_response("Your cart is empty.", "EMPTY_CART")

        with transaction.atomic():
            total = sum(ci.line_total() for ci in cart_items)
            order = Order.objects.create(
                table=table, user=request.user, total_amount=total
            )
            order_items = [
                OrderItem(
                    order=order,
                    item=ci.item,
                    quantity=ci.quantity,
                    price=float(ci.item.price),
                )
                for ci in cart_items
            ]
            OrderItem.objects.bulk_create(order_items)
            cart_items.delete()

        broadcast_order_update(table.table_number)

        return success_response(
            {"order_number": order.order_number, "total_amount": total},
            "Order placed successfully.",
            201,
        )


class OrderDetailView(APIView):
    """Get order details by order_number."""
    permission_classes = [IsAuthenticatedUserCustom]

    def get(self, request, order_number):
        try:
            order = (
                Order.objects
                .select_related('table', 'user')
                .prefetch_related('items__item')
                .get(order_number=order_number, user=request.user)
            )
        except Order.DoesNotExist:
            return error_response("Order not found.", "ORDER_NOT_FOUND", 404)
        return success_response(serialize_order(order))


class UserOrderHistoryView(APIView):
    """Customer order history."""
    permission_classes = [IsAuthenticatedUserCustom]

    def get(self, request):
        orders = (
            Order.objects
            .filter(user=request.user)
            .select_related('table')
            .prefetch_related('items__item')
        )
        return success_response([serialize_order(o) for o in orders])


# ─────────────────────── Admin Order Views ───────────────────────

class AdminTableOrdersView(APIView):
    """Admin: get all active orders for a table."""
    permission_classes = [IsAdminUserCustom]

    def get(self, request, table_number):
        try:
            table = Table.objects.get(table_number=table_number)
        except Table.DoesNotExist:
            return error_response("Table not found.", "TABLE_NOT_FOUND", 404)

        orders = (
            Order.objects
            .filter(table=table, status__in=['pending', 'preparing', 'served'])
            .select_related('user')
            .prefetch_related('items__item')
        )
        return success_response([serialize_order(o) for o in orders])


class AdminOrderStatusView(APIView):
    """Admin: update order status."""
    permission_classes = [IsAdminUserCustom]

    def patch(self, request, order_number):
        new_status = request.data.get("status", "").strip()
        valid_statuses = ['pending', 'preparing', 'served', 'paid']
        if new_status not in valid_statuses:
            return error_response(f"Status must be one of {valid_statuses}.", "INVALID_STATUS")

        try:
            order = Order.objects.select_related('table').get(order_number=order_number)
        except Order.DoesNotExist:
            return error_response("Order not found.", "ORDER_NOT_FOUND", 404)

        order.status = new_status
        order.save()
        broadcast_order_update(order.table.table_number)
        return success_response({"order_number": order.order_number, "status": order.status}, "Status updated.")
