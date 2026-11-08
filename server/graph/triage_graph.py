from server.llm import triage as triage_fn
from server.graph.state import TriageOutput, Event, ToolCall
from typing import Dict,Any

def triage_run(event: Event) -> TriageOutput:
    evdict = {"source": event.source, "type": event.type, "payload": event.payload}
    result = triage_fn(evdict)
    tools_list = result.get("tools_to_call", [])
    tri = TriageOutput(
        severity=result.get("severity","S4"),
        category=result.get("category","Unknown"),
        rationale=result.get("rationale",""),
        tools_to_call=[ToolCall(**t) if isinstance(t, dict) else t for t in tools_list]
    )
    return tri
