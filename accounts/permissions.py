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

class IsSuperAdminUserCustom(BasePermission):
    """Allow only true super users."""
    message = 'Superadmin access required.'

    def has_permission(self, request, view):
        return bool(
            request.user
            and request.user.is_authenticated
            and request.user.is_superuser
        )

def get_target_admin(request):
    """
    Returns the target admin context for the current request.
    If the user is a superadmin and an X-Target-Admin-ID header is provided,
    this attempts to return that specific admin user.
    Otherwise, returns the current authenticated user.
    """
    user = request.user
    if user.is_superuser:
        target_id = request.headers.get('X-Target-Admin-ID')
        if target_id:
            try:
                from accounts.models import CustomUser
                return CustomUser.objects.get(id=target_id, is_staff=True)
            except Exception:
                pass
    return user
