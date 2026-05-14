"""Accounts app views — Register, OTP, Login, Profile."""
from django.utils import timezone
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework_simplejwt.tokens import RefreshToken

from accounts.models import CustomUser, OTPRecord, Notification
from accounts.utils import generate_otp, send_otp_sms
from accounts.permissions import IsAuthenticatedUserCustom, IsAdminUserCustom, IsSuperAdminUserCustom
from django.conf import settings


def success_response(data=None, message="Success", http_status=200):
    return Response({"success": True, "message": message, "data": data if data is not None else {}}, status=http_status)


def error_response(message, error_code="ERROR", http_status=400):
    return Response({"success": False, "message": message, "error_code": error_code}, status=http_status)


def get_tokens_for_user(user):
    refresh = RefreshToken.for_user(user)
    return {
        "refresh": str(refresh),
        "access": str(refresh.access_token),
    }


from django.utils.crypto import get_random_string

class CheckPhoneView(APIView):
    """Check if phone number exists. If not, generate unverified user and send OTP."""

    def post(self, request):
        phone_number = request.data.get("phone_number", "").strip()
        if not phone_number:
            return error_response("Phone number is required.", "MISSING_PHONE")

        try:
            user = CustomUser.objects.get(phone_number=phone_number)
            if user.is_verified:
                return success_response({"exists": True}, "User exists and verified.")
            else:
                recent = OTPRecord.objects.filter(
                    user=user, is_used=False,
                    created_at__gte=timezone.now() - timezone.timedelta(minutes=1)
                ).exists()
                if recent:
                    return error_response("Please wait before requesting another OTP.", "OTP_RATE_LIMIT", 429)

                otp_code = generate_otp(settings.OTP_DIGITS)
                OTPRecord.objects.create(user=user, code=otp_code)
                send_otp_sms(phone_number, otp_code)
                return success_response({"exists": False}, "User unverified, OTP sent.")
                
        except CustomUser.DoesNotExist:
            with transaction.atomic():
                user = CustomUser.objects.create_user(
                    phone_number=phone_number,
                    password=get_random_string(10),
                    first_name="",
                    last_name="",
                    is_verified=False,
                )
                otp_code = generate_otp(settings.OTP_DIGITS)
                OTPRecord.objects.create(user=user, code=otp_code)
                send_otp_sms(phone_number, otp_code)
            return success_response({"exists": False}, "New user created, OTP sent.")


class RegisterFinalizeView(APIView):
    """Finalize registration by setting password and names after OTP is verified."""

    def post(self, request):
        phone_number = request.data.get("phone_number", "").strip()
        password = request.data.get("password", "").strip()
        first_name = request.data.get("first_name", "").strip()
        last_name = request.data.get("last_name", "").strip()

        if not all([phone_number, password, first_name, last_name]):
            return error_response("All fields are required.", "MISSING_FIELDS")

        if len(password) < 6:
            return error_response("Password must be at least 6 characters.", "WEAK_PASSWORD")

        try:
            user = CustomUser.objects.get(phone_number=phone_number)
        except CustomUser.DoesNotExist:
            return error_response("User not found.", "USER_NOT_FOUND", 404)

        if not user.is_verified:
            return error_response("Phone number not verified. Please verify OTP first.", "NOT_VERIFIED", 403)

        user.first_name = first_name
        user.last_name = last_name
        user.set_password(password)
        user.save()

        tokens = get_tokens_for_user(user)
        return success_response(
            {**tokens, "phone_number": user.phone_number},
            "Registration finalized successfully.",
            http_status=201
        )


