# Shop Floor Assistance

A proof-of-concept backend where background agents watch a factory's machines, orders and safety logs, raise events, and a central router triages each event and runs the matching actions (stop a machine, schedule maintenance, reschedule an order, notify a role). A small React dashboard shows it live.

I built it during my AI engineering internship at September AI to try an event-driven, tool-calling agent design on a manufacturing scenario. Data lives in local JSON files, so there is no database to set up. Triage is rule-based by default and can use an OpenAI model with one environment flag.

## How it works

Everything flows through one queue. Three scanner loops read the JSON files and publish events (`{source, type, payload}`), and a single router consumes them.

- **Scanners** (`server/graph/agents_loops.py`): machines over 100 C raise `machine_upset` (every 8 s); orders due within 1 hour with under 80% progress raise `order_delay` (every 10 s); safety logs still `unresolved` are raised again (every 6 s).
- **Router** (`server/graph/engine.py`): `GlobalRouterGraph` pulls an event off an `asyncio.Queue`, triages it into a severity (S1 critical to S4 informational), category and list of tool calls, executes them, logs the result and broadcasts it over the WebSocket. A failing event does not stop the loop.
- **Triage** (`server/llm.py`): by default a rule table. Temperature >= 120 C is S1 (stop machine, schedule maintenance, critical notify). Temperature >= 100 C or vibration >= 1.2 is S2. Order delay >= 50% is S2 (push the order out 3 hours, notify planner) and 20 to 50% is S3. PPE and unsafe-zone safety events are S1. Anything else is S4 with no action. With `USE_OPENAI_TRIAGE=1` the event goes to an OpenAI chat model (`TRIAGE_MODEL`, default `gpt-4o`) with the JSON schema and examples from `server/prompts/triage_prompt.md`, and falls back to the rules if the call fails or the output is malformed.
- **Tools** (`server/tools/`): `stop_machine`, `schedule_maintenance`, `update_order`, `notify` and `log`. The production tools are simulated: they write an entry to the action log and return a status.
- **Supervisor** (`server/agents/supervisor_agent.py`): every 60 s it summarises the last hour of actions, escalates on 3 or more critical notifications, reschedules orders recently flagged as delayed, and writes one daily summary (state kept in `supervisor_state.json`).
- **Dashboard** (`frontend/`): four panels (Machines, Orders, Agent Workflow, Safety Logs). It polls the REST endpoints every 5 s and listens on the WebSocket for log, triage and safety-resolved messages. Resolving a safety log in the UI publishes a `safety_resolve` event through the same router.

### API

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/machines` | machine states |
| GET | `/orders` | orders |
| GET | `/safety_logs` | safety logs |
| GET | `/logs` | action log, newest first |
| GET | `/memory` | router counters and last triage |
| POST | `/publish_event` | inject an event; `?async_mode=true` queues it instead of processing inline |
| WS | `/ws` | live stream of log, triage and safety-resolved messages |

## Tech stack

- Backend: Python 3.10+, FastAPI, Uvicorn, Pydantic, asyncio, WebSockets
- Triage LLM (optional): OpenAI Python client
- Frontend: React 18 (Create React App)
- Storage: JSON files in `server/data/` with lock-guarded atomic writes

## Setup

```bash
pip install -r requirements.txt
cp .env.example .env
cd frontend && npm install && cd ..
```

Run the backend from the repo root and the dashboard in a second terminal:

```bash
uvicorn server.main:app --reload --port 8000
cd frontend && npm start
```

The API is on http://localhost:8000 and the dashboard on http://localhost:3000. The frontend reads `REACT_APP_API_URL` and `REACT_APP_WS_URL` if you need to point it elsewhere. For OpenAI triage set `OPENAI_API_KEY` and `USE_OPENAI_TRIAGE=1` in `.env`.

## Trying it

The seed data has one machine at 125 C, so the first scan raises an S1 and you will see an Event, Triage, Tools card in the Agent Workflow panel. To inject your own event:

```bash
curl -X POST http://localhost:8000/publish_event \
  -H "Content-Type: application/json" \
  -d '{"source":"UI","type":"machine_upset","payload":{"id":"M2","temperature":130}}'
```

The seed data is 3 machines, 3 orders and 1 safety log.

## Project structure

```
server/
  main.py            FastAPI app, REST and WebSocket endpoints, startup tasks
  config.py          env config
  llm.py             rule-based triage and optional OpenAI triage
  realtime.py        WebSocket manager
  graph/             router engine, scanner loops, triage, tool dispatch, state models
  agents/            supervisor loop
  tools/             production, notify and safety-log tools
  prompts/           triage prompt for the OpenAI path
  data/              JSON store
  static/            demo_dashboard.html
frontend/src/        React dashboard
setup_chatbot_index.py   unfinished Pinecone index script (see below)
```

## Limitations

- It is a proof of concept. Actions are simulated and nothing has been run against real equipment.
- `setup_chatbot_index.py` imports `server.chatbot.helper`, which is not in the repo, so it does not run. `.env.example` also lists MySQL, Pinecone and Groq settings that the current code does not use.
- `langchain` and `langchain-openai` are pinned in `requirements.txt` but the server code does not import them.
