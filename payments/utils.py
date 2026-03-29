"""Payments loyalty calculation helpers."""
from admin_panel.models import SystemConfig


def get_system_config():
    config, _ = SystemConfig.objects.get_or_create(pk=1)
    return config


def calculate_discount(points_used: float, point_value: float) -> float:
    """Convert points to Rs discount amount."""
    return round(points_used * point_value, 2)


def calculate_points_earned(total_amount: float, loyalty_percentage: float) -> float:
    """Points earned after payment = total * loyalty% / 100."""
    return round((total_amount * loyalty_percentage) / 100, 2)


def validate_points_redemption(points_used: float, user_points: float, total_amount: float, point_value: float) -> str | None:
    """
    Returns error string if redemption is invalid, else None.
    """
    if points_used < 0:
        return "Points to use cannot be negative."
    if points_used > user_points:
        return "Insufficient loyalty points."
    discount = calculate_discount(points_used, point_value)
    if discount > total_amount:
        return "Points discount cannot exceed total bill amount."
    return None
