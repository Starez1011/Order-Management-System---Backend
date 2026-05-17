"""Admin panel URL patterns."""
from django.urls import path
from admin_panel import views

urlpatterns = [
    path('config/', views.SystemConfigView.as_view(), name='system-config'),
    path('dashboard/', views.DashboardView.as_view(), name='dashboard'),
    path('revenue/', views.RevenueAnalyticsView.as_view(), name='revenue'),
    path('payment-methods/', views.PaymentMethodListView.as_view(), name='payment-methods-list'),
    path('payment-methods/<int:pk>/', views.PaymentMethodDetailView.as_view(), name='payment-methods-detail'),
    path('order/<str:order_number>/payment-method/', views.UpdateOrderPaymentMethodView.as_view(), name='update-order-payment-method'),
    path('clear-table/<str:table_number>/', views.ClearTableView.as_view(), name='clear-table'),
    path('table/<str:table_number>/transfer/', views.TransferTableView.as_view(), name='transfer-table'),
    path('order-history/', views.AdminOrderHistoryView.as_view(), name='order-history'),
    path('table/<str:table_number>/create-order/', views.AdminOrderCreateView.as_view(), name='admin-create-order'),
    path('order/<str:order_number>/edit/', views.AdminOrderEditView.as_view(), name='admin-edit-order'),
    path('user-by-phone/<str:phone_number>/', views.UserByPhoneView.as_view(), name='user-by-phone'),
    # Promotions
    path('banners/', views.BannerListView.as_view(), name='banner-list'),
    path('banners/<int:banner_id>/', views.BannerDetailView.as_view(), name='banner-detail'),
    path('offers/', views.OfferListView.as_view(), name='offer-list'),
    path('offers/<int:offer_id>/', views.OfferDetailView.as_view(), name='offer-detail'),
    path('popular/', views.PopularItemsView.as_view(), name='popular-items'),
]
