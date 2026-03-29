"""Orders app WebSocket consumer for live order updates."""
import json
from channels.generic.websocket import AsyncWebsocketConsumer


class OrderUpdateConsumer(AsyncWebsocketConsumer):
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
