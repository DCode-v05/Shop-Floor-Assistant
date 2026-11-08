import asyncio
import json
from langchain.tools import tool
from langchain_openai import ChatOpenAI
from langchain.agents import AgentExecutor, OpenAIFunctionsAgent
from langchain.schema import SystemMessage
from server.llm import get_triage_llm
from server import tools
from server.agents.safety_log_agent import mark_resolved
from typing import Dict, Any, List

with open("server/prompts/triage_prompt.md", "r") as f:
    TRIAGE_PROMPT = f.read()

system_message = SystemMessage(content=TRIAGE_PROMPT)


def stop_machine_func(input_str: str):
    try:
        d = json.loads(input_str)
        mid = d.get("machine_id")
    except:
        mid = input_str.strip()
    return tools.stop_machine(mid)

def schedule_maintenance_func(input_str: str):
    try:
        d = json.loads(input_str)
        mid = d.get("machine_id")
        eta = d.get("eta_hours", 1)
    except:
        mid = input_str.strip()
        eta = 1
    return tools.schedule_maintenance(mid, eta_hours=eta)

def notify_func(input_str: str):
    try:
        d = json.loads(input_str)
        role = d.get("role", "supervisor")
        msg = d.get("message", input_str)
        level = d.get("level", "info")
    except:
        role = "supervisor"
        msg = input_str
        level = "info"
    return tools.notify(role, msg, level)

def update_order_func(input_str: str):
    try:
        d = json.loads(input_str)
        oid = d.get("order_id")
        nd = d.get("new_due_in_hours", 2)
    except:
        oid = input_str.strip()
        nd = 2
    return tools.update_order_schedule(oid, nd)


lc_tools = [
    tool.from_function(stop_machine_func, name="stop_machine", description="Stop a machine by ID"),
    tool.from_function(schedule_maintenance_func, name="schedule_maintenance",
                       description="Schedule maintenance for a machine"),
    tool.from_function(notify_func, name="notify",
                       description="Send a notification to a role"),
    tool.from_function(update_order_func, name="update_order",
                       description="Reschedule an order by ID")
]


def build_triage_executor():
    llm = get_triage_llm()

    agent = OpenAIFunctionsAgent(
        llm=llm,
        tools=lc_tools,
        system_message=system_message,
    )

    executor = AgentExecutor(
        agent=agent,
        tools=lc_tools,
        verbose=False
    )

    return executor


TRIAGE_EXECUTOR = build_triage_executor()


async def fallback_classification(event: Dict[str, Any]):
    etype = event.get("type")
    out = {
        "severity": "S4",
        "category": "Unknown",
        "recommended_actions": ["log"],
        "tools_to_call": [],
        "rationale": "Default fallback"
    }

    if etype == "machine_overheat":
        temp = event.get("temperature", 0)
        if temp >= 120:
            out = {
                "severity": "S1",
                "category": "Machine",
                "recommended_actions": ["stop_machine", "schedule_maintenance", "notify"],
                "tools_to_call": [
                    {"name": "stop_machine", "args": {"machine_id": event["machine_id"]}},
                    {"name": "schedule_maintenance", "args": {"machine_id": event["machine_id"]}},
                    {"name": "notify",
                     "args": {"role": "supervisor", "message": "Critical overheat", "level": "critical"}}
                ],
                "rationale": f"Temp {temp} > 120°C"
            }

    elif etype == "order_delay":
        dp = event.get("delay_percent", 0)
        if dp >= 50:
            out = {
                "severity": "S2",
                "category": "Order",
                "recommended_actions": ["update_order", "notify"],
                "tools_to_call": [
                    {"name": "update_order", "args": {"order_id": event["order_id"], "new_due_in_hours": 3}},
                    {"name": "notify",
                     "args": {"role": "planner", "message": "Order delayed heavily", "level": "warning"}}
                ],
                "rationale": f"Delay {dp}%"
            }

    elif etype in ("ppe_missing", "unsafe_zone_entry"):
        out = {
            "severity": "S1",
            "category": "Safety",
            "recommended_actions": ["notify", "log"],
            "tools_to_call": [
                {
                    "name": "notify",
                    "args": {
                        "role": "supervisor",
                        "message": f"Safety violation: {etype}",
                        "level": "critical"
                    }
                }
            ],
            "rationale": "Critical safety violation"
        }

    return out


async def execute_tool_calls(tool_calls: List[Dict[str, Any]]):
    for t in tool_calls:
        name = t["name"]
        args = t.get("args", {})
        if hasattr(tools, name):
            fn = getattr(tools, name)
            fn(**args)


async def handle_event(event: Dict[str, Any]):
    try:
        result = TRIAGE_EXECUTOR.invoke({"input": json.dumps(event)})

        tools.log_event({
            "agent": "TriageAgent",
            "event": event,
            "agent_output": result
        })

    except Exception as e:
        fallback = await fallback_classification(event)

        tools.log_event({
            "agent": "TriageAgent",
            "event": event,
            "fallback_used": True,
            "fallback_output": fallback,
            "error": str(e)
        })

        await execute_tool_calls(fallback["tools_to_call"])

    if "log_id" in event:
        await mark_resolved(event["log_id"])

    return True


triage_queue = asyncio.Queue()

async def publish(event: Dict[str, Any]):
    await triage_queue.put(event)

async def triage_loop():
    while True:
        evt = await triage_queue.get()
        try:
            await handle_event(evt)
        except Exception as e:
            tools.log_event({"agent": "TriageAgent", "error": str(e), "event": evt})
        triage_queue.task_done()
