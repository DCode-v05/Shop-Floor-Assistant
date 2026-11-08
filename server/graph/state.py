from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List

class Event(BaseModel):
    source: str
    type: str
    payload: Dict[str,Any] = {}

class ToolCall(BaseModel):
    name: str
    args: Dict[str,Any] = {}

class TriageOutput(BaseModel):
    severity: str
    category: str
    rationale: str
    tools_to_call: List[ToolCall] = Field(default_factory=list)

class MemoryState(BaseModel):
    events_processed: int = 0
    counts_by_category: Dict[str, int] = Field(default_factory=dict)
    counts_by_severity: Dict[str, int] = Field(default_factory=dict)
    last_triage: Optional[TriageOutput] = None
