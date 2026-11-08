import json, os, datetime, threading
from server.config import DATA_DIR, LOG_FILE

_LOG_LOCK = threading.Lock()

def _ensure_log():
    os.makedirs(DATA_DIR, exist_ok=True)
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE,"w") as f:
            json.dump([], f)

def append_log(entry):
    _ensure_log()
    with _LOG_LOCK:
        try:
            with open(LOG_FILE, "r") as f:
                logs = json.load(f)
            if not isinstance(logs, list):
                logs = []
        except Exception:
            logs = []
        entry["timestamp"] = datetime.datetime.utcnow().isoformat()
        logs.insert(0, entry)
        tmp_path = LOG_FILE + ".tmp"
        with open(tmp_path, "w") as f:
            json.dump(logs, f, indent=2)
        os.replace(tmp_path, LOG_FILE)
    try:
        from server.realtime import notify_log
        import asyncio
        coro = notify_log(entry)
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(coro)
        except RuntimeError:
            pass
    except Exception:
        pass

def stop_machine(machine_id: str):
    append_log({"actor":"tool","action":"stop_machine","target":machine_id})
    return {"status":"ok","msg":f"Machine {machine_id} stopped."}

def schedule_maintenance(machine_id: str, eta_hours:int=1):
    append_log({"actor":"tool","action":"schedule_maintenance","target":machine_id,"eta_hours":eta_hours})
    return {"status":"ok","msg":f"Maintenance scheduled for {machine_id}."}

def update_order_schedule(order_id: str, new_due_in_hours: float):
    append_log({"actor":"tool","action":"update_order","target":order_id,"new_due_in_hours": new_due_in_hours})
    return {"status":"ok","msg":f"Order {order_id} rescheduled."}

def log_event(event):
    append_log({"actor":"tool","action":"log","event":event})
    return {"status":"ok"}
