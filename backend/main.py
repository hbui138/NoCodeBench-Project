# main.py
from fastapi import FastAPI, HTTPException, BackgroundTasks
from datasets import load_dataset
from contextlib import asynccontextmanager
from fastapi.middleware.cors import CORSMiddleware
import os
import json

import state
import schemas
import service 

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

# --- HELPER: Load tasks ---
# --- 1. LIFESPAN ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    print("\n⏳ [STARTUP] Downloading & Loading Dataset from Hugging Face...")
    try:
        ds = load_dataset('NoCode-bench/NoCode-bench_Verified', split='test')

        # Get first k items for testing
        # ds = ds.select([i for i in list(range(2))])
        
        state.data_map = {}
        count = 0
        for item in ds:
            # Change row to dict
            t = dict(item)
            
            t_id = t.get('instance_id')
            if t_id:
                t['id'] = t_id
                state.data_map[t_id] = t
                count += 1
                
        print(f"✅ [STARTUP] Successfully loaded {count} tasks into memory.")
        
    except Exception as e:
        print(f"❌ [STARTUP ERROR] Could not load dataset: {e}")
    
    yield
    
    print("🛑 [SHUTDOWN] Cleaning up resources...")
    state.data_map.clear()

# --- 2. APP CONFIGURATION ---
app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware, 
    allow_origins=["*"], 
    allow_methods=["*"], 
    allow_headers=["*"]
)

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
        "mask_doc_diff": item.get('mask_doc_diff'),
        "feature_patch": item.get('feature_patch', "")
    }

@app.get("/results/{instance_id}")
def get_task_result(instance_id: str):
    service.initialize_paths()
    all_results = load_results_from_file()

    task_info = state.data_map.get(instance_id)
    if not task_info: raise HTTPException(404, "Task not found")

    all_results = load_results_from_file()
    run_result = all_results.get(instance_id, {})

    patch = run_result.get("model_patch", "")
    usage = run_result.get("token_usage", {"prompt": 0, "completion": 0, "total": 0})
    is_success = run_result.get("success", False)

    return {
        "info": {
            "repo": task_info['repo'],
            "base_commit": task_info['base_commit']
        },
        "result": {
            "patch": patch,
            "success": is_success, # <--- Field Success mới
            "token_usage": usage,
            "p2p": run_result.get("p2p_stats", {}),
            "f2p": run_result.get("f2p_stats", {}),
            "notes": run_result.get("notes", ""),
            "status": "Completed" if run_result else "Pending"
        }
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
    service.initialize_paths(force_new=True)

    # Gọi logic từ service
    result = service.run_task_logic(req.instance_id, is_batch_mode=False)
    service.run_final_aggregation_and_cleanup()
    return result

# ==========================================
# 2. Run BATCH API (ASYNC)
# ==========================================
@app.post("/batch/start")
def start_batch(req: schemas.BatchStartRequest, background_tasks: BackgroundTasks):
    service.initialize_paths(force_new=True)

    if state.batch_state.is_running:
        raise HTTPException(400, "Batch is already running")
    # Logic lọc số lượng

    if req.ids and len(req.ids) > 0:
        target_ids = req.ids
        print(f"🎯 [MODE: SELECTED] Running {len(target_ids)} tasks provided by Client.")
    elif req.limit > 0:
        all_ids = list(state.data_map.keys())
        target_ids = all_ids[:req.limit]
        print(f"✂️ [MODE: LIMIT] Running first {req.limit} tasks.")
    else:
        target_ids = list(state.data_map.keys())
        print(f"🚀 [MODE: FULL] Running ALL {len(target_ids)} tasks.")

    if not target_ids:
        raise HTTPException(400, "No tasks found to run.")

    background_tasks.add_task(service.run_batch_process, target_ids)
    return {
        "status": "success", 
        "message": f"Started batch for {len(target_ids)} tasks",
        "count": len(target_ids)
    }

@app.get("/batch/status", response_model=schemas.BatchStatusResponse)
def get_batch_status():
    """Client calls this endpoint periodically to get batch status."""
    s = state.batch_state

    percent = 0.0
    if s.total_tasks > 0:
        percent = (s.processed_count / s.total_tasks) * 100

    return {
        "is_running": s.is_running,
        "processed": s.processed_count,
        "total": s.total_tasks,
        "current_task": None,
        "progress_percent": round(percent, 2),
        "latest_logs": s.logs[-10:] if hasattr(s, 'logs') else [],
        "results_summary": s.results if hasattr(s, 'results') else []
    }

@app.post("/batch/stop")
def stop_batch():
    state.batch_state.stop()
    return {"message": "Stop signal sent (not fully implemented)"}

def load_results_from_file():
    results = {}
    
    # 1. Read main predictions file
    pred_file = service.MAIN_PREDICTIONS_FILE 
    if pred_file and os.path.exists(pred_file):
        with open(pred_file, "r") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    iid = data['instance_id']
                    results[iid] = data
                    # Initialize fields in case missing
                    results[iid]['success'] = False
                    results[iid]['p2p_stats'] = {"success": [], "fail": []}
                    results[iid]['f2p_stats'] = {"success": [], "fail": []}
                except: pass

    # 2. Read evaluation details file to enrich resultss
    eval_details_path = os.path.join(service.LOG_DIR, "evaluation_details.jsonl")
    
    if os.path.exists(eval_details_path):
        with open(eval_details_path, "r") as f:
            for line in f:
                try:
                    eval_data = json.loads(line)
                    iid = eval_data.get('instance_id')
                    
                    if iid in results:
                        # Save overall success flag
                        results[iid]['success'] = eval_data.get('resolved', False)
                        
                        # Save detailed P2P stats
                        p2p_data = eval_data.get('P2P', {})
                        results[iid]['p2p_stats'] = {
                            "success": p2p_data.get('success', []),
                            "fail": p2p_data.get('failure', []) or p2p_data.get('fail', [])
                        }
                        
                        # Save detailed F2P stats
                        f2p_data = eval_data.get('F2P', {})
                        results[iid]['f2p_stats'] = {
                            "success": f2p_data.get('success', []),
                            "fail": f2p_data.get('failure', []) or f2p_data.get('fail', [])
                        }
                        
                        # Notes field
                        results[iid]['notes'] = eval_data.get('notes', "")
                except: pass
                
    return results

@app.get("/batch/report")
def get_batch_report():
    """API endpoint to get summary report content."""
    content = service.get_summary_report_content()
    if content is None:
        return {"content": "No active run directory found."}
    return {"content": content}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)