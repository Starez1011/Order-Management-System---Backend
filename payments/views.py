"""Payments app views — atomic payment processing with loyalty."""
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Payment, PaymentRequest
from .utils import (
    get_system_config,
    calculate_discount,
    calculate_points_earned,
    validate_points_redemption,
)
from orders.models import Order
from tables.models import TableSession
from accounts.permissions import IsAuthenticatedUserCustom, IsAdminUserCustom


def success_response(data=None, message="Success", http_status=200):
    return Response({"success": True, "message": message, "data": data if data is not None else {}}, status=http_status)


def error_response(message, error_code="ERROR", http_status=400):
    return Response({"success": False, "message": message, "error_code": error_code}, status=http_status)


class PaymentPreviewView(APIView):
    """
    Customer: preview bill before paying.
    Pass points_to_use to see discount applied.
    """
    permission_classes = [IsAuthenticatedUserCustom]

    def post(self, request):
        order_number = request.data.get("order_number", "").strip()
        points_to_use = float(request.data.get("points_to_use", 0))

        try:
            if request.user.is_staff:
                order = Order.objects.get(order_number=order_number)
            else:
                order = Order.objects.get(order_number=order_number, user=request.user)
        except Order.DoesNotExist:
            return error_response("Order not found.", "ORDER_NOT_FOUND", 404)

        if order.status == 'paid':
            return error_response("Order is already paid.", "ALREADY_PAID")

        config = get_system_config()
        
        from accounts.models import CustomUser
        payer_phone = request.data.get("payer_phone_number", "").strip()
        if payer_phone:
            user, _ = CustomUser.objects.get_or_create(
                phone_number=payer_phone,
                defaults={'first_name': 'Walk-in', 'last_name': 'Customer', 'is_verified': False}
            )
        else:
            user = order.user

        err = validate_points_redemption(points_to_use, user.loyalty_points, order.total_amount, config.point_value)
        if err:
            return error_response(err, "INVALID_REDEMPTION")

        discount = calculate_discount(points_to_use, config.point_value)
        cash_needed = round(order.total_amount - discount, 2)
        points_earned = calculate_points_earned(cash_needed, config.loyalty_percentage)

        return success_response({
            "order_number": order.order_number,
            "total_amount": order.total_amount,
            "available_points": user.loyalty_points,
            "point_value": config.point_value,
            "points_to_use": points_to_use,
            "discount_amount": discount,
            "cash_payable": max(cash_needed, 0),
            "points_to_earn": points_earned,
            "customer_name": f"{user.first_name} {user.last_name}".strip()
        })


class TableProcessPaymentView(APIView):
    """
    Admin confirms payment for a table.
    Atomically: mark all active orders as paid -> add earned points to payer.
    """
    permission_classes = [IsAdminUserCustom]

    def post(self, request):
        table_number = request.data.get("table_number", "")
        if isinstance(table_number, str): table_number = table_number.strip()
        order_number = request.data.get("order_number", "")
        if isinstance(order_number, str): order_number = order_number.strip()
        payer_phone = request.data.get("payer_phone_number", "")
        if isinstance(payer_phone, str): payer_phone = payer_phone.strip()
        payment_method = request.data.get("payment_method", "cash")
        if isinstance(payment_method, str): payment_method = payment_method.strip()
        
        try:
            points_used = float(request.data.get("points_used", 0))
        except (TypeError, ValueError):
            points_used = 0.0

        if not table_number and not order_number:
            return error_response("table_number or order_number is required.", "MISSING_FIELDS")

        from tables.models import Table
        from accounts.models import CustomUser

        orders = None
        table = None

        if order_number:
            try:
                order = Order.objects.get(order_number=order_number, payment_status='pending')
                orders = [order]
                table = order.table
                table_number = table.table_number
            except Order.DoesNotExist:
                return error_response("Pending order not found.", "ORDER_NOT_FOUND", 404)
        else:
            try:
                table = Table.objects.get(table_number=table_number)
            except Exception:
                return error_response("Table not found.", "TABLE_NOT_FOUND", 404)
            orders = list(Order.objects.filter(table=table, payment_status='pending'))
            if not orders:
                return error_response("No pending orders found for this table.", "NO_ORDERS")

        total_amount = sum(order.total_amount for order in orders)

        config = get_system_config()
        points_earned = 0.0
        user = None
        discount_amount = 0.0

        with transaction.atomic():
            # If we are processing a specific order, that order has a user.
            if len(orders) == 1 and not payer_phone:
                user = orders[0].user
            elif payer_phone:
                user, created = CustomUser.objects.get_or_create(
                    phone_number=payer_phone,
                    defaults={'first_name': 'Walk-in', 'last_name': 'Customer', 'is_verified': False}
                )

            if user and points_used > 0:
                err = validate_points_redemption(points_used, user.loyalty_points, total_amount, config.point_value)
                if err:
                    return error_response(err, "INVALID_REDEMPTION")
                
                discount_amount = calculate_discount(points_used, config.point_value)
                user.loyalty_points = round(user.loyalty_points - points_used, 2)
                user.save(update_fields=['loyalty_points'])

            cash_needed = round(max(total_amount - discount_amount, 0), 2)
            
            if user:
                points_earned = calculate_points_earned(cash_needed, config.loyalty_percentage)
                user.loyalty_points = round(user.loyalty_points + points_earned, 2)
                user.save(update_fields=['loyalty_points'])

            if not user:
                user = request.user

            for order in orders:
                if user and (not order.user or order.user.is_staff or order.user.phone_number == "0000000000"):
                    order.user = user
                order.payment_status = 'completed'
                order.payment_method = payment_method
                order.save(update_fields=['payment_status', 'payment_method', 'user'])

            payment = Payment.objects.create(
                table=table,
                user=user,
                points_used=points_used,
                discount_amount=discount_amount,
                cash_paid=cash_needed,
                final_amount=cash_needed,
                points_earned=points_earned,
            )
            payment.orders.set(orders)

            from accounts.models import Notification
            if points_used > 0:
                Notification.objects.create(
                    user=user,
                    title="Points Redeemed",
                    message=f"You redeemed {points_used} loyalty points to pay for your order."
                )
            if points_earned > 0:
                Notification.objects.create(
                    user=user,
                    title="Points Earned",
                    message=f"You earned {points_earned} loyalty points from your recent order."
                )

            # Check if there are any remaining pending orders for this table
            remaining_pending = Order.objects.filter(table=table, payment_status='pending').exists()
            if not remaining_pending:
                TableSession.objects.filter(table=table, is_active=True).update(is_active=False)

        return success_response({
            "table_number": table_number,
            "total_amount": total_amount,
            "cash_paid": cash_needed,
            "points_earned": points_earned,
            "payer_phone": user.phone_number if user else None,
        }, "Table payment processed successfully.")


class PaymentHistoryView(APIView):
    """Admin: view payment history grouped by table."""
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        payments = (
            Payment.objects
            .select_related('table', 'user')
            .prefetch_related('orders', 'orders__items', 'orders__items__item', 'orders__user')
            .order_by('-created_at')[:100]
        )
        data = []
        for p in payments:
            orders_data = []
            for order in p.orders.all():
                items_data = []
                for order_item in order.items.all():
                    items_data.append({
                        "name": order_item.item.name,
                        "quantity": order_item.quantity,
                        "price": order_item.price,
                        "line_total": order_item.line_total()
                    })
                orders_data.append({
                    "order_number": order.order_number,
                    "placed_by": order.user.get_full_name(),
                    "placed_at": order.created_at.isoformat(),
                    "total_amount": order.total_amount,
                    "items": items_data
                })

            data.append({
                "table_number": p.table.table_number if p.table else "N/A",
                "checkout_time": p.created_at.isoformat(),
                "paid_by": p.user.get_full_name(),
                "payer_phone": p.user.phone_number,
                "total_amount": sum(o.total_amount for o in p.orders.all()),
                "payment_method": p.orders.first().payment_method if p.orders.exists() else None,
                "points_used": p.points_used,
                "discount_amount": p.discount_amount,
                "cash_paid": p.cash_paid,
                "points_earned": p.points_earned,
                "orders": orders_data
            })
            
        return success_response(data)

class AdminGeneratePaymentQRView(APIView):
    """Admin creates a payment request QR asking for X points for a Table."""
    permission_classes = [IsAdminUserCustom]

    def post(self, request):
        table_number = request.data.get("table_number")
        
        if not table_number:
            return error_response("table_number is required.", "INVALID_INPUT")

        try:
            from tables.models import Table
            table = Table.objects.get(table_number=table_number)
        except Exception:
            return error_response("Table not found.", "TABLE_NOT_FOUND", 404)

        orders = Order.objects.filter(table=table, payment_status='pending')
        if not orders.exists():
            return error_response("No pending orders found for this table.", "NO_ORDERS")

        amount_requested = sum(order.total_amount for order in orders)
        if amount_requested <= 0:
            return error_response("Total amount is zero.", "ZERO_AMOUNT")

        config = get_system_config()
        points_required = round(amount_requested / config.point_value, 2)

        PaymentRequest.objects.filter(table=table, is_active=True).update(is_active=False)

        pr = PaymentRequest.objects.create(
            table=table,
            amount_requested=amount_requested,
            points_required=points_required
        )
        return success_response({
            "qr_token": str(pr.id),
            "amount_requested": amount_requested,
            "points_required": points_required,
            "table_number": table_number,
        })


class CustomerProcessQRPaymentView(APIView):
    """Customer scans the payment QR. Deducts points, marks table orders as paid."""
    permission_classes = [IsAuthenticatedUserCustom]

    def post(self, request):
        qr_token = request.data.get("qr_token", "").strip()
        transaction_password = request.data.get("transaction_password", "").strip()

        user = request.user
        
        biometric_verified = request.data.get("biometric_verified", False)
        if str(biometric_verified).lower() == 'true':
            biometric_verified = True
            
        if not biometric_verified and not user.check_transaction_password(transaction_password):
            return error_response("Invalid transaction password or biometric.", "INVALID_PASSWORD", 401)

        try:
            pr = PaymentRequest.objects.select_related('table').get(id=qr_token, is_active=True)
        except (PaymentRequest.DoesNotExist, ValueError):
            return error_response("Invalid or expired payment QR request.", "INVALID_QR", 404)

        table = pr.table
        orders = Order.objects.filter(table=table, payment_status='pending')
        
        if not orders.exists():
            return error_response("Orders are already paid.", "ALREADY_PAID")

        if user.loyalty_points < pr.points_required:
            return error_response(f"Insufficient points. You need {pr.points_required}.", "INSUFFICIENT_POINTS")

        with transaction.atomic():
            user.loyalty_points = round(user.loyalty_points - pr.points_required, 2)
            user.save(update_fields=['loyalty_points'])

            pr.is_active = False
            pr.save()

            for order in orders:
                order.payment_status = 'completed'
                order.payment_method = 'loyalty_points'
                order.save(update_fields=['payment_status', 'payment_method'])

            payment = Payment.objects.create(
                table=table,
                user=user,
                points_used=pr.points_required,
                discount_amount=pr.amount_requested,
                cash_paid=0.0,
                final_amount=0.0,
                points_earned=0.0,
            )
            payment.orders.set(orders)

            from accounts.models import Notification
            Notification.objects.create(
                user=user,
                title="Points Redeemed",
                message=f"You redeemed {pr.points_required} loyalty points to pay for your order via QR."
            )

            TableSession.objects.filter(table=table, is_active=True).update(is_active=False)

        return success_response({
            "table_number": table.table_number,
            "message": f"Successfully paid {pr.points_required} points.",
            "remaining_points": user.loyalty_points
        })
