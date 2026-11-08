from server.graph.engine import GLOBAL_GRAPH

async def run_event(ev: dict):
    return await GLOBAL_GRAPH.process_one(ev)
