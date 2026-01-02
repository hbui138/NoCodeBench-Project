# schemas.py
from pydantic import BaseModel
from typing import Optional, Any, Dict

class RunRequest(BaseModel):
    instance_id: str

class BatchStatusResponse(BaseModel):
    is_running: bool
    total: int
    processed: int
    current_task: str | None
    progress_percent: float
    latest_logs: list
    results_summary: list