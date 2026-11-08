from typing import Any, Dict
from server.tools.production_tools import stop_machine, schedule_maintenance, update_order_schedule, log_event
from server.tools.notify_tools import notify
from server.graph.state import ToolCall

TOOL_MAP = {
    "stop_machine": stop_machine,
    "schedule_maintenance": schedule_maintenance,
    "update_order": update_order_schedule,
    "notify": notify,
    "log": log_event
}

def _normalize_call(call: Any) -> Dict[str, Any]:
    if isinstance(call, ToolCall):
        return {"name": call.name, "args": call.args or {}}
    if isinstance(call, dict):
        return {"name": call.get("name"), "args": call.get("args", {})}
    return {"name": None, "args": {}}

def execute_tool_call(call: dict | ToolCall):
    norm = _normalize_call(call)
    name = norm.get("name")
    args = norm.get("args", {})
    if name in TOOL_MAP:
        fn = TOOL_MAP[name]
        return fn(**args)
    else:
        return {"error":"unknown_tool", "tool": name}
