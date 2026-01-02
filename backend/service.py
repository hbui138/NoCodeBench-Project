# service.py
import os
import json
import subprocess
from agent import NoCodeAgent
from utils import setup_repo, read_local_file
import state

# --- CONSTANTS ---
PREDICTIONS_FILE = "all_preds.jsonl"
LOG_DIR = "evaluation/logs"

# --- AGENT INITIALIZATION ---
agent = NoCodeAgent(model_name="gemini-2.5-flash")

def run_task_logic(instance_id: str, is_batch_mode: bool = False):
    """
    This function encapsulates the logic to run a single task. It can be called both in single-task mode and batch mode.
    """
    
    # 1. Get Task Data
    task_data = state.data_map.get(instance_id)
    if not task_data:
        return {"status": "error", "detail": "Task not found"}

    print(f"\n🚀 [START] Processing task: {instance_id}")
    masked_input = task_data.get('mask_doc_diff') or task_data.get('problem_statement')
    augmentations = task_data.get('augmentations', {})

    # 2. Setup Repo
    success, repo_path_or_msg = setup_repo(task_data['repo'], task_data['base_commit'])
    if not success:
        return {"status": "error", "step": "setup_repo", "detail": repo_path_or_msg}
    repo_path = repo_path_or_msg

    # 3. Locate Files
    target_files = agent.locate_files(doc_diff=masked_input)

    # 4. Read Files
    code_context = {}
    if target_files:
        for rel_path in target_files:
            content = read_local_file(repo_path, rel_path)
            if content:
                code_context[rel_path] = content

    # 5. Generate Patch
    patch = agent.generate_patch(
        doc_diff=masked_input,
        augmentations=augmentations,
        code_context=code_context,
        instance_id=instance_id
    )

    if not patch:
        return {"status": "error", "step": "generation", "detail": "Empty patch"}

    # 6. Save Prediction
    # Note: In batch mode, we append to the same predictions file
    prediction_entry = {
        "model_name_or_path": agent.model_name,
        "instance_id": instance_id,
        "model_patch": patch
    }
    
    # If running in single-task mode, ensure the predictions file is clean
    if not is_batch_mode and os.path.exists(PREDICTIONS_FILE):
        # Optional: Remove old file if you want to run single tests cleanly
        # os.remove(PREDICTIONS_FILE) 
        pass 

    with open(PREDICTIONS_FILE, "a") as f:
        f.write(json.dumps(prediction_entry) + "\n")

    # 7. Run Docker Evaluation
    current_dir = os.path.dirname(os.path.abspath(__file__))
    root_dir = os.path.abspath(os.path.join(current_dir, '..'))
    bench_core_path = os.path.join(root_dir, 'bench-core')
    
    cmd = [
        "python", "evaluation/eval.py",
        "--predictions_path", os.path.abspath(PREDICTIONS_FILE),
        "--log_dir", os.path.abspath(LOG_DIR),
        "--bench_tasks", "NoCode-bench/NoCode-bench_Verified",
        "--image_level", "repo",
        "--max_workers", "1",
        "--timeout", "300"
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = bench_core_path + os.pathsep + env.get("PYTHONPATH", "")

    try:
        result = subprocess.run(
            cmd, cwd=bench_core_path, env=env,
            capture_output=True, text=True
        )
        
        output_log = result.stdout + "\nErrors:\n" + result.stderr
        is_passed = "PASSED" in output_log
        
        return {
            "status": "completed",
            "patch": patch,
            "read_files": list(code_context.keys()),
            "eval_output": output_log,
            "success": is_passed
        }

    except Exception as e:
        return {"status": "error", "step": "evaluation", "detail": str(e)}

def run_batch_process(task_ids: list):
    """Run batch processing logic"""
    state.batch_state.start(len(task_ids))
    
    if os.path.exists(PREDICTIONS_FILE):
        os.remove(PREDICTIONS_FILE)

    for i, t_id in enumerate(task_ids):
        if state.batch_state.stop_signal:
            break
        
        state.batch_state.current_task_id = t_id
        res = run_task_logic(t_id, is_batch_mode=True)
        
        # Update batch state
        status = "PASS" if res.get("success") else "FAIL"
        if res.get("status") == "error": status = "ERROR"
        
        state.batch_state.processed_count += 1
        state.batch_state.logs.append(f"[{i+1}] {t_id}: {status}")
    
    state.batch_state.finish()