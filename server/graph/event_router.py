from server.graph.tool_nodes import execute_tool_call, _normalize_call

def route_and_execute(triage_output):
    results = []
    for call in triage_output.tools_to_call or []:
        norm = _normalize_call(call)
        res = execute_tool_call(call)
        results.append({"call": norm, "result": res})
    return results
