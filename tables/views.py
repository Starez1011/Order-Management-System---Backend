"""Tables app views — QR validation, sessions, admin table CRUD."""
from django.utils import timezone
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import CafeLocation, Table, TableSession
from .utils import is_within_cafe
from accounts.permissions import IsAuthenticatedUserCustom, IsAdminUserCustom


def success_response(data=None, message="Success", http_status=200):
    return Response({"success": True, "message": message, "data": data if data is not None else {}}, status=http_status)


def error_response(message, error_code="ERROR", http_status=400):
    return Response({"success": False, "message": message, "error_code": error_code}, status=http_status)


class ValidateQRView(APIView):
    """
    Customer scans QR → validates token + location → creates/returns session.
    Auth optional: anonymous users can validate location; session assigned if logged in.
    """

    def post(self, request):
        qr_token = request.data.get("qr_token", "").strip()
        user_lat = request.data.get("latitude")
        user_lon = request.data.get("longitude")

        if not qr_token:
            return error_response("QR token is required.", "MISSING_QR_TOKEN")
        if user_lat is None or user_lon is None:
            return error_response("Location coordinates are required.", "MISSING_LOCATION")

        # Strip the CAFE_TABLE: prefix that the admin QR encodes
        if qr_token.upper().startswith("CAFE_TABLE:"):
            qr_token = qr_token[len("CAFE_TABLE:"):]

        try:
            user_lat = float(user_lat)
            user_lon = float(user_lon)
        except (TypeError, ValueError):
            return error_response("Invalid coordinates.", "INVALID_LOCATION")

        # Validate QR token
        try:
            table = Table.objects.get(qr_token=qr_token, is_active=True)
        except Table.DoesNotExist:
            return error_response("Invalid or inactive QR code.", "INVALID_QR", 404)

        # Validate location
        cafe_loc = CafeLocation.objects.first()
        if cafe_loc:
            if not is_within_cafe(user_lat, user_lon, cafe_loc.latitude, cafe_loc.longitude, cafe_loc.radius_meters):
                return error_response(
                    "You must be inside the café to place an order.",
                    "OUTSIDE_CAFE_RADIUS",
                    403,
                )

        # Create or return active session
        user = request.user if request.user.is_authenticated else None
        with transaction.atomic():
            session, created = TableSession.objects.get_or_create(
                table=table, is_active=True,
                defaults={"user": user}
            )
            if not created and user and not session.user:
                session.user = user
                session.save()

        return success_response({
            "table_number": table.table_number,
            "qr_token": str(table.qr_token),
            "session_id": session.id,
            "location_valid": True,
        }, "Table session started.")


class TableListView(APIView):
    """Admin: list all tables."""
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        tables = Table.objects.prefetch_related('sessions').all()
        data = []
        for t in tables:
            active_session = t.sessions.filter(is_active=True).first()
            data.append({
                "table_number": t.table_number,
                "qr_token": str(t.qr_token),
                "is_active": t.is_active,
                "has_active_session": active_session is not None,
            })
        return success_response(data)

    def post(self, request):
        table_number = request.data.get("table_number")
        if not table_number:
            return error_response("table_number is required.", "MISSING_FIELD")
        if Table.objects.filter(table_number=table_number).exists():
            return error_response("Table number already exists.", "TABLE_EXISTS")
        table = Table.objects.create(table_number=table_number)
        return success_response({
            "table_number": table.table_number,
            "qr_token": str(table.qr_token),
        }, "Table created.", 201)


class TableDetailView(APIView):
    """Admin: update or delete a table by table_number."""
    permission_classes = [IsAdminUserCustom]

    def get(self, request, table_number):
        try:
            table = Table.objects.get(table_number=table_number)
        except Table.DoesNotExist:
            return error_response("Table not found.", "TABLE_NOT_FOUND", 404)

        active_session = table.sessions.filter(is_active=True).first()
        return success_response({
            "table_number": table.table_number,
            "qr_token": str(table.qr_token),
            "is_active": table.is_active,
            "has_active_session": active_session is not None,
            "session_id": active_session.id if active_session else None,
        })

    def patch(self, request, table_number):
        try:
            table = Table.objects.get(table_number=table_number)
        except Table.DoesNotExist:
            return error_response("Table not found.", "TABLE_NOT_FOUND", 404)
        table.is_active = request.data.get("is_active", table.is_active)
        table.save()
        return success_response(message="Table updated.")

    def delete(self, request, table_number):
        try:
            table = Table.objects.get(table_number=table_number)
        except Table.DoesNotExist:
            return error_response("Table not found.", "TABLE_NOT_FOUND", 404)
        table.delete()
        return success_response(message="Table deleted.")


class CafeLocationView(APIView):
    """Admin: update, Any Auth: get café GPS location and details."""
    
    def get_permissions(self):
        if self.request.method == 'GET':
            return [IsAuthenticatedUserCustom()]
        return [IsAdminUserCustom()]

    def get(self, request):
        loc = CafeLocation.objects.first()
        if not loc:
            return error_response("Café location not configured.", "NO_LOCATION", 404)
        return success_response({
            "name": loc.name,
            "address": loc.address,
            "phone_number": loc.phone_number,
            "latitude": loc.latitude,
            "longitude": loc.longitude,
            "radius_meters": loc.radius_meters,
        })

    def post(self, request):
        lat = request.data.get("latitude")
        lon = request.data.get("longitude")
        radius = request.data.get("radius_meters", 100.0)
        name = request.data.get("name", "Main Café")
        address = request.data.get("address", "")
        phone_number = request.data.get("phone_number", "")
        
        if lat is None or lon is None:
            return error_response("latitude and longitude are required.", "MISSING_FIELDS")
            
        loc, _ = CafeLocation.objects.update_or_create(
            pk=1,
            defaults={
                "latitude": float(lat), 
                "longitude": float(lon),
                "radius_meters": float(radius), 
                "name": name,
                "address": address,
                "phone_number": phone_number
            }
        )
        return success_response(message="Café location updated.")
