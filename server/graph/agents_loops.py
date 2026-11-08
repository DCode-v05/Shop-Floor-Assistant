import asyncio, json, os
from server.graph.engine import GLOBAL_GRAPH
from server.tools.production_tools import log_event

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
MACHINES_FILE = os.path.join(DATA_DIR, "machines.json")
ORDERS_FILE = os.path.join(DATA_DIR, "orders.json")
SAFETY_FILE = os.path.join(DATA_DIR, "safety_logs.json")

async def shopfloor_loop(interval=8):
    while True:
        try:
            with open(MACHINES_FILE) as f:
                machines = json.load(f)
            for m in machines:
                if m.get("temperature",0) > 100:
                    event = {"source":"ShopFloorAgent","type":"machine_upset","payload": m}
                    log_event({"agent":"ShopFloorAgent","event": event})
                    await GLOBAL_GRAPH.publish(event)
        except Exception as e:
            log_event({"actor":"ShopFloorAgent","error":str(e)})
        await asyncio.sleep(interval)

async def order_loop(interval=10):
    while True:
        with open(ORDERS_FILE) as f:
            orders = json.load(f)
        for o in orders:
            due = o.get("due_in_hours", 999)
            progress = o.get("progress", 0)
            if due <= 1 and progress < 80:
                dp = max(0, 100 - progress)
                event = {
                    "source": "OrderAgent",
                    "type": "order_delay",
                    "payload": {
                        "order_id": o.get("order_id"),
                        "progress": progress,
                        "due_in_hours": due,
                        "delay_percent": dp,
                    },
                }
                log_event({"agent": "OrderAgent", "event": event})
                await GLOBAL_GRAPH.publish(event)
        await asyncio.sleep(interval)

async def safety_log_loop(interval=6):
    while True:
        try:
            with open(SAFETY_FILE) as f:
                logs = json.load(f)
            for lg in logs:
                if lg.get("status") == "unresolved":
                    event = {"source":"SafetyAgent","type": lg.get("event_type"), "payload": lg}
                    log_event({"agent":"SafetyAgent","event":event})
                    await GLOBAL_GRAPH.publish(event)
        except Exception as e:
            log_event({"actor":"SafetyAgent","error":str(e)})
        await asyncio.sleep(interval)
