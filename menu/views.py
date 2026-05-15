"""Menu app views — Category and MenuItem CRUD + customer listing."""
from django.db import transaction
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status

from menu.models import Category, MenuItem
from accounts.permissions import IsAdminUserCustom, get_target_admin


def success_response(data=None, message="Success", http_status=200):
    return Response({"success": True, "message": message, "data": data if data is not None else {}}, status=http_status)


def error_response(message, error_code="ERROR", http_status=400):
    return Response({"success": False, "message": message, "error_code": error_code}, status=http_status)


def serialize_item(item, request=None):
    image_url = None
    if item.image:
        image_url = item.image.url
    return {
        "id": item.id,
        "name": item.name,
        "category": item.category.name,
        "category_id": item.category.id,
        "price": str(item.price),
        "discount_percentage": item.discount_percentage,
        "discounted_price": str(item.discounted_price) if item.discounted_price is not None else None,
        "description": item.description,
        "image_url": image_url,
        "is_available": item.is_available,
        "is_global": item.admin.is_superuser if hasattr(item, 'admin') and item.admin else False,
    }


def serialize_category(cat, request=None):
    return {
        "id": cat.id,
        "name": cat.name,
        "is_active": cat.is_active,
        "items": [serialize_item(i, request) for i in cat.items.filter(is_available=True)],
    }


from django.db.models import Q

# ──────────────────────────── Customer Views ────────────────────────────

class MenuView(APIView):
    """Public: full menu grouped by active category.
    Returns BOTH global (superadmin) items and branch-local items.
    """

    def get(self, request):
        branch_id = request.GET.get('branch_id')
        
        # Admin dashboard fallback: if branch_id is missing, try to derive it from the admin context
        if not branch_id and request.user and request.user.is_authenticated and request.user.is_staff:
            target_admin = get_target_admin(request)
            if hasattr(target_admin, 'cafe_location') and target_admin.cafe_location:
                branch_id = target_admin.cafe_location.id

        if not branch_id:
            return error_response("branch_id is required to fetch the menu.", "MISSING_BRANCH_ID", 400)

        try:
            # Include: categories owned by the branch's admin (local)
            #      OR: categories owned by the superuser (global)
            categories = (
                Category.objects
                .filter(
                    Q(admin__cafe_location__id=branch_id) | Q(admin__is_superuser=True),
                    is_active=True
                )
                .select_related('admin')
                .prefetch_related('items')
                .distinct()
            )
            data = [serialize_category(c, request) for c in categories]
            return success_response(data)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return error_response(f"Failed to load menu: {str(e)}", "SERVER_ERROR", 500)


class CategoryItemsView(APIView):
    """Public: items for a single category."""

    def get(self, request, category_id):
        branch_id = request.GET.get('branch_id')
        try:
            if branch_id:
                cat = Category.objects.prefetch_related('items').get(
                    Q(admin__cafe_location__id=branch_id) | Q(admin__is_superuser=True),
                    pk=category_id, is_active=True
                )
            else:
                cat = Category.objects.prefetch_related('items').get(pk=category_id, is_active=True)
        except Category.DoesNotExist:
            return error_response("Category not found.", "CATEGORY_NOT_FOUND", 404)
        return success_response(serialize_category(cat, request))


# ──────────────────────────── Admin Category Views ────────────────────────

class AdminCategoryListView(APIView):
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        target_admin = get_target_admin(request)
        if target_admin.is_superuser:
            cats = Category.objects.filter(admin=target_admin)
        else:
            cats = Category.objects.filter(
                Q(admin=target_admin) | Q(admin__is_superuser=True)
            ).distinct()
            
        data = [{"id": c.id, "name": c.name, "is_active": c.is_active, "is_global": c.admin.is_superuser} for c in cats]
        return success_response(data)

    def post(self, request):
        target_admin = get_target_admin(request)
        name = request.data.get("name", "").strip()
        if not name:
            return error_response("Category name is required.")

        if Category.objects.filter(admin=target_admin, name__iexact=name).exists():
            return error_response("Category with this name already exists.", "CATEGORY_EXISTS")

        cat = Category.objects.create(admin=target_admin, name=name)
        return success_response({"id": cat.id, "name": cat.name}, "Category created.", 201)


