from __future__ import annotations

import json
from collections import defaultdict

from fastapi import WebSocket


class RideRealtimeManager:
    def __init__(self) -> None:
        self.ride_connections: dict[str, set[WebSocket]] = defaultdict(set)
        self.admin_connections: set[WebSocket] = set()
        self.connection_keys: dict[str, WebSocket] = {}
        self.socket_keys: dict[WebSocket, str] = {}

    async def connect_ride(self, ride_id: str, websocket: WebSocket, connection_key: str) -> bool:
        return await self._connect(
            websocket=websocket,
            connection_key=connection_key,
            register=lambda: self.ride_connections[ride_id].add(websocket),
        )

    async def connect_admin(self, websocket: WebSocket, connection_key: str) -> bool:
        return await self._connect(
            websocket=websocket,
            connection_key=connection_key,
            register=lambda: self.admin_connections.add(websocket),
        )

    def disconnect(self, websocket: WebSocket) -> None:
        for ride_id, sockets in list(self.ride_connections.items()):
            sockets.discard(websocket)
            if not sockets:
                self.ride_connections.pop(ride_id, None)
        self.admin_connections.discard(websocket)

        connection_key = self.socket_keys.pop(websocket, None)
        if connection_key and self.connection_keys.get(connection_key) is websocket:
            self.connection_keys.pop(connection_key, None)

    async def broadcast_ride(self, ride_id: str, payload: dict) -> None:
        await self._broadcast(self.ride_connections.get(ride_id, set()), payload)
        await self._broadcast(self.admin_connections, payload)

    async def broadcast_admin(self, payload: dict) -> None:
        await self._broadcast(self.admin_connections, payload)

    async def _broadcast(self, sockets: set[WebSocket], payload: dict) -> None:
        dead: list[WebSocket] = []
        message = json.dumps(payload, default=str)
        for socket in list(sockets):
            try:
                await socket.send_text(message)
            except Exception:
                dead.append(socket)
        for socket in dead:
            self.disconnect(socket)

    async def _connect(self, *, websocket: WebSocket, connection_key: str, register) -> bool:
        await self._replace_existing_connection(connection_key)
        if not await self._accept_socket(websocket):
            return False
        register()
        self.connection_keys[connection_key] = websocket
        self.socket_keys[websocket] = connection_key
        return True

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


ride_realtime_manager = RideRealtimeManager()
