"""Orders app views — Cart and Order management."""
import json
from django.db import transaction
from django.utils import timezone
from datetime import timedelta
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
    payment = order.payment_records.first() if hasattr(order, 'payment_records') else None
    return {
        "order_number": order.order_number,
        "table_number": order.table.table_number if order.table else 'N/A',
        "user_name": order.user.get_full_name(),
        "phone_number": order.user.phone_number,
        "status": order.status,
        "payment_status": order.payment_status,
        "total_amount": order.total_amount,
        "created_at": order.created_at.isoformat(),
        "points_earned": payment.points_earned if payment else 0.0,
        "points_used": payment.points_used if payment else 0.0,
        "paid_with_points": (payment.points_used > 0) if payment else False,
        "items": [
            {
                "item_id": oi.item.id,
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
        if qr_token.upper().startswith("CAFE_TABLE:"):
            qr_token = qr_token[len("CAFE_TABLE:"):]
            
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
        if qr_token.upper().startswith("CAFE_TABLE:"):
            qr_token = qr_token[len("CAFE_TABLE:"):]
            
        item_id = request.data.get("item_id")
        quantity = request.data.get("quantity", 1)

        if not all([qr_token, item_id]):
            return error_response("qr_token and item_id are required.", "MISSING_FIELDS")

        try:
            quantity = int(quantity)
        except (TypeError, ValueError):
            return error_response("Quantity must be an integer.", "INVALID_QUANTITY")

        try:
            table = Table.objects.get(qr_token=qr_token, is_active=True)
        except Table.DoesNotExist:
            return error_response("Invalid table.", "INVALID_TABLE", 404)

        try:
            item = MenuItem.objects.get(pk=item_id, is_available=True)
        except MenuItem.DoesNotExist:
            return error_response("Item not found or unavailable.", "ITEM_NOT_FOUND", 404)

        cart_item, created = Cart.objects.get_or_create(
            user=request.user, table=table, item=item,
            defaults={"quantity": quantity}
        )
        
        if created:
            if cart_item.quantity <= 0:
                cart_item.delete()
                return error_response("Cannot add negative or zero quantity of a new item.", "INVALID_QUANTITY")
        else:
            cart_item.quantity += quantity
            if cart_item.quantity <= 0:
                cart_item.delete()
                return success_response({"item_id": item.id, "quantity": 0}, "Item removed from cart.", 200)
            else:
                cart_item.save(update_fields=['quantity'])
            
        msg = "Item added to cart." if created else "Cart item updated."
        return success_response({"item_id": item.id, "quantity": cart_item.quantity}, msg, 201 if created else 200)

    def delete(self, request):
        """Remove a single item or clear entire cart."""
        qr_token = request.data.get("qr_token", "").strip()
        if qr_token.upper().startswith("CAFE_TABLE:"):
            qr_token = qr_token[len("CAFE_TABLE:"):]
            
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
        if qr_token.upper().startswith("CAFE_TABLE:"):
            qr_token = qr_token[len("CAFE_TABLE:"):]
            
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
                table=table, user=request.user, total_amount=total, status='order_sent'
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
        days_str = request.query_params.get('days')
        days = None
        if days_str:
            try:
                days = int(days_str)
            except ValueError:
                return error_response("Invalid 'days' parameter. Must be an integer.", "INVALID_PARAM")

        orders_query = Order.objects.filter(user=request.user)

        if days is not None:
            # Prevent excessive historical fetching
            if days > 365:
                days = 365
            cutoff = timezone.now() - timedelta(days=days)
            orders_query = orders_query.filter(created_at__gte=cutoff)

        orders = (
            orders_query
            .select_related('table')
            .prefetch_related('items__item', 'payment_records')
            .order_by('-created_at')
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
            .filter(table=table, status__in=['order_sent', 'order_received', 'order_served'])
            .select_related('user')
            .prefetch_related('items__item')
        )
        return success_response([serialize_order(o) for o in orders])


class AdminOrderStatusView(APIView):
    """Admin: update order status."""
    permission_classes = [IsAdminUserCustom]

    def patch(self, request, order_number):
        new_status = request.data.get("status", "").strip()
        valid_statuses = ['order_sent', 'order_received', 'order_served', 'cancelled', 'paid']
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

class MyActiveOrdersView(APIView):
    """Customer: get all active, non-paid orders."""
    permission_classes = [IsAuthenticatedUserCustom]

    def get(self, request):
        orders = (
            Order.objects
            .filter(user=request.user, status__in=['order_sent', 'order_received', 'order_served'])
            .select_related('table')
            .prefetch_related('items__item')
        )
        return success_response([serialize_order(o) for o in orders])

class CancelOrderView(APIView):
    """Cancel an order. Customer can only cancel 'order_sent'. Admin can cancel any active order."""
    permission_classes = [IsAuthenticatedUserCustom]

    def post(self, request, order_number):
        try:
            order = Order.objects.select_related('table').get(order_number=order_number)
        except Order.DoesNotExist:
            return error_response("Order not found.", "ORDER_NOT_FOUND", 404)

        if not request.user.is_staff and order.user != request.user:
            return error_response("You don't have permission to cancel this order.", "PERMISSION_DENIED", 403)

        if order.status == 'cancelled':
            return error_response("Order is already cancelled.", "ALREADY_CANCELLED")
        
        if order.status == 'paid' or order.status == 'paid_by_points':
            return error_response("Cannot cancel a paid order.", "CANNOT_CANCEL")

        if not request.user.is_staff and order.status != 'order_sent':
            return error_response("Order has already been received by kitchen. Please contact staff to cancel.", "CANNOT_CANCEL_RECEIVED")

        order.status = 'cancelled'
        order.save(update_fields=['status'])
        broadcast_order_update(order.table.table_number)

        return success_response({"order_number": order.order_number, "status": order.status}, "Order cancelled successfully.")

class UserEditOrderView(APIView):
    """Customer edits an existing 'order_sent' order."""
    permission_classes = [IsAuthenticatedUserCustom]

    @transaction.atomic
    def patch(self, request, order_number):
        try:
            order = Order.objects.get(order_number=order_number, user=request.user)
        except Order.DoesNotExist:
            return error_response("Order not found.", "ORDER_NOT_FOUND", 404)

        if order.status != 'order_sent':
            return error_response("Cannot edit order once it is received by kitchen.", "CANNOT_EDIT_ORDER")

        items_data = request.data.get("items", [])
        if not items_data or not isinstance(items_data, list):
            return error_response("Items are required and must be a list.", "INVALID_ITEMS")

        valid_items = []
        for item_data in items_data:
            try:
                menu_item = MenuItem.objects.get(pk=item_data["item_id"])
            except MenuItem.DoesNotExist:
                return error_response(f"Menu item not found.", "ITEM_NOT_FOUND")
            
            qty = int(item_data.get("quantity", 1))
            if qty > 0:
                valid_items.append({"menu_item": menu_item, "quantity": qty})

        if not valid_items:
            return error_response("Order must have valid items.", "EMPTY_ORDER")

        order.items.all().delete()
        total = 0.0
        
        for v_item in valid_items:
            OrderItem.objects.create(
                order=order,
                item=v_item["menu_item"],
                quantity=v_item["quantity"],
                price=v_item["menu_item"].price
            )
            total += float(v_item["menu_item"].price) * v_item["quantity"]
        
        order.total_amount = total
        order.save()

        broadcast_order_update(order.table.table_number)
        return success_response({"order_number": order.order_number, "total_amount": order.total_amount}, "Order updated.")
