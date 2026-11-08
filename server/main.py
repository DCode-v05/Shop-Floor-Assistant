import asyncio, os, json
from fastapi import FastAPI, HTTPException, Query, WebSocket
from fastapi.websockets import WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from server.graph.runner import run_event
from server.graph.agents_loops import shopfloor_loop, order_loop, safety_log_loop
from server.graph.engine import GLOBAL_GRAPH
from server.agents.supervisor_agent import loop as supervisor_loop
from server.realtime import MANAGER
from server.tools.production_tools import log_event
from server.config import DATA_DIR

app = FastAPI(title="Agentic Manufacturing - LangGraph PoC")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

def read_json(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path) as f:
            return json.load(f)
    except Exception:
        return []

@app.get("/machines")
def machines():
    return read_json(os.path.join(DATA_DIR,"machines.json"))

@app.get("/orders")
def orders():
    return read_json(os.path.join(DATA_DIR,"orders.json"))

@app.get("/safety_logs")
def safety_logs():
    return read_json(os.path.join(DATA_DIR,"safety_logs.json"))

@app.get("/logs")
def logs():
    return read_json(os.path.join(DATA_DIR,"action_log.json"))

@app.post("/publish_event")
async def publish_event(event: dict, async_mode: bool = Query(False, description="If true, enqueue and return immediately")):
    try:
        if async_mode:
            await GLOBAL_GRAPH.publish(event)
            return {"status":"ok","enqueued": True}
        res = await run_event(event)
        return {"status":"ok","result":res, "enqueued": False}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.on_event("startup")
async def startup_event():
    loop = asyncio.get_event_loop()
    loop.create_task(shopfloor_loop())
    loop.create_task(order_loop())
    loop.create_task(safety_log_loop())
    loop.create_task(GLOBAL_GRAPH.run_loop())
    loop.create_task(supervisor_loop())
    log_event({"actor":"system","action":"startup","msg":"Background agent loops started."})

@app.get("/memory")
def memory_state():
    return GLOBAL_GRAPH.snapshot_memory()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await MANAGER.connect(ws)
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        MANAGER.disconnect(ws)