class AdminCategoryDetailView(APIView):
    permission_classes = [IsAdminUserCustom]

    def patch(self, request, category_id):
        target_admin = get_target_admin(request)
        try:
            cat = Category.objects.get(pk=category_id, admin=target_admin)
        except Category.DoesNotExist:
            return error_response("Category not found.", "CATEGORY_NOT_FOUND", 404)
        cat.name = request.data.get("name", cat.name)
        cat.is_active = request.data.get("is_active", cat.is_active)
        cat.save()
        return success_response(message="Category updated.")

    def delete(self, request, category_id):
        target_admin = get_target_admin(request)
        try:
            cat = Category.objects.get(pk=category_id, admin=target_admin)
        except Category.DoesNotExist:
            return error_response("Category not found.", "CATEGORY_NOT_FOUND", 404)
        cat.delete()
        return success_response(message="Category deleted.")


# ──────────────────────────── Admin MenuItem Views ────────────────────────

class AdminMenuItemListView(APIView):
    permission_classes = [IsAdminUserCustom]

    def get(self, request):
        target_admin = get_target_admin(request)
        if target_admin.is_superuser:
            items = MenuItem.objects.select_related('category').filter(category__admin=target_admin)
        else:
            items = MenuItem.objects.select_related('category').filter(
                Q(category__admin=target_admin) | Q(category__admin__is_superuser=True)
            ).distinct()
        data = [serialize_item(i, request) for i in items]
        return success_response(data)

    def post(self, request):
        target_admin = get_target_admin(request)
        name = request.data.get("name", "").strip()
        category_id = request.data.get("category_id")
        price = request.data.get("price")
        discount_percentage = request.data.get("discount_percentage")
        discounted_price = request.data.get("discounted_price")
        description = request.data.get("description", "")

        if not all([name, category_id, price]):
            return error_response("name, category_id, and price are required.", "MISSING_FIELDS")

        try:
            category = Category.objects.get(pk=category_id, admin=target_admin)
        except Category.DoesNotExist:
            return error_response("Category not found.", "CATEGORY_NOT_FOUND", 404)

        try:
            price = float(price)
            if price <= 0:
                raise ValueError
        except (TypeError, ValueError):
            return error_response("Invalid price.", "INVALID_PRICE")

        item = MenuItem.objects.create(
            admin=target_admin, name=name, category=category, price=price, description=description,
            discount_percentage=int(discount_percentage) if discount_percentage else None,
            discounted_price=float(discounted_price) if discounted_price else None,
            image=request.FILES.get("image"),
        )
        return success_response(serialize_item(item, request), "Item created.", 201)


class AdminMenuItemDetailView(APIView):
    permission_classes = [IsAdminUserCustom]

    def patch(self, request, item_id):
        target_admin = get_target_admin(request)
        try:
            item = MenuItem.objects.select_related('category').get(pk=item_id, admin=target_admin)
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

        dp_val = request.data.get("discount_percentage")
        if dp_val is not None:
            item.discount_percentage = int(dp_val) if dp_val != "" else None
        
        dprice_val = request.data.get("discounted_price")
        if dprice_val is not None:
            item.discounted_price = float(dprice_val) if dprice_val != "" else None

        category_id = request.data.get("category_id")
        if category_id:
            try:
                item.category = Category.objects.get(pk=category_id, admin=target_admin)
            except Category.DoesNotExist:
                return error_response("Category not found.", "CATEGORY_NOT_FOUND", 404)

        if request.FILES.get("image"):
            item.image = request.FILES.get("image")
        elif str(request.data.get("remove_image", "")).lower() == "true":
            item.image = None

        item.save()
        return success_response(serialize_item(item, request), "Item updated.")

    def delete(self, request, item_id):
        target_admin = get_target_admin(request)
        try:
            item = MenuItem.objects.get(pk=item_id, admin=target_admin)
        except MenuItem.DoesNotExist:
            return error_response("Item not found.", "ITEM_NOT_FOUND", 404)
        item.delete()
        return success_response(message="Item deleted.")
