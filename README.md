# Shop Floor Assistant

**A graph-style multi-agent backend that watches a factory floor's machines, orders and safety logs, triages events, and takes action automatically, with a live React dashboard on top.**

![Python](https://img.shields.io/badge/Python-3776AB?style=flat&logo=python&logoColor=white) ![FastAPI](https://img.shields.io/badge/FastAPI-009688?style=flat&logo=fastapi&logoColor=white) ![Uvicorn](https://img.shields.io/badge/Uvicorn-2A6DB0?style=flat&logo=gunicorn&logoColor=white) ![WebSockets](https://img.shields.io/badge/WebSockets-010101?style=flat&logo=socketdotio&logoColor=white) ![React](https://img.shields.io/badge/React-61DAFB?style=flat&logo=react&logoColor=black) ![OpenAI](https://img.shields.io/badge/OpenAI-412991?style=flat&logo=openai&logoColor=white)

## Overview

Shop Floor Assistant is a proof-of-concept for agentic manufacturing operations. Instead of an operator watching every machine reading, order deadline and safety log by hand, a set of background agents scans those data sources, raises events when something looks wrong, and a central router decides how serious each event is and which actions to fire: stop a machine, schedule maintenance, reschedule an order, or notify the right role.

The backend is a single FastAPI service. At its core is a global router "graph": a long-running async loop that pulls events off a queue, runs each through a triage step, and executes the tools the triage step asks for. Every action is appended to a shared action log and pushed out over WebSockets, so the React dashboard shows machines, orders, safety logs and the agent's decision-to-action workflow updating in near real time.

I built this during an AI engineering internship at September AI to try an event-driven, tool-calling agent design on a manufacturing scenario. It uses local JSON files as the data store, so there is no database to set up. Triage is rule-based by default and can be switched to an OpenAI model with one environment flag. The actions are simulated, and nothing has been run against real equipment.

## Key Features

- **Background monitoring agents:** three async loops scan the data store on independent intervals:
  - *Shop Floor loop* (every 8s): flags any machine whose temperature is over 100°C as a `machine_upset` event.
  - *Order loop* (every 10s): flags orders due within 1 hour but under 80% progress as `order_delay`, with a delay percentage.
  - *Safety loop* (every 6s): re-raises any safety log still marked `unresolved`.
- **Global router graph:** a singleton `GlobalRouterGraph` backed by an `asyncio.Queue`. It takes events one at a time, triages each, routes the resulting tool calls, executes them and records the outcome. A single bad event does not crash the loop.
- **Configurable triage:** by default a rule-based `MockLLM` assigns a severity tier and a list of tool calls per event. Set `USE_OPENAI_TRIAGE=1` and it calls an OpenAI chat model and parses strict-JSON triage output instead, falling back to the rules if the call fails or returns malformed JSON.
- **Severity tiers (S1–S4):** events are graded from S1 (critical: production stop or safety hazard) down to S4 (informational), and each tier maps to a different set of actions.
- **Tool execution layer:** a fixed tool registry (`stop_machine`, `schedule_maintenance`, `update_order`, `notify`, `log`) that the router dispatches by name with arguments. Unknown tool names return an `unknown_tool` result instead of throwing.
- **Supervisor agent:** a separate loop (every 60s) that summarizes the last hour of actions, escalates on 3 or more critical notifications, reschedules orders recently flagged as delayed, and writes a once-per-day summary, with state saved to disk.
- **Real-time dashboard:** a React single-page app with four panels (Machines, Orders, Agent Workflow, Safety Logs). It polls REST endpoints every 5 seconds and also opens a WebSocket for live log entries, triage workflow cards and safety-resolution updates.
- **Manual event injection:** the `/publish_event` endpoint lets you publish ad-hoc events to test scenarios, and the dashboard lets you resolve safety logs.
- **Append-only action log:** every tool call and agent decision is written to `action_log.json` through a lock-guarded, atomic temp-file-then-replace write, newest first.
- **In-memory analytics:** the router keeps a `MemoryState` (events processed, counts by category, counts by severity, last triage), exposed at `/memory`.

## How It Works

The whole system is event-driven. Data lives in JSON files; agents read those files, decide whether something is worth raising, and publish events to one central queue. The router is the only thing that acts.

### 1. Data and agent loops

The data store is JSON files under `server/data/`: `machines.json`, `orders.json`, `safety_logs.json`, the append-only `action_log.json` and `supervisor_state.json`. On startup, FastAPI launches all the background loops as asyncio tasks (`shopfloor_loop`, `order_loop`, `safety_log_loop`, the supervisor `loop`, and the router's `run_loop`).

Each scanner loop is a simple `while True` that reads its file, checks a condition, and publishes an event dict (`{source, type, payload}`) onto the global queue. For example, the shop floor loop raises a `machine_upset` for any machine over 100°C, and the order loop raises an `order_delay` carrying the computed `delay_percent`.

### 2. The router graph

`GlobalRouterGraph.run_loop()` waits on the queue, then runs `process_one()` for each event:

1. **Triage:** the event is validated into a Pydantic `Event` and passed to the triage function, which returns a `TriageOutput` with a severity, a category, a short rationale and a list of `ToolCall`s.
2. **Route and execute:** `event_router.route_and_execute()` walks the tool calls, normalizes each one and runs it through the tool registry. Results are collected.
3. **Log and broadcast:** the event, the triage decision and the executed tools are logged, and the combined result is broadcast over WebSocket as a `triage` message (the dashboard turns it into an Event → Triage → Tools workflow card).
4. **Memory update:** counters for events processed, category and severity are updated.
5. **Dynamic safety resolution:** if the event came from the safety agent or is an explicit `safety_resolve`, the matching safety log is marked resolved and a `safety_resolved` message is pushed to clients.

### 3. Triage logic

There are two triage paths, selected by the `USE_OPENAI_TRIAGE` flag:

- **Rule-based mock (default).** A rule table in `server/llm.py`. The actual rules:
  - Machine over/upset: temp ≥ 120°C → **S1** (`stop_machine` + `schedule_maintenance` + critical notify); temp ≥ 100°C or vibration ≥ 1.2 → **S2** (warning notify).
  - Order delay: delay ≥ 50% → **S2** (`update_order` to 3h + planner notify); 20–50% → **S3** (info notify).
  - Safety (`ppe_missing` / `unsafe_zone_entry` / `ppe_violation`) → **S1** (critical supervisor notify).
  - Anything else → **S4 / Unknown**, no actions.
- **OpenAI triage (optional).** When enabled, the event is sent to an OpenAI chat model (`TRIAGE_MODEL`, default `gpt-4o`) with a strict-JSON instruction; the response is parsed and shape-checked, and any error falls back to the rules. `server/prompts/triage_prompt.md` holds the JSON schema, severity guidance and few-shot examples for this path.

### 4. Tools

The tool registry maps names to functions in `server/tools/`. `stop_machine`, `schedule_maintenance` and `update_order` are "production" actions; `notify` sends a role-targeted message at a level (info/warning/critical); `log` records a generic event. In this PoC the production tools are simulated: they write a structured entry to the action log and return a status, so the code shows what would be called without touching real machinery.

### 5. Supervisor

The supervisor loop is the higher-level overseer. Every 60 seconds it reads the action log, builds an hourly summary grouped by action type, escalates if it sees 3+ critical notifications in the window, collects order IDs that were flagged as delayed and reschedules them, and emits a daily summary once per day (tracked in `supervisor_state.json`).

### 6. Frontend

The React app (`frontend/`) renders four panels and keeps them fresh two ways: a 5-second interval that re-fetches `/machines`, `/orders`, `/logs` and `/safety_logs`, plus a WebSocket (`connectStream`) that handles `log`, `triage` and `safety_resolved` push messages. The Workflow panel renders each triage result as a three-step card (Event → Triage → Tools) with severity-coloured badges. The Safety panel lets an operator mark a log resolved, which publishes a `safety_resolve` event back through the same router.

### API surface

| Method | Endpoint | Purpose |
| --- | --- | --- |
| GET | `/machines` | Current machine states |
| GET | `/orders` | Current orders |
| GET | `/safety_logs` | Safety logs |
| GET | `/logs` | Action log (newest first) |
| GET | `/memory` | Router memory snapshot (counts, last triage) |
| POST | `/publish_event` | Inject an event; `?async_mode=true` enqueues, otherwise processes synchronously |
| WS | `/ws` | Live stream of log, triage and safety-resolved messages |

## Triage Rules and Demo Data

There are no benchmark or performance numbers here; it's a PoC, not a tuned system. What's concrete is the behaviour and the seed data:

- **Severity model:** four tiers, S1 (critical) to S4 (informational), each mapping to a distinct action set.
- **Thresholds:** machine S1 at ≥ 120°C, S2 at ≥ 100°C or vibration ≥ 1.2; order delay S2 at ≥ 50%, S3 at 20–50%; safety violations always S1.
- **Loop cadence:** shop floor 8s, orders 10s, safety 6s, supervisor 60s.
- **Seed dataset:** 3 machines (one already at 125°C / vibration 1.5, which triggers an S1 on the first scan), 3 orders (one due in 0.5h at 90%, one due in 1h at 20%) and 1 safety log. That is enough to see the full event → triage → action → log → dashboard cycle as soon as the server starts.

## Tech Stack

- **Languages:** Python (backend), JavaScript / JSX (frontend), HTML/CSS.
- **Backend frameworks/libraries:** FastAPI, Uvicorn, Pydantic, `python-dotenv`, native `asyncio` (queue + background tasks), WebSockets.
- **AI / LLM:** OpenAI Python client for the optional triage path (default model `gpt-4o`); a rule-based mock as the default and fallback. `langchain` / `langchain-openai` are pinned in `requirements.txt`, but only the unused `server/agents/triage_agent.py` imports LangChain. The live triage path is `server/llm.py`.
- **Frontend:** React 18 with Create React App (`react-scripts`), REST + WebSocket client.
- **Data store:** local JSON files with atomic, lock-guarded writes, so no database is needed to run.

## Getting Started

### Prerequisites
- Python 3.10+ (the code uses `int | None` / `dict | ToolCall` union syntax)
- Node.js 16+ and npm (for the dashboard)
- An OpenAI API key, only if you want the LLM triage path; the default rules need nothing

### Installation
```bash
git clone https://github.com/DCode-v05/Shop-Floor-Assistant.git
cd Shop-Floor-Assistant

# Backend deps
pip install -r requirements.txt

# Environment file
cp .env.example .env   # then edit as needed

# Frontend deps
cd frontend
npm install
cd ..
```

`.env.example` also lists MySQL, Pinecone, Groq, Chroma and email settings that the current code does not use. Only the OpenAI and triage settings matter.

### Running
```bash
# Backend (from repo root)
uvicorn server.main:app --reload --port 8000

# Frontend (in a second terminal)
cd frontend
npm start
```

The API serves on `http://localhost:8000` and the dashboard on `http://localhost:3000`. The React app reads `REACT_APP_API_URL` / `REACT_APP_WS_URL` if you need to point it elsewhere.

## Usage

1. Start the backend, then the frontend, and open `http://localhost:3000`.
2. The seed `machines.json` already has a machine at 125°C, so the shop floor loop raises an S1 within seconds. Watch the **Agent Workflow** panel produce an Event → Triage → Tools card and the action log fill in.
3. **Machines / Orders** panels reflect the JSON store (refreshed every 5s). **Safety Logs** lets you click *Mark Resolved*, which publishes a `safety_resolve` event.
4. To run your own scenario, POST an event:
   ```bash
   curl -X POST http://localhost:8000/publish_event \
     -H "Content-Type: application/json" \
     -d '{"source":"UI","type":"machine_upset","payload":{"id":"M2","temperature":130}}'
   ```
   Add `?async_mode=true` to enqueue and return immediately instead of processing inline.
5. To use OpenAI triage instead of the rules, set `OPENAI_API_KEY` and `USE_OPENAI_TRIAGE=1` in `.env` (optionally `TRIAGE_MODEL`), then restart.
6. Call `GET /memory` at any point for a running tally of events processed and counts by category and severity.

## Project Structure

```
Shop-Floor-Assistant/
├── server/                      # FastAPI backend
│   ├── main.py                  # App, REST + WS endpoints, startup tasks
│   ├── config.py                # Env config (models, flags, paths)
│   ├── llm.py                   # MockLLM rules + optional OpenAI triage
│   ├── realtime.py              # WebSocket connection manager + broadcasts
│   ├── graph/
│   │   ├── engine.py            # GlobalRouterGraph: queue, process_one, run_loop
│   │   ├── agents_loops.py      # Shop floor / order / safety scan loops
│   │   ├── triage_graph.py      # Event -> TriageOutput
│   │   ├── event_router.py      # Routes triage tool calls to executors
│   │   ├── tool_nodes.py        # Tool registry + dispatch
│   │   ├── runner.py            # Synchronous single-event entry point
│   │   └── state.py             # Pydantic Event / ToolCall / TriageOutput / MemoryState
│   ├── agents/
│   │   ├── supervisor_agent.py  # Hourly summaries, escalation, daily report
│   │   └── triage_agent.py      # LangChain-based triage agent, not imported anywhere
│   ├── tools/
│   │   ├── production_tools.py  # stop_machine, schedule_maintenance, update_order, atomic log
│   │   ├── notify_tools.py      # Role-targeted notifications
│   │   └── safety_store.py      # Load + mark-resolved for safety logs
│   ├── prompts/triage_prompt.md # LLM triage schema, severity guide, few-shot
│   ├── data/                    # JSON store: machines, orders, safety, action_log, supervisor_state
│   └── static/demo_dashboard.html
├── frontend/                    # React dashboard (CRA)
│   └── src/
│       ├── App.js               # Layout, polling + WebSocket wiring
│       ├── api.js               # REST + WS client
│       └── components/          # Machines / Orders / SafetyLogs / Triage / Workflow panels
├── setup_chatbot_index.py       # Unfinished Pinecone index script: imports server.chatbot.helper, which is not in the repo, so it does not run
├── requirements.txt
├── .env.example
├── .gitignore
└── README.md
```

---

## Contact

<table>
  <tr><td><b>Portfolio:</b> <a href="https://www.denistan.me">Denistan</a></td><td><b>LinkedIn:</b> <a href="https://www.linkedin.com/in/denistanb">denistanb</a></td></tr>
  <tr><td><b>GitHub:</b> <a href="https://github.com/DCode-v05">DCode-v05</a></td><td><b>LeetCode:</b> <a href="https://leetcode.com/u/Denistan_B">Denistan_B</a></td></tr>
  <tr><td colspan="2" align="center"><b>Email:</b> <a href="mailto:denistanb05@gmail.com">denistanb05@gmail.com</a></td></tr>
</table>

Made with ❤️ by **Denistan B**
