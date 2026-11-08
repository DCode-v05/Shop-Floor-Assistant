import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Dict, Any, List
from server.tools.production_tools import log_event
from server.tools.notify_tools import notify
from server.config import DATA_DIR
from server.tools.production_tools import update_order_schedule

LOG_FILE = os.path.join(DATA_DIR, "action_log.json")
STATE_FILE = os.path.join(DATA_DIR, "supervisor_state.json")


def _read_logs(limit: int | None = None):
    if not os.path.exists(LOG_FILE):
        return []
    try:
        logs = json.load(open(LOG_FILE))
        return logs if limit is None else logs[:limit]
    except Exception:
        return []


def summarize_last_period(minutes: int = 60) -> Dict[str, Any]:
    logs = _read_logs()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    def parse_ts(e):
        try:
            ts = e.get("timestamp", "")
            dt = datetime.fromisoformat(ts)
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    recent = [e for e in logs if (ts := parse_ts(e)) and ts >= cutoff]

    summary: Dict[str, Any] = {
        "window_minutes": minutes,
        "total_actions": len(recent),
        "by_action": {},
        "notifies": [],
    }

    for e in recent:
        action = e.get("action")
        summary["by_action"][action] = summary["by_action"].get(action, 0) + 1
        if action == "notify":
            summary["notifies"].append(e)

    return summary


def _load_state() -> Dict[str, Any]:
    if os.path.exists(STATE_FILE):
        try:
            return json.load(open(STATE_FILE))
        except Exception:
            return {}
    return {}


def _save_state(state: Dict[str, Any]):
    try:
        json.dump(state, open(STATE_FILE, "w"), indent=2)
    except Exception:
        pass


def _collect_recent_order_delays(minutes: int = 60) -> List[str]:
    logs = _read_logs()
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    order_ids: List[str] = []
    def parse_ts(e):
        try:
            dt = datetime.fromisoformat(e.get("timestamp", ""))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except Exception:
            return None
    for e in logs:
        ts = parse_ts(e)
        if not ts or ts < cutoff:
            continue
        evt = e.get("event") or {}
        tri = e.get("triage") or {}
        if isinstance(evt, dict) and evt.get("type") == "order_delay":
            payload = evt.get("payload", {})
            oid = payload.get("order_id")
            if oid:
                order_ids.append(oid)
    return list(dict.fromkeys(order_ids))


async def loop(interval_seconds: int = 60):
    while True:
        try:
            summary = summarize_last_period(minutes=60)
            log_event({"agent": "SupervisorAgent", "summary": summary})
            criticals = [n for n in summary.get("notifies", []) if n.get("level") == "critical"]
            if len(criticals) >= 3:
                notify("supervisor", f"Escalation: {len(criticals)} critical events in last hour", "critical")

            delayed_orders = _collect_recent_order_delays(minutes=60)
            for oid in delayed_orders:
                update_order_schedule(oid, new_due_in_hours=2)
                notify("planner", f"Order {oid} auto-rescheduled by SupervisorAgent", "info")

            st = _load_state()
            last_day = st.get("last_daily_summary")
            today = datetime.now(timezone.utc).date().isoformat()
            if last_day != today:
                day_summary = summarize_last_period(minutes=24*60)
                log_event({"agent": "SupervisorAgent", "daily_summary": day_summary})
                notify("supervisor", "Daily summary logged by SupervisorAgent", "info")
                st["last_daily_summary"] = today
                _save_state(st)
        except Exception as e:
            log_event({"agent": "SupervisorAgent", "error": str(e)})
        await asyncio.sleep(interval_seconds)