class SendOTPView(APIView):
    """Resend OTP to an existing unverified user."""

    def post(self, request):
        phone_number = request.data.get("phone_number", "").strip()
        if not phone_number:
            return error_response("Phone number is required.", "MISSING_PHONE")

        try:
            user = CustomUser.objects.get(phone_number=phone_number)
        except CustomUser.DoesNotExist:
            return error_response("User not found.", "USER_NOT_FOUND", 404)

        if user.is_verified:
            return error_response("Account already verified.", "ALREADY_VERIFIED")

        # Rate limit: check if recent OTP exists (last 1 min)
        recent = OTPRecord.objects.filter(
            user=user, is_used=False,
            created_at__gte=timezone.now() - timezone.timedelta(minutes=1)
        ).exists()
        if recent:
            return error_response("Please wait before requesting another OTP.", "OTP_RATE_LIMIT", 429)

        otp_code = generate_otp(settings.OTP_DIGITS)
        OTPRecord.objects.create(user=user, code=otp_code)
        send_otp_sms(phone_number, otp_code)
        return success_response(message="OTP sent successfully.")


class VerifyOTPView(APIView):
    """Verify OTP and activate user account."""

    def post(self, request):
        phone_number = request.data.get("phone_number", "").strip()
        otp_code = request.data.get("otp", "").strip()

        if not all([phone_number, otp_code]):
            return error_response("Phone number and OTP are required.", "MISSING_FIELDS")

        try:
            user = CustomUser.objects.get(phone_number=phone_number)
        except CustomUser.DoesNotExist:
            return error_response("User not found.", "USER_NOT_FOUND", 404)

        otp = OTPRecord.objects.filter(
            user=user, code=otp_code, is_used=False
        ).order_by('-created_at').first()

        if not otp or not otp.is_valid():
            return error_response("Invalid or expired OTP.", "INVALID_OTP")

        with transaction.atomic():
            otp.is_used = True
            otp.save()
            user.is_verified = True
            user.save()

        tokens = get_tokens_for_user(user)
        return success_response(
            {**tokens, "phone_number": user.phone_number},
            "Account verified successfully.",
        )


class LoginView(APIView):
    """Login with phone + password. User must be verified."""

    def post(self, request):
        phone_number = request.data.get("phone_number", "").strip()
        password = request.data.get("password", "").strip()

        if not all([phone_number, password]):
            return error_response("Phone number and password are required.", "MISSING_FIELDS")

        try:
            user = CustomUser.objects.get(phone_number=phone_number)
        except CustomUser.DoesNotExist:
            return error_response("Invalid credentials.", "INVALID_CREDENTIALS", 401)

        if not user.check_password(password):
            return error_response("Invalid credentials.", "INVALID_CREDENTIALS", 401)

        if not user.is_verified:
            return error_response("Account not verified. Please verify via OTP.", "NOT_VERIFIED", 403)

        if not user.is_active:
            return error_response("Account is deactivated.", "ACCOUNT_INACTIVE", 403)

        tokens = get_tokens_for_user(user)
        return success_response({
            **tokens,
            "user": {
                "phone_number": user.phone_number,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "loyalty_points": user.loyalty_points,
                "is_staff": user.is_staff,
                "is_superuser": user.is_superuser,
            }
        }, "Login successful.")


class ProfileView(APIView):
    """Get and update authenticated user profile."""
    permission_classes = [IsAuthenticatedUserCustom]

    def get(self, request):
        user = request.user
        branch_name = None
        
        if user.is_staff and not user.is_superuser:
            from tables.models import CafeLocation
            loc = CafeLocation.objects.filter(admin=user).first()
            if loc:
                branch_name = loc.branch_name

        return success_response({
            "phone_number": user.phone_number,
            "first_name": user.first_name,
            "last_name": user.last_name,
            "loyalty_points": user.loyalty_points,
            "is_verified": user.is_verified,
            "is_superuser": user.is_superuser,
            "branch_name": branch_name,
        })

    def patch(self, request):
        user = request.user
        user.first_name = request.data.get("first_name", user.first_name)
        user.last_name = request.data.get("last_name", user.last_name)
        new_password = request.data.get("new_password", "").strip()
        if new_password:
            if len(new_password) < 6:
                return error_response("Password must be at least 6 characters.", "WEAK_PASSWORD")
            user.set_password(new_password)
        user.save()
        return success_response(message="Profile updated successfully.")


