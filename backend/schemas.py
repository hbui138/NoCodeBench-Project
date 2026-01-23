# schemas.py
from pydantic import BaseModel
from typing import Optional, Any, Dict, List

class RunRequest(BaseModel):
    instance_id: str

class BatchStartRequest(BaseModel):
    limit: int = 0
    ids: Optional[List[str]] = None

class BatchStatusResponse(BaseModel):
    is_running: bool
    total: int
    processed: int
    current_task: str | None
    progress_percent: float
    latest_logs: list
    results_summary: list