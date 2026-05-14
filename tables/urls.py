"""Tables app URL patterns."""
from django.urls import path
from tables import views

urlpatterns = [
    path('validate-qr/', views.ValidateQRView.as_view(), name='validate-qr'),
    path('location/', views.CafeLocationView.as_view(), name='cafe-location'),
    path('branches/', views.CafeLocationListView.as_view(), name='cafe-location-list'),
    path('admin/tables/', views.TableListView.as_view(), name='admin-table-list'),
    path('admin/tables/<str:table_number>/', views.TableDetailView.as_view(), name='admin-table-detail'),
]
