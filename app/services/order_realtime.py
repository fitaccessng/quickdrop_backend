from __future__ import annotations

import json
from collections import defaultdict

from fastapi import WebSocket


class OrderRealtimeManager:
    def __init__(self) -> None:
        self.order_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self.connection_keys: dict[str, WebSocket] = {}
        self.socket_keys: dict[WebSocket, str] = {}

    async def connect(self, order_id: str, websocket: WebSocket, connection_key: str) -> bool:
        await self._replace_existing_connection(connection_key)
        if not await self._accept_socket(websocket):
            return False
        self.order_connections[order_id].add(websocket)
        self.connection_keys[connection_key] = websocket
        self.socket_keys[websocket] = connection_key
        return True

    def disconnect(self, websocket: WebSocket) -> None:
        for order_id, sockets in list(self.order_connections.items()):
            sockets.discard(websocket)
            if not sockets:
                self.order_connections.pop(order_id, None)
        connection_key = self.socket_keys.pop(websocket, None)
        if connection_key and self.connection_keys.get(connection_key) is websocket:
            self.connection_keys.pop(connection_key, None)

    async def broadcast(self, order_id: str, payload: dict) -> None:
        dead: list[WebSocket] = []
        message = json.dumps(payload, default=str)
        for socket in list(self.order_connections.get(order_id, set())):
            try:
                await socket.send_text(message)
            except Exception:
                dead.append(socket)
        for socket in dead:
            self.disconnect(socket)

    async def _replace_existing_connection(self, connection_key: str) -> None:
        existing = self.connection_keys.get(connection_key)
        if not existing:
            return
        self.disconnect(existing)
        try:
            await existing.close(code=1000, reason="replaced")
        except Exception:
            pass

    async def _accept_socket(self, websocket: WebSocket) -> bool:
        try:
            await websocket.accept()
            return True
        except RuntimeError:
            return False


order_realtime_manager = OrderRealtimeManager()