class AdminUserListView(APIView):
    """Admin: list all users."""
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        users = CustomUser.objects.all().order_by('-created_at')
        data = [
            {
                "phone_number": u.phone_number,
                "first_name": u.first_name,
                "last_name": u.last_name,
                "loyalty_points": u.loyalty_points,
                "is_verified": u.is_verified,
                "is_staff": u.is_staff,
                "created_at": u.created_at.isoformat(),
            }
            for u in users
        ]
        return success_response(data)


class SuperAdminStaffManagementView(APIView):
    """Superadmin: manage POS Admin accounts (is_staff=True)."""
    permission_classes = [IsSuperAdminUserCustom]

    def get(self, request):
        """List all admins."""
        staff = CustomUser.objects.filter(is_staff=True).order_by('-created_at')
        return success_response([{
            "id": u.id,
            "phone_number": u.phone_number,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "is_active": u.is_active,
            "is_superuser": u.is_superuser,
            "created_at": u.created_at.isoformat(),
        } for u in staff])
    
    def post(self, request):
        """Create a new POS Admin."""
        phone_number = request.data.get("phone_number", "").strip()
        first_name = request.data.get("first_name", "").strip()
        last_name = request.data.get("last_name", "").strip()
        password = request.data.get("password", "").strip()

        if not all([phone_number, first_name, last_name, password]):
            return error_response("All fields are required.", "MISSING_FIELDS")
        
        if CustomUser.objects.filter(phone_number=phone_number).exists():
            return error_response("Phone number already exists.", "PHONE_EXISTS")

        try:
            with transaction.atomic():
                user = CustomUser.objects.create_user(
                    phone_number=phone_number,
                    password=password,
                    first_name=first_name,
                    last_name=last_name,
                    is_verified=True,
                )
                user.is_staff = True
                user.save()
                
                # Auto-create CafeLocation for the new branch admin
                from tables.models import CafeLocation
                CafeLocation.objects.create(
                    admin=user,
                    restaurant_name="My Cafe",
                    branch_name=f"Branch - {first_name}",
                    name=f"Branch - {first_name}",
                )
                
            return success_response({"id": user.id, "phone_number": phone_number}, "Admin account and branch created.", 201)
        except Exception as e:
            return error_response(str(e), "CREATE_ERROR")

    def patch(self, request, user_id):
        """Toggle an admin's access (deactivate/activate) or reset password."""
        if request.user.id == user_id:
            return error_response("Cannot modify your own superadmin account.", "SELF_ACTION")
            
        try:
            target = CustomUser.objects.get(id=user_id, is_staff=True)
            action = request.data.get("action")
            
            if action == "reset_password":
                target.set_password("admin123")
                target.save()
                return success_response({}, "Password reset to admin123 successfully.")
            
            # Default toggle action
            target.is_active = not target.is_active
            target.save()
            status_text = "activated" if target.is_active else "deactivated"
            return success_response({"is_active": target.is_active}, f"Admin {status_text} successfully.")
        except CustomUser.DoesNotExist:
            return error_response("Admin user not found.", "NOT_FOUND", 404)

    def put(self, request, user_id):
        """Edit an admin's details."""
        if request.user.id == user_id:
            return error_response("Cannot edit your own superadmin account from here.", "SELF_ACTION")
            
        try:
            target = CustomUser.objects.get(id=user_id, is_staff=True)
            phone_number = request.data.get("phone_number", target.phone_number).strip()
            first_name = request.data.get("first_name", target.first_name).strip()
            last_name = request.data.get("last_name", target.last_name).strip()
            
            # Check phone number uniqueness if changed
            if phone_number != target.phone_number and CustomUser.objects.filter(phone_number=phone_number).exists():
                return error_response("Phone number already exists.", "PHONE_EXISTS")
            
            target.phone_number = phone_number
            target.first_name = first_name
            target.last_name = last_name
            target.save()
            return success_response({}, "Admin details updated successfully.")
        except CustomUser.DoesNotExist:
            return error_response("Admin user not found.", "NOT_FOUND", 404)

    def delete(self, request, user_id):
        """Delete an admin account entirely."""
        if request.user.id == user_id:
            return error_response("Cannot delete your own superadmin account.", "SELF_ACTION")
            
        try:
            target = CustomUser.objects.get(id=user_id, is_staff=True)
            target.delete()
            return success_response({}, "Admin account deleted successfully.")
        except CustomUser.DoesNotExist:
            return error_response("Admin user not found.", "NOT_FOUND", 404)


