"""Admin panel URL patterns."""
from django.urls import path
from . import views

urlpatterns = [
    path('config/', views.SystemConfigView.as_view(), name='system-config'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('clear-table/<str:table_number>/', views.ClearTableView.as_view(), name='clear-table'),
    path('order-history/', views.AdminOrderHistoryView.as_view(), name='order-history'),
]
