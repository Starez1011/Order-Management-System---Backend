"""Orders app URL patterns."""
from django.urls import path
from orders import views

urlpatterns = [
    # Customer
    path('cart/', views.CartView.as_view(), name='cart'),
    path('place/', views.PlaceOrderView.as_view(), name='place-order'),
    path('detail/<str:order_number>/', views.OrderDetailView.as_view(), name='order-detail'),
    path('history/', views.UserOrderHistoryView.as_view(), name='order-history'),
    path('my-active/', views.MyActiveOrdersView.as_view(), name='my-active-orders'),
    path('cancel/<str:order_number>/', views.CancelOrderView.as_view(), name='cancel-order'),
    path('edit/<str:order_number>/', views.UserEditOrderView.as_view(), name='user-edit-order'),
    # Admin
    path('admin/table/<str:table_number>/', views.AdminTableOrdersView.as_view(), name='admin-table-orders'),
    path('admin/status/<str:order_number>/', views.AdminOrderStatusView.as_view(), name='admin-order-status'),
]
