"""Accounts app URL patterns."""
from django.urls import path
from rest_framework_simplejwt.views import TokenRefreshView
from . import views

urlpatterns = [
    path('register/', views.RegisterView.as_view(), name='register'),
    path('send-otp/', views.SendOTPView.as_view(), name='send-otp'),
    path('verify-otp/', views.VerifyOTPView.as_view(), name='verify-otp'),
    path('login/', views.LoginView.as_view(), name='login'),
    path('token/refresh/', TokenRefreshView.as_view(), name='token-refresh'),
    path('profile/', views.ProfileView.as_view(), name='profile'),
    path('admin/users/', views.AdminUserListView.as_view(), name='admin-users'),
    path('transaction-password/', views.SetTransactionPasswordView.as_view(), name='transaction-password'),
    path('transfer-points/', views.TransferPointsView.as_view(), name='transfer-points'),
]
