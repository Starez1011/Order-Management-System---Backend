"""Orders WebSocket routing."""
from django.urls import re_path
from . import consumers

websocket_urlpatterns = [
    re_path(r'ws/orders/table/(?P<table_number>[\w\s-]+)/$', consumers.OrderUpdateConsumer.as_asgi()),
    re_path(r'ws/orders/dashboard/$', consumers.DashboardConsumer.as_asgi()),
]
