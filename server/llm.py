import json
import os
from typing import Dict, Any
from server.config import USE_OPENAI_TRIAGE, TRIAGE_MODEL, OPENAI_API_KEY

class MockLLM:
    """
    Return deterministic triage responses based on event.
    """
    def triage(self, event: Dict[str,Any]) -> Dict[str,Any]:
        etype = event.get("type")
        if etype in ("machine_overheat", "machine_upset"):
            temp = event.get("payload", {}).get("temperature", event.get("temperature", 0))
            vib = event.get("payload", {}).get("vibration", event.get("vibration", 0))
            if temp >= 120:
                return {
                    "severity":"S1",
                    "category":"Machine",
                    "rationale": f"Temp {temp}C > 120C",
                    "tools_to_call": [
                        {"name":"stop_machine","args":{"machine_id": event.get("payload", {}).get("id", event.get("machine_id"))}},
                        {"name":"schedule_maintenance","args":{"machine_id": event.get("payload", {}).get("id", event.get("machine_id"))}},
                        {"name":"notify","args":{"role":"supervisor","message":f"Machine overheat detected","level":"critical"}}
                    ]
                }
            elif temp >= 100 or vib >= 1.2:
                return {
                    "severity":"S2",
                    "category":"Machine",
                    "rationale": f"Upset: temp {temp}C or vibration {vib}",
                    "tools_to_call":[{"name":"notify","args":{"role":"maintenance","message":"High temp","level":"warning"}}]
                }
        if etype == "order_delay":
            dp = event.get("payload", {}).get("delay_percent", event.get("delay_percent",0))
            if dp >= 50:
                return {
                    "severity":"S2","category":"Order",
                    "rationale": f"Delay {dp}%",
                    "tools_to_call":[
                        {"name":"update_order","args":{"order_id": event.get("payload",{}).get("order_id", event.get("order_id")), "new_due_in_hours": 3}},
                        {"name":"notify","args":{"role":"planner","message":"Order heavily delayed","level":"warning"}}
                    ]
                }
            elif dp >= 20:
                return {"severity":"S3","category":"Order","rationale":"Moderate delay","tools_to_call":[{"name":"notify","args":{"role":"planner","message":"Order delayed","level":"info"}}]}
        if etype in ("ppe_missing","unsafe_zone_entry","ppe_violation"):
            return {
                "severity":"S1","category":"Safety",
                "rationale":"PPE missing / unsafe zone entry",
                "tools_to_call":[{"name":"notify","args":{"role":"supervisor","message":"Safety violation detected","level":"critical"}}]
            }
        return {"severity":"S4","category":"Unknown","rationale":"No issue","tools_to_call":[]}

llm = MockLLM()

def triage_with_openai(event: Dict[str, Any]) -> Dict[str, Any]:
    try:
        from openai import OpenAI
        client = OpenAI(api_key=OPENAI_API_KEY or None)
        prompt = (
            "You are a manufacturing triage agent. Return ONLY JSON with keys: "
            "severity, category, rationale, tools_to_call (list of {name,args}).\n"
            f"Event: {json.dumps(event)}"
        )
        resp = client.chat.completions.create(
            model=TRIAGE_MODEL,
            messages=[{"role": "system", "content": "Respond with strict JSON only."},
                      {"role": "user", "content": prompt}],
            temperature=0.1,
        )
        content = resp.choices[0].message.content
        data = json.loads(content)
        if not isinstance(data.get("tools_to_call", []), list):
            data["tools_to_call"] = []
        return data
    except Exception:
        return llm.triage(event)

def triage(event: Dict[str, Any]) -> Dict[str, Any]:
    if USE_OPENAI_TRIAGE and OPENAI_API_KEY:
        return triage_with_openai(event)
    return llm.triage(event)
