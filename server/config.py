import os
from dotenv import load_dotenv
load_dotenv()

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
MONITOR_MODEL = os.getenv("MONITOR_MODEL", "gpt-4.1-mini")
TRIAGE_MODEL = os.getenv("TRIAGE_MODEL", "gpt-4.1")
PORT = int(os.getenv("PORT", "8000"))
USE_OPENAI_TRIAGE = os.getenv("USE_OPENAI_TRIAGE", "0").strip() in ("1", "true", "True")

DATA_DIR = os.path.join(os.path.dirname(__file__), "data")
LOG_FILE = os.path.join(DATA_DIR, "action_log.json")
