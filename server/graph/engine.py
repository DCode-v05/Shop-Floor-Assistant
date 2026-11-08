import asyncio
from typing import Any, Dict, List
from server.graph.state import Event, TriageOutput, MemoryState
from server.graph.triage_graph import triage_run
from server.graph.event_router import route_and_execute
from server.tools.production_tools import log_event
from server.tools.safety_store import mark_resolved as mark_safety_resolved
from server.realtime import notify_triage, notify_safety_resolved


class GlobalRouterGraph:
    def __init__(self):
        self.queue: asyncio.Queue[Dict[str, Any]] = asyncio.Queue()
        self.memory = MemoryState()

    def snapshot_memory(self) -> Dict[str, Any]:
        return {
            "events_processed": self.memory.events_processed,
            "counts_by_category": dict(self.memory.counts_by_category),
            "counts_by_severity": dict(self.memory.counts_by_severity),
            "last_triage": self.memory.last_triage.dict() if self.memory.last_triage else None,
        }

    async def publish(self, event: Dict[str, Any]):
        await self.queue.put(event)

    def _update_memory(self, triage: TriageOutput):
        self.memory.events_processed += 1
        self.memory.counts_by_category[triage.category] = self.memory.counts_by_category.get(triage.category, 0) + 1
        self.memory.counts_by_severity[triage.severity] = self.memory.counts_by_severity.get(triage.severity, 0) + 1
        self.memory.last_triage = triage

    async def process_one(self, ev: Dict[str, Any]) -> Dict[str, Any]:
        event = Event(**ev)
        triage = triage_run(event)
        log_event({"agent": "TriageGraph", "event": ev, "triage": triage.dict()})
        executed = route_and_execute(triage)
        log_event({"agent": "TriageGraph", "executed": executed})
        self._update_memory(triage)

        try:
            if isinstance(ev, dict):
                etype = ev.get("type")
                payload = ev.get("payload", {}) if isinstance(ev.get("payload", {}), dict) else {}
                if (ev.get("source") == "SafetyAgent" and payload.get("id")) or (etype == "safety_resolve" and payload.get("id")):
                    log_id = payload.get("id")
                    if mark_safety_resolved(log_id):
                        log_event({"agent": "TriageGraph", "action": "safety_resolved", "log_id": log_id})
                        try:
                            import asyncio
                            loop = asyncio.get_running_loop()
                            loop.create_task(notify_safety_resolved(log_id))
                        except Exception:
                            pass
        except Exception:
            pass

        result = {"event": ev, "triage": triage.dict(), "executed": executed}
        try:
            import asyncio
            coro = notify_triage(result)
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except Exception:
            pass
        return result

    async def run_loop(self):
        while True:
            ev = await self.queue.get()
            try:
                await self.process_one(ev)
            except Exception as e:
                log_event({"actor": "GlobalRouterGraph", "error": str(e), "event": ev})
            finally:
                self.queue.task_done()


GLOBAL_GRAPH = GlobalRouterGraph()
