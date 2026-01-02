# main.py
from fastapi import FastAPI, HTTPException, BackgroundTasks
from datasets import load_dataset
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware

import state
import schemas
import service 

# --- LIFESPAN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("⏳ Loading Dataset...")
    ds = load_dataset('NoCode-bench/NoCode-bench_Verified', split='test')
    state.data_map = {item['instance_id']: item for item in ds}
    print(f"✅ Loaded {len(state.data_map)} tasks.")
    yield

app = FastAPI(lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- API ROUTES ---

@app.get("/tasks")
def get_all_tasks():
    # Return list of all tasks
    return [{"id": k, "project": v['repo'], "status": "Ready"} for k, v in state.data_map.items()]

@app.get("/tasks/{instance_id}")
def get_task_detail(instance_id: str):
    item = state.data_map.get(instance_id)
    if not item: raise HTTPException(404, "Not found")
    display_diff = item.get('mask_doc_diff') or item.get('problem_statement')
    # Return detailed info about a specific task
    return {
        "instance_id": item['instance_id'],
        "repo": item['repo'],
        "doc_changes": display_diff,
        "augmentations": item.get('augmentations', {}),
        "base_commit": item['base_commit'],
        "problem_statement": item['problem_statement'],
        "mask_doc_diff": item.get('mask_doc_diff')
    }

# ==========================================
# 1. Run SINGLE TASK API (SYNC)
# ==========================================
@app.post("/run")
def run_single(req: schemas.RunRequest):
    """
    This endpoint runs a single task synchronously.
    """
    print(f"User requested single run for: {req.instance_id}")
    
    # Gọi logic từ service
    result = service.run_task_logic(req.instance_id, is_batch_mode=False)
    
    return result

# ==========================================
# 2. Run BATCH API (ASYNC)
# ==========================================
@app.post("/batch/start")
def start_batch(background_tasks: BackgroundTasks):
    if state.batch_state.is_running:
        raise HTTPException(400, "Batch is already running")
    
    all_ids = list(state.data_map.keys())
    background_tasks.add_task(service.run_batch_process, all_ids)
    return {"message": f"Started batch for {len(all_ids)} tasks"}

@app.get("/batch/status")
def get_batch_status():
    s = state.batch_state
    return {
        "is_running": s.is_running,
        "processed": s.processed_count,
        "total": s.total_tasks,
        "logs": s.logs[-10:]
    }

@app.post("/batch/stop")
def stop_batch():
    state.batch_state.stop()
    return {"message": "Stopping..."}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)