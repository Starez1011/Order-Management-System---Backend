"""Payments app views — atomic payment processing with loyalty."""
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from payments.models import Payment, PaymentRequest
from payments.utils import (
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
        
        user_points = 0.0
        customer_name = "Walk-in Customer"

        if payer_phone:
            try:
                user = CustomUser.objects.get(phone_number=payer_phone)
                user_points = user.loyalty_points
                customer_name = f"{user.first_name} {user.last_name}".strip()
            except CustomUser.DoesNotExist:
                user_points = 0.0
                customer_name = "Not Found (Walk-in)"
        elif order.user:
            user_points = order.user.loyalty_points
            customer_name = f"{order.user.first_name} {order.user.last_name}".strip()

        err = validate_points_redemption(points_to_use, user_points, order.total_amount, config.point_value)
        if err:
            return error_response(err, "INVALID_REDEMPTION")

        discount = calculate_discount(points_to_use, config.point_value)
        cash_needed = round(order.total_amount - discount, 2)
        points_earned = calculate_points_earned(cash_needed, config.loyalty_percentage)

        return success_response({
            "order_number": order.order_number,
            "total_amount": order.total_amount,
            "available_points": user_points,
            "point_value": config.point_value,
            "points_to_use": points_to_use,
            "discount_amount": discount,
            "cash_payable": max(cash_needed, 0),
            "points_to_earn": points_earned,
            "customer_name": customer_name
        }, "Payment preview generated.")


class TableGroupPreviewView(APIView):
    """
    Admin: get a combined billing preview for ALL pending orders at a table.
    Returns:
      - combined_total
      - per-order breakdown with user info (for phone update / loyalty mapping)
      - flat combined items list (for print bill)
    """
    permission_classes = [IsAdminUserCustom]

    def get(self, request, table_number):
        from tables.models import Table
        from accounts.models import CustomUser

        try:
            table = Table.objects.get(table_number=table_number, admin=request.user)
        except Table.DoesNotExist:
            return error_response("Table not found.", "TABLE_NOT_FOUND", 404)

        pending_orders = (
            Order.objects
            .filter(table=table, payment_status='pending')
            .exclude(status='cancelled')
            .select_related('user')
            .prefetch_related('items__item')
        )

        if not pending_orders.exists():
            return error_response("No pending orders for this table.", "NO_ORDERS", 404)

        combined_total = 0.0
        orders_info = []
        combined_items = {}  # name -> {name, qty, price, line_total}

        for order in pending_orders:
            combined_total += order.total_amount

            # Determine if user is a real registered app user (not walk-in / staff)
            user = order.user
            is_registered = (
                user is not None and
                not user.is_staff and
                user.phone_number != "0000000000" and
                user.is_verified
            )

            orders_info.append({
                "order_number": order.order_number,
                "user_name": user.get_full_name() if user else "Walk-in",
                "phone_number": user.phone_number if user else "",
                "is_registered": is_registered,
                "order_total": order.total_amount,
                "status": order.status,
            })

            # Accumulate combined items
            for oi in order.items.all():
                key = oi.item.name
                if key in combined_items:
                    combined_items[key]["quantity"] += oi.quantity
                    combined_items[key]["line_total"] = round(
                        combined_items[key]["line_total"] + oi.line_total(), 2
                    )
                else:
                    combined_items[key] = {
                        "name": oi.item.name,
                        "quantity": oi.quantity,
                        "price": oi.price,
                        "line_total": round(oi.line_total(), 2),
                    }

        config = get_system_config()

        return success_response({
            "table_number": table_number,
            "combined_total": round(combined_total, 2),
            "order_count": len(orders_info),
            "orders": orders_info,
            "combined_items": list(combined_items.values()),
            "point_value": config.point_value,
            "loyalty_percentage": config.loyalty_percentage,
        })


class TableProcessPaymentView(APIView):
    """
    Admin confirms payment for a table.

    Supports two modes:
      1. Single order payment (order_number provided) — legacy, unchanged.
      2. Full table payment (table_number provided with optional per_user_phones list)
         Points are distributed PROPORTIONALLY to each registered user based on their
         share of the total bill.

    per_user_phones: list of {order_number, phone_number} objects.
      If provided, the server resolves/creates a user for each order using that phone.
      Phone numbers for walk-in / unregistered orders can be omitted.
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
        per_user_phones = request.data.get("per_user_phones", [])  # [{order_number, phone_number}]

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

        # ── Single order payment (legacy) ──
        if order_number and not per_user_phones:
            try:
                order = Order.objects.get(order_number=order_number, payment_status='pending', admin=request.user)
                orders = [order]
                table = order.table
                table_number = table.table_number
            except Order.DoesNotExist:
                return error_response("Pending order not found.", "ORDER_NOT_FOUND", 404)
        else:
            # ── Table-wide payment ──
            try:
                table = Table.objects.get(table_number=table_number, admin=request.user)
            except Exception:
                return error_response("Table not found.", "TABLE_NOT_FOUND", 404)
            orders = list(Order.objects.filter(table=table, payment_status='pending').exclude(status='cancelled'))
            if not orders:
                return error_response("No pending orders found for this table.", "NO_ORDERS")

        total_amount = sum(order.total_amount for order in orders)
        config = get_system_config()

        # Build order->user mapping from per_user_phones override
        phone_map = {}  # order_number -> phone_number
        if per_user_phones and isinstance(per_user_phones, list):
            for entry in per_user_phones:
                if isinstance(entry, dict):
                    on = entry.get("order_number", "").strip()
                    ph = entry.get("phone_number", "").strip()
                    if on and ph:
                        phone_map[on] = ph

        with transaction.atomic():
            # ── Resolve user for each order ──
            order_user_map = {}  # order -> resolved CustomUser or None
            for order in orders:
                phone = phone_map.get(order.order_number, "")
                if phone:
                    user_obj, _ = CustomUser.objects.get_or_create(
                        phone_number=phone,
                        defaults={'first_name': 'Walk-in', 'last_name': 'Customer', 'is_verified': False}
                    )
                    order_user_map[order.order_number] = user_obj
                elif order.user and not order.user.is_staff and order.user.phone_number != "0000000000":
                    order_user_map[order.order_number] = order.user
                else:
                    order_user_map[order.order_number] = None

            # ── Single-payer legacy path (1 order or explicit payer_phone) ──
            if len(orders) == 1 and not per_user_phones:
                single_user = order_user_map.get(orders[0].order_number)
                if payer_phone and not single_user:
                    single_user, _ = CustomUser.objects.get_or_create(
                        phone_number=payer_phone,
                        defaults={'first_name': 'Walk-in', 'last_name': 'Customer', 'is_verified': False}
                    )

                discount_amount = 0.0
                if single_user and points_used > 0:
                    err = validate_points_redemption(points_used, single_user.loyalty_points, total_amount, config.point_value)
                    if err:
                        return error_response(err, "INVALID_REDEMPTION")
                    discount_amount = calculate_discount(points_used, config.point_value)
                    single_user.loyalty_points = round(single_user.loyalty_points - points_used, 2)
                    single_user.save(update_fields=['loyalty_points'])

                cash_needed = round(max(total_amount - discount_amount, 0), 2)
                points_earned = 0.0
                if single_user:
                    points_earned = calculate_points_earned(cash_needed, config.loyalty_percentage)
                    single_user.loyalty_points = round(single_user.loyalty_points + points_earned, 2)
                    single_user.save(update_fields=['loyalty_points'])

                payer = single_user or request.user
                for order in orders:
                    if single_user and (not order.user or order.user.is_staff or order.user.phone_number == "0000000000"):
                        order.user = single_user
                    order.payment_status = 'completed'
                    order.payment_method = payment_method
                    order.save(update_fields=['payment_status', 'payment_method', 'user'])

                payment = Payment.objects.create(
                    admin=request.user,
                    table=table,
                    user=payer,
                    points_used=points_used,
                    discount_amount=discount_amount,
                    cash_paid=cash_needed,
                    final_amount=cash_needed,
                    points_earned=points_earned,
                )
                payment.orders.set(orders)

                from accounts.models import Notification
                if single_user:
                    if points_used > 0:
                        Notification.objects.create(
                            user=single_user,
                            title="Points Redeemed",
                            message=f"You redeemed {points_used} loyalty points for your order."
                        )
                    if points_earned > 0:
                        Notification.objects.create(
                            user=single_user,
                            title="Points Earned",
                            message=f"You earned {points_earned} loyalty points from your order."
                        )

                remaining_pending = Order.objects.filter(table=table, payment_status='pending').exists()
                if not remaining_pending:
                    TableSession.objects.filter(table=table, is_active=True).update(is_active=False)

                return success_response({
                    "table_number": table_number,
                    "total_amount": total_amount,
                    "cash_paid": cash_needed,
                    "points_earned": points_earned,
                    "payer_phone": payer.phone_number if payer else None,
                }, "Payment processed successfully.")

            # ── Multi-order proportional loyalty distribution ──
            # Global discount from points (optional, applies to total)
            discount_amount = 0.0
            points_deducted_from = None
            if points_used > 0 and payer_phone:
                try:
                    deduct_user = CustomUser.objects.get(phone_number=payer_phone)
                    err = validate_points_redemption(points_used, deduct_user.loyalty_points, total_amount, config.point_value)
                    if err:
                        return error_response(err, "INVALID_REDEMPTION")
                    discount_amount = calculate_discount(points_used, config.point_value)
                    deduct_user.loyalty_points = round(deduct_user.loyalty_points - points_used, 2)
                    deduct_user.save(update_fields=['loyalty_points'])
                    points_deducted_from = deduct_user
                except CustomUser.DoesNotExist:
                    return error_response("Payer not found for points redemption.", "USER_NOT_FOUND", 404)

            cash_needed = round(max(total_amount - discount_amount, 0), 2)
            total_points_to_earn = calculate_points_earned(cash_needed, config.loyalty_percentage)

            # Distribute points proportionally
            from accounts.models import Notification
            points_distributed = {}  # user_id -> points

            registered_orders = [
                (order, order_user_map[order.order_number])
                for order in orders
                if order_user_map.get(order.order_number) is not None
            ]
            registered_total = sum(o.total_amount for o, u in registered_orders)

            for order, user_obj in registered_orders:
                if user_obj and registered_total > 0:
                    share = order.total_amount / registered_total
                    user_points_earned = round(total_points_to_earn * share, 2)
                    uid = user_obj.pk
                    if uid not in points_distributed:
                        points_distributed[uid] = {"user": user_obj, "points": 0.0, "order_total": 0.0}
                    points_distributed[uid]["points"] = round(points_distributed[uid]["points"] + user_points_earned, 2)
                    points_distributed[uid]["order_total"] = round(points_distributed[uid]["order_total"] + order.total_amount, 2)

            # Apply points to each user
            for uid, info in points_distributed.items():
                u = info["user"]
                u.loyalty_points = round(u.loyalty_points + info["points"], 2)
                u.save(update_fields=['loyalty_points'])
                if info["points"] > 0:
                    Notification.objects.create(
                        user=u,
                        title="Points Earned",
                        message=f"You earned {info['points']} loyalty points from your order at Table {table_number}."
                    )

            if points_deducted_from and points_used > 0:
                Notification.objects.create(
                    user=points_deducted_from,
                    title="Points Redeemed",
                    message=f"You redeemed {points_used} loyalty points for the table bill at Table {table_number}."
                )

            # Mark all orders paid and update user if phone was provided
            for order in orders:
                resolved_user = order_user_map.get(order.order_number)
                if resolved_user and (not order.user or order.user.is_staff or order.user.phone_number == "0000000000"):
                    order.user = resolved_user
                order.payment_status = 'completed'
                order.payment_method = payment_method
                order.save(update_fields=['payment_status', 'payment_method', 'user'])

            # Use first resolved user as payment record user (or admin as fallback)
            primary_user = (
                points_deducted_from or
                next((u for _, u in registered_orders if u is not None), None) or
                request.user
            )

            payment = Payment.objects.create(
                admin=request.user,
                table=table,
                user=primary_user,
                points_used=points_used,
                discount_amount=discount_amount,
                cash_paid=cash_needed,
                final_amount=cash_needed,
                points_earned=total_points_to_earn,
            )
            payment.orders.set(orders)

            TableSession.objects.filter(table=table, is_active=True).update(is_active=False)

            # Build per-user summary for response
            per_user_summary = [
                {
                    "user_name": info["user"].get_full_name(),
                    "phone": info["user"].phone_number,
                    "order_total": info["order_total"],
                    "points_earned": info["points"],
                }
                for info in points_distributed.values()
            ]

        return success_response({
            "table_number": table_number,
            "total_amount": total_amount,
            "cash_paid": cash_needed,
            "discount_amount": discount_amount,
            "total_points_earned": total_points_to_earn,
            "per_user_summary": per_user_summary,
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