class SetTransactionPasswordView(APIView):
    """Set or update transaction password."""
    permission_classes = [IsAuthenticatedUserCustom]

    def post(self, request):
        user = request.user
        password = request.data.get("transaction_password", "").strip()
        if not password or len(password) < 4:
            return error_response("Password must be at least 4 characters.", "WEAK_PASSWORD")
        
        user.set_transaction_password(password)
        user.save()
        return success_response(message="Transaction password set successfully.")


class TransferPointsView(APIView):
    """Transfer loyalty points to another user."""
    permission_classes = [IsAuthenticatedUserCustom]

    def post(self, request):
        sender = request.user
        target_phone = request.data.get("phone_number", "").strip()
        try:
            points_to_transfer = float(request.data.get("points", 0))
        except ValueError:
            return error_response("Points must be a number.", "INVALID_INPUT")
            
        transaction_password = request.data.get("transaction_password", "").strip()

        if not target_phone or points_to_transfer <= 0:
            return error_response("Valid phone number and points > 0 are required.", "INVALID_INPUT")
        
        biometric_verified = request.data.get("biometric_verified", False)
        if str(biometric_verified).lower() == 'true':
            biometric_verified = True
            
        if not biometric_verified and not sender.check_transaction_password(transaction_password):
            return error_response("Invalid transaction password or biometric.", "INVALID_PASSWORD", 401)

        if sender.phone_number == target_phone:
            return error_response("Cannot transfer points to yourself.", "INVALID_TARGET")

        try:
            receiver = CustomUser.objects.get(phone_number=target_phone)
        except CustomUser.DoesNotExist:
            return error_response("Target user not found.", "USER_NOT_FOUND", 404)

        if sender.loyalty_points < points_to_transfer:
            return error_response("Insufficient loyalty points.", "INSUFFICIENT_POINTS")

        with transaction.atomic():
            sender.loyalty_points = round(sender.loyalty_points - points_to_transfer, 2)
            sender.save(update_fields=['loyalty_points'])
            receiver.loyalty_points = round(receiver.loyalty_points + points_to_transfer, 2)
            receiver.save(update_fields=['loyalty_points'])
            
            # Create notifications
            Notification.objects.create(
                user=sender,
                title="Points Sent",
                message=f"You successfully sent {points_to_transfer} points to {receiver.first_name} ({target_phone})."
            )
            Notification.objects.create(
                user=receiver,
                title="Points Received",
                message=f"You received {points_to_transfer} points from {sender.first_name} ({sender.phone_number})."
            )

        return success_response({
            "transferred_points": points_to_transfer,
            "remaining_points": sender.loyalty_points,
            "receiver_phone": receiver.phone_number
        }, message="Points transferred successfully.")

class NotificationListView(APIView):
    """Customer: get notifications and mark all as read."""
    permission_classes = [IsAuthenticatedUserCustom]

    def get(self, request):
        notifications = Notification.objects.filter(user=request.user).order_by('-created_at')[:50]
        data = [
            {
                "id": n.id,
                "title": n.title,
                "message": n.message,
                "is_read": n.is_read,
                "created_at": n.created_at.isoformat(),
            }
            for n in notifications
        ]
        return success_response(data)

    def post(self, request):
        """Mark all notifications as read."""
        Notification.objects.filter(user=request.user, is_read=False).update(is_read=True)
        return success_response(message="Notifications marked as read.")
