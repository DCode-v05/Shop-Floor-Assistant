from typing import Any, Dict, Set
from fastapi import WebSocket
from server.tools.production_tools import append_log as _append_log 


class ConnectionManager:
    def __init__(self):
        self.active: Set[WebSocket] = set()

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.add(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast_json(self, payload: Dict[str, Any]):
        dead = []
        for ws in list(self.active):
            try:
                await ws.send_json(payload)
            except Exception:
                dead.append(ws)
        for ws in dead:
            self.disconnect(ws)


MANAGER = ConnectionManager()


async def notify_log(entry: Dict[str, Any]):
    await MANAGER.broadcast_json({"type": "log", "data": entry})


async def notify_triage(result: Dict[str, Any]):
    await MANAGER.broadcast_json({"type": "triage", "data": result})


async def notify_safety_resolved(log_id: str):
    await MANAGER.broadcast_json({"type": "safety_resolved", "data": {"id": log_id}})
