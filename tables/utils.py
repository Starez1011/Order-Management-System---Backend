"""Tables app — Haversine location utility."""
import math


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """
    Calculate great-circle distance between two GPS points using the Haversine formula.
    Returns distance in meters.
    """
    R = 6_371_000  # Earth radius in meters
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c


def is_within_cafe(user_lat: float, user_lon: float, cafe_lat: float, cafe_lon: float, radius: float) -> bool:
    """Returns True if user is within the café's allowed radius."""
    distance = haversine_distance(user_lat, user_lon, cafe_lat, cafe_lon)
    return distance <= radius
