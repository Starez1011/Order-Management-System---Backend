"""Menu app URL patterns."""
from django.urls import path
from menu import views

urlpatterns = [
    # Customer
    path('', views.MenuView.as_view(), name='menu'),
    path('category/<int:category_id>/', views.CategoryItemsView.as_view(), name='category-items'),
    # Admin
    path('admin/categories/', views.AdminCategoryListView.as_view(), name='admin-category-list'),
    path('admin/categories/<int:category_id>/', views.AdminCategoryDetailView.as_view(), name='admin-category-detail'),
    path('admin/items/', views.AdminMenuItemListView.as_view(), name='admin-item-list'),
    path('admin/items/<int:item_id>/', views.AdminMenuItemDetailView.as_view(), name='admin-item-detail'),
]
