"""Accounts app permissions."""
from rest_framework.permissions import BasePermission


class IsAuthenticatedUserCustom(BasePermission):
    """Allow only authenticated and OTP-verified users."""
    message = 'Authentication and phone verification required.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_verified
        )


class IsAdminUserCustom(BasePermission):
    """Allow only Django staff/superusers."""
    message = 'Admin access required.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_staff
        )
