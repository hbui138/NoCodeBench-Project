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

    # Bóc tách dữ liệu
    patch = run_result.get("model_patch", "")
    usage = run_result.get("token_usage", {"prompt": 0, "completion": 0, "total": 0})
    is_success = run_result.get("eval_summary", {}) # Lấy từ field mới hợp nhất

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
    
    return result

# ==========================================
# 2. Run BATCH API (ASYNC)
# ==========================================
@app.post("/batch/start")
def start_batch(background_tasks: BackgroundTasks):
    service.initialize_paths(force_new=True)

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

def load_results_from_file():
    results = {}
    
    # 1. Đọc dữ liệu cơ bản (Patch, Token)
    pred_file = service.MAIN_PREDICTIONS_FILE 
    if pred_file and os.path.exists(pred_file):
        with open(pred_file, "r") as f:
            for line in f:
                try:
                    data = json.loads(line)
                    iid = data['instance_id']
                    results[iid] = data
                    # Khởi tạo mặc định các trường eval
                    results[iid]['success'] = False
                    results[iid]['p2p_stats'] = {"success": [], "fail": []}
                    results[iid]['f2p_stats'] = {"success": [], "fail": []}
                except: pass

    # 2. Đọc dữ liệu chi tiết (Success, P2P, F2P)
    eval_details_path = os.path.join(service.LOG_DIR, "evaluation_details.jsonl")
    
    if os.path.exists(eval_details_path):
        with open(eval_details_path, "r") as f:
            for line in f:
                try:
                    eval_data = json.loads(line)
                    iid = eval_data.get('instance_id')
                    
                    if iid in results:
                        # Lưu trạng thái resolved (thành công tổng thể)
                        results[iid]['success'] = eval_data.get('resolved', False)
                        
                        # Lưu chi tiết P2P (Các test vốn đã pass, nay ntn?)
                        p2p_data = eval_data.get('P2P', {})
                        results[iid]['p2p_stats'] = {
                            "success": p2p_data.get('success', []),
                            "fail": p2p_data.get('failure', []) or p2p_data.get('fail', [])
                        }
                        
                        # Lưu chi tiết F2P (Các test vốn bị fail, nay có sửa được không?)
                        f2p_data = eval_data.get('F2P', {})
                        results[iid]['f2p_stats'] = {
                            "success": f2p_data.get('success', []),
                            "fail": f2p_data.get('failure', []) or f2p_data.get('fail', [])
                        }
                        
                        # Lưu chú thích nếu có (ví dụ: "Instance not attempted")
                        results[iid]['notes'] = eval_data.get('notes', "")
                except: pass
                
    return results

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)