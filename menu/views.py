"""Menu app views — Category and MenuItem CRUD + customer listing."""
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from .models import Category, MenuItem
from accounts.permissions import IsAdminUserCustom


def success_response(data=None, message="Success", http_status=200):
    return Response({"success": True, "message": message, "data": data if data is not None else {}}, status=http_status)


def error_response(message, error_code="ERROR", http_status=400):
    return Response({"success": False, "message": message, "error_code": error_code}, status=http_status)


def serialize_item(item, request=None):
    image_url = None
    if item.image:
        image_url = request.build_absolute_uri(item.image.url) if request else item.image.url
    return {
        "id": item.id,
        "name": item.name,
        "category": item.category.name,
        "category_id": item.category.id,
        "price": str(item.price),
        "description": item.description,
        "image_url": image_url,
        "is_available": item.is_available,
    }


def serialize_category(cat, request=None):
    return {
        "id": cat.id,
        "name": cat.name,
        "is_active": cat.is_active,
        "items": [serialize_item(i, request) for i in cat.items.filter(is_available=True)],
    }


# ──────────────────────────── Customer Views ────────────────────────────

class MenuView(APIView):
    """Public: full menu grouped by active category."""

    def get(self, request):
        categories = (
            Category.objects
            .filter(is_active=True)
            .prefetch_related('items')
        )
        data = [serialize_category(c, request) for c in categories]
        return success_response(data)


class CategoryItemsView(APIView):
    """Public: items for a single category."""

    def get(self, request, category_id):
        try:
            cat = Category.objects.prefetch_related('items').get(pk=category_id, is_active=True)
        except Category.DoesNotExist:
            return error_response("Category not found.", "CATEGORY_NOT_FOUND", 404)
        return success_response(serialize_category(cat, request))


# ──────────────────────────── Admin Category Views ────────────────────────

class AdminCategoryListView(APIView):
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        cats = Category.objects.all()
        data = [{"id": c.id, "name": c.name, "is_active": c.is_active} for c in cats]
        return success_response(data)

    def post(self, request):
        name = request.data.get("name", "").strip()
        if not name:
            return error_response("Category name is required.", "MISSING_NAME")
        if Category.objects.filter(name__iexact=name).exists():
            return error_response("Category already exists.", "CATEGORY_EXISTS")
        cat = Category.objects.create(name=name)
        return success_response({"id": cat.id, "name": cat.name}, "Category created.", 201)


class AdminCategoryDetailView(APIView):
    permission_classes = [IsAdminUserCustom]

    def patch(self, request, category_id):
        try:
            cat = Category.objects.get(pk=category_id)
        except Category.DoesNotExist:
            return error_response("Category not found.", "CATEGORY_NOT_FOUND", 404)
        cat.name = request.data.get("name", cat.name)
        cat.is_active = request.data.get("is_active", cat.is_active)
        cat.save()
        return success_response(message="Category updated.")

    def delete(self, request, category_id):
        try:
            cat = Category.objects.get(pk=category_id)
        except Category.DoesNotExist:
            return error_response("Category not found.", "CATEGORY_NOT_FOUND", 404)
        cat.delete()
        return success_response(message="Category deleted.")


# ──────────────────────────── Admin MenuItem Views ────────────────────────

class AdminMenuItemListView(APIView):
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        items = MenuItem.objects.select_related('category').all()
        data = [serialize_item(i, request) for i in items]
        return success_response(data)

    def post(self, request):
        name = request.data.get("name", "").strip()
        category_id = request.data.get("category_id")
        price = request.data.get("price")
        description = request.data.get("description", "")

        if not all([name, category_id, price]):
            return error_response("name, category_id, and price are required.", "MISSING_FIELDS")

        try:
            category = Category.objects.get(pk=category_id)
        except Category.DoesNotExist:
            return error_response("Category not found.", "CATEGORY_NOT_FOUND", 404)

        try:
            price = float(price)
            if price <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return error_response("Invalid price.", "INVALID_PRICE")

        item = MenuItem.objects.create(
            name=name, category=category, price=price, description=description,
            image=request.FILES.get("image"),
        )
        return success_response(serialize_item(item, request), "Item created.", 201)


class AdminMenuItemDetailView(APIView):
    permission_classes = [IsAdminUserCustom]

    def patch(self, request, item_id):
        try:
            item = MenuItem.objects.select_related('category').get(pk=item_id)
        except MenuItem.DoesNotExist:
            return error_response("Item not found.", "ITEM_NOT_FOUND", 404)

        item.name = request.data.get("name", item.name)
        item.description = request.data.get("description", item.description)
        item.is_available = request.data.get("is_available", item.is_available)

        price = request.data.get("price")
        if price is not None:
            try:
                item.price = float(price)
            except (TypeError, ValueError):
                return error_response("Invalid price.", "INVALID_PRICE")

        category_id = request.data.get("category_id")
        if category_id:
            try:
                item.category = Category.objects.get(pk=category_id)
            except Category.DoesNotExist:
                return error_response("Category not found.", "CATEGORY_NOT_FOUND", 404)

        if request.FILES.get("image"):
            item.image = request.FILES.get("image")
        elif str(request.data.get("remove_image", "")).lower() == "true":
            item.image = None

        item.save()
        return success_response(serialize_item(item, request), "Item updated.")

    def delete(self, request, item_id):
        try:
            item = MenuItem.objects.get(pk=item_id)
        except MenuItem.DoesNotExist:
            return error_response("Item not found.", "ITEM_NOT_FOUND", 404)
        item.delete()
        return success_response(message="Item deleted.")
