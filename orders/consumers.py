"""Orders app WebSocket consumers for live order updates."""
import json
from channels.generic.websocket import AsyncWebsocketConsumer


class OrderUpdateConsumer(AsyncWebsocketConsumer):
    """Per-table consumer — used by TableDetail page to listen for order changes."""

    async def connect(self):
        self.table_number = self.scope['url_route']['kwargs']['table_number']
        self.group_name = f"table_{self.table_number}"
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def order_update(self, event):
        """Receive order_update from channel layer and push to WebSocket."""
        await self.send(text_data=json.dumps({
            "type": "order_update",
            "table_number": event["table_number"],
        }))


import urllib.parse

class DashboardConsumer(AsyncWebsocketConsumer):
    """
    Branch-specific consumer for the admin dashboard.
    Joins the 'dashboard_{admin_id}' group and receives a message whenever
    any table in that branch changes state.
    """

    async def connect(self):
        import jwt
        from django.conf import settings
        
        query_string = self.scope['query_string'].decode()
        query_params = urllib.parse.parse_qs(query_string)
        
        target_admin_id = query_params.get('target_admin_id', [None])[0]
        token = query_params.get('token', [None])[0]
        
        if not target_admin_id and token:
            try:
                payload = jwt.decode(token, settings.SECRET_KEY, algorithms=['HS256'])
                target_admin_id = payload.get('user_id')
            except Exception:
                pass
        
        if target_admin_id:
            self.group_name = f"dashboard_{target_admin_id}"
        else:
            self.group_name = "dashboard_global"
            
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)

    async def dashboard_update(self, event):
        """Forward dashboard_update events to the connected WebSocket client."""
        await self.send(text_data=json.dumps({
            "type": "dashboard_update",
            "table_number": event.get("table_number", ""),
        }))
