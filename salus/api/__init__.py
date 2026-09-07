"""Salus REST and WebSocket API."""

from salus.api.app import create_app
from salus.api.websocket import WebSocketBroadcaster

__all__ = ["WebSocketBroadcaster", "create_app"]
