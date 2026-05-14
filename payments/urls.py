"""Payments app URL patterns."""
from django.urls import path
from payments import views

urlpatterns = [
    path('preview/', views.PaymentPreviewView.as_view(), name='payment-preview'),
    path('process/', views.TableProcessPaymentView.as_view(), name='process-payment'),
    path('history/', views.PaymentHistoryView.as_view(), name='payment-history'),
    path('admin/generate-qr/', views.AdminGeneratePaymentQRView.as_view(), name='admin-generate-qr'),
    path('pay-via-qr/', views.CustomerProcessQRPaymentView.as_view(), name='pay-via-qr'),
    path('table-preview/<str:table_number>/', views.TableGroupPreviewView.as_view(), name='table-group-preview'),
]
