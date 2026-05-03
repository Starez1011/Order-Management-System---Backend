"""Admin panel URL patterns."""
from django.urls import path
from . import views

urlpatterns = [
    path('config/', views.SystemConfigView.as_view(), name='system-config'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('revenue/', views.RevenueAnalyticsView.as_view(), name='revenue'),
    path('clear-table/<str:table_number>/', views.ClearTableView.as_view(), name='clear-table'),
    path('table/<str:table_number>/transfer/', views.TransferTableView.as_view(), name='transfer-table'),
    path('order-history/', views.AdminOrderHistoryView.as_view(), name='order-history'),
    path('table/<str:table_number>/create-order/', views.AdminOrderCreateView.as_view(), name='admin-create-order'),
    path('order/<str:order_number>/edit/', views.AdminOrderEditView.as_view(), name='admin-edit-order'),
]
