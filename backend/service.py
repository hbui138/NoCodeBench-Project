# service.py
import os
import json
import subprocess
import concurrent.futures
import threading
import shutil
import uuid
from collections import deque
from datetime import datetime

from agent import NoCodeAgent
from utils import setup_repo, read_local_file, get_repo_structure
import state

# --- CONSTANTS ---
CURRENT_RUN_DIR = None
LOG_DIR = None
MAIN_PREDICTIONS_FILE = None
WORKSPACE_TEMP_DIR = None
ROOT_DIR = None

# --- FUNCTIONS ---
def initialize_paths(force_new=False):
    global CURRENT_RUN_DIR, LOG_DIR, MAIN_PREDICTIONS_FILE, WORKSPACE_TEMP_DIR, ROOT_DIR

    current_dir = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.abspath(os.path.join(current_dir, ".."))
    BASE_RESULTS_DIR = os.path.join(ROOT_DIR, "results")
    WORKSPACE_TEMP_DIR = os.path.join(ROOT_DIR, "workspace_temp")

    # Nếu gọi để chạy task mới (force_new=True) HOẶC lần đầu tiên khởi động mà chưa có folder nào
    if force_new or CURRENT_RUN_DIR is None:
        all_runs = []
        if os.path.exists(BASE_RESULTS_DIR):
            all_runs = [d for d in os.listdir(BASE_RESULTS_DIR) if d.startswith("results_")]

        # Chế độ Discovery: Nếu không ép tạo mới, hãy thử tìm folder mới nhất hiện có
        if not force_new and all_runs:
            latest_run = sorted(all_runs)[-1]
            CURRENT_RUN_DIR = os.path.join(BASE_RESULTS_DIR, latest_run)
            print(f"🔄 Recovered latest session: {latest_run}")
        else:
            # Chế độ Creation: Tạo timestamp mới
            TIMESTAMP = datetime.now().strftime("%Y%m%d_%H%M%S")
            CURRENT_RUN_DIR = os.path.join(BASE_RESULTS_DIR, f"results_{TIMESTAMP}")
            print(f"🆕 Created NEW session: {CURRENT_RUN_DIR}")

        # Cập nhật các biến đường dẫn
        LOG_DIR = os.path.join(CURRENT_RUN_DIR, "evaluation_logs")
        MAIN_PREDICTIONS_FILE = os.path.join(CURRENT_RUN_DIR, "all_preds.jsonl")

        os.makedirs(LOG_DIR, exist_ok=True)
        os.makedirs(WORKSPACE_TEMP_DIR, exist_ok=True)

# --- GLOBAL LOCKS ---
# Khóa để ghi vào file tổng an toàn
FILE_WRITE_LOCK = threading.Lock() 

def run_task_logic(instance_id: str, is_batch_mode: bool = False):
    initialize_paths()
    
    # [THREAD SAFETY] Initialize a new Agent instance per thread
    agent = NoCodeAgent(model_name="gemini-2.5-pro")
    agent.reset_task_tokens()

    task_data = state.data_map.get(instance_id)
    if not task_data:
        return {"status": "error", "detail": "Task not found"}

    print(f"\n🚀 [START] Processing task: {instance_id}")
    input_for_agent = task_data.get('problem_statement')

    if not input_for_agent:
        mask_diff = task_data.get('mask_doc_diff', "")
        if isinstance(mask_diff, list):
            input_for_agent = "\n".join([str(d.get('metadata', '')) for d in mask_diff])
        else:
            input_for_agent = mask_diff

        augs = task_data.get('augmentations', {}).get('data', [])
        aug_text = f"\nSuggested entity names: {', '.join(augs)}" if augs else ""

        input_for_agent = f"{input_for_agent}\n{aug_text}"

    input_for_agent = str(input_for_agent)

    # ==============================================================================
    # 1. REPO ISOLATION (Tạo thư mục code riêng)
    # ==============================================================================
    success, base_repo_path_or_msg = setup_repo(task_data['repo'], task_data['base_commit'])
    if not success:
        return {"status": "error", "step": "setup_repo", "detail": base_repo_path_or_msg}

    # Tạo folder tạm: workspace_temp/task_id_random
    unique_id = f"{instance_id}_{uuid.uuid4().hex[:6]}"
    working_repo_path = os.path.join(WORKSPACE_TEMP_DIR, unique_id)
    
    try:
        if os.path.exists(working_repo_path): shutil.rmtree(working_repo_path)
        shutil.copytree(base_repo_path_or_msg, working_repo_path)
    except Exception as e:
        return {"status": "error", "step": "repo_isolation", "detail": str(e)}

    # ==============================================================================
    # 2. AGENT GENERATION
    # ==============================================================================
    repo_structure = get_repo_structure(working_repo_path)
    target_files = agent.locate_files(doc_diff=input_for_agent, repo_structure=repo_structure)
    
    code_context = {}
    if target_files:
        for rel_path in target_files:
            content, real_path = read_local_file(working_repo_path, rel_path)
            if content: code_context[real_path] = content 

    patch_result = agent.generate_patch(
        doc_diff=input_for_agent,
        code_context=code_context,
        instance_id=instance_id
    )

    usage = getattr(agent, 'current_task_tokens', {"prompt": 0, "completion": 0, "total": 0})

    # Check if agent returned an overload error
    if isinstance(patch_result, dict) and patch_result.get("error_type") == "overload":
        # Clean up and return special status
        shutil.rmtree(working_repo_path, ignore_errors=True)
        return {
            "status": "error", 
            "detail": "api_overload_skip"  # Từ khóa để run_batch_process bắt được
        }

    # If normal string patch
    patch = patch_result

    if not patch:
        shutil.rmtree(working_repo_path, ignore_errors=True)
        return {"status": "error", "step": "generation", "detail": "Empty patch"}

    prediction_entry = {
        "model_name_or_path": agent.model_name,
        "instance_id": instance_id,
        "model_patch": patch,
        "token_usage": usage
    }

    # ==============================================================================
    # 3. FILE ISOLATION (create temp jsonl for this task)
    # ==============================================================================
    # Instead of appending to main_preds.jsonl directly, create a temp file for this task
    temp_jsonl_path = os.path.join(WORKSPACE_TEMP_DIR, f"temp_pred_{unique_id}.jsonl")
    
    # Make sure the directory exists
    os.makedirs(os.path.dirname(temp_jsonl_path), exist_ok=True)

    with open(temp_jsonl_path, "w") as f:
        f.write(json.dumps(prediction_entry) + "\n")

    # ==============================================================================
    # 4. RUN EVALUATION ON THIS SINGLE ENTRY
    # ==============================================================================
    current_dir = os.path.dirname(os.path.abspath(__file__))
    bench_core_path = os.path.abspath(os.path.join(current_dir, '..', 'bench-core'))
    
    cmd = [
        "python", "evaluation/eval.py",
        "--predictions_path", temp_jsonl_path, 
        "--log_dir", os.path.abspath(LOG_DIR),
        "--bench_tasks", "NoCode-bench/NoCode-bench_Verified",
        "--image_level", "repo",
        "--max_workers", "1",
        "--timeout", "300"
    ]

    env = os.environ.copy()
    env["PYTHONPATH"] = bench_core_path + os.pathsep + env.get("PYTHONPATH", "")
    
    eval_result_log = ""
    is_passed = False
    eval_error = None

    try:
        # Delete working repo after eval to save space
        shutil.rmtree(working_repo_path, ignore_errors=True)

        result = subprocess.run(
            cmd, cwd=bench_core_path, env=env,
            capture_output=True, text=True
        )
        eval_result_log = result.stdout + "\nErrors:\n" + result.stderr
        is_passed = "PASSED" in eval_result_log

    except Exception as e:
        eval_error = str(e)
    finally:
        # [CLEANUP] Delete temp jsonl file
        if os.path.exists(temp_jsonl_path):
            os.remove(temp_jsonl_path)

    if eval_error:
        return {"status": "error", "step": "evaluation", "detail": eval_error}

    # ==============================================================================
    # 5. WRITE TO MAIN PREDICTIONS FILE
    # ==============================================================================
    # Append to main predictions file with lock
    with FILE_WRITE_LOCK:
        with open(MAIN_PREDICTIONS_FILE, "a") as f:
            f.write(json.dumps(prediction_entry) + "\n")

    return {
        "status": "completed",
        "patch": patch,
        "eval_output": eval_result_log,
        "success": is_passed
    }

def run_final_aggregation_and_cleanup():
    initialize_paths()
    try:
        bench_core_path = os.path.abspath(os.path.join(ROOT_DIR, 'bench-core'))
        predictions_path = os.path.abspath(MAIN_PREDICTIONS_FILE)
        eval_details_path = os.path.join(LOG_DIR, "evaluation_details.jsonl")
        print(eval_details_path)

        if not os.path.exists(predictions_path):
            print(f"❌ Error: Cannot find {MAIN_PREDICTIONS_FILE}")
            return
        
        # Run final aggregation
        print(f"📊 Generating final summary report...")
        final_cmd = [
            "python", "evaluation/eval.py",
            "--predictions_path", predictions_path, 
            "--log_dir", os.path.abspath(LOG_DIR),
            "--bench_tasks", "NoCode-bench/NoCode-bench_Verified",
            "--image_level", "repo",
            "--max_workers", "4", 
            "--timeout", "300"
        ]

        env = os.environ.copy()
        env["PYTHONPATH"] = bench_core_path + os.pathsep + env.get("PYTHONPATH", "")

        subprocess.run(final_cmd, cwd=bench_core_path, env=env, check=True)

        task_details = []
        total_prompt = 0
        total_completion = 0
        total_all = 0

        token_data_map = {}
        with open(predictions_path, "r") as f:
            for line in f:
                try:
                    d = json.loads(line)
                    token_data_map[d['instance_id']] = d.get("token_usage", {})
                except: continue

        # Read evaluation details
        if os.path.exists(eval_details_path):
            with open(eval_details_path, "r") as f:
                for line in f:
                    try:
                        eval_data = json.loads(line)
                        iid = eval_data.get('instance_id')
                        if iid not in token_data_map: continue
                        
                        # Calculate P2P rate
                        p2p = eval_data.get('P2P', {})
                        p2p_passed = len(p2p.get('success', []))
                        p2p_total = p2p_passed + len(p2p.get('failure', []) or p2p.get('fail', []))
                        p2p_rate = (p2p_passed / p2p_total * 100) if p2p_total > 0 else 0

                        # Calculate F2P rate
                        f2p = eval_data.get('F2P', {})
                        f2p_passed = len(f2p.get('success', []))
                        f2p_total = f2p_passed + len(f2p.get('failure', []) or f2p.get('fail', []))
                        f2p_rate = (f2p_passed / f2p_total * 100) if f2p_total > 0 else 0

                        usage = token_data_map.get(iid, {})
                        total_prompt += usage.get("prompt", 0)
                        total_completion += usage.get("completion", 0)
                        total_all += usage.get("total", 0)

                        task_details.append(
                            f"{iid:<30} | P2P: {p2p_rate:>5.1f}% ({p2p_passed}/{p2p_total}) | F2P: {f2p_rate:>5.1f}% ({f2p_passed}/{f2p_total}) | Resolved: {str(eval_data.get('resolved')): <5}"
                        )
                    except: continue

        # Append detailed stats to summary report
        system_report_name = os.path.basename(predictions_path).replace(".jsonl", "") + "_summary_report.txt"
        summary_report_path = os.path.join(CURRENT_RUN_DIR, system_report_name)
        if os.path.exists(summary_report_path):
            avg_token = total_all / len(task_details) if task_details else 0
            
            detail_table = "\n".join(task_details)
            additional_stats = f"""
============================================================
DETAILED TASK PERFORMANCE
============================================================
{"INSTANCE ID":<30} | {"P2P RATE":<15} | {"F2P RATE":<15} | {"STATUS":<10}
{"-"*80}
{detail_table}

============================================================
AGGREGATED TOKEN USAGE STATS
============================================================
Total Tasks:           {len(task_details)}
Total Prompt Tokens:   {total_prompt:,}
Total Completion Tokens: {total_completion:,}
Total Tokens Consumed: {total_all:,}
AVERAGE TOKENS/TASK:   {avg_token:,.2f}
============================================================
"""
            with open(summary_report_path, "a", encoding="utf-8") as report_file:
                report_file.write(additional_stats)
            print(f"✅ Enhanced stats appended to {summary_report_path}")

        # Cleanup global temp workspace
        if os.path.exists(WORKSPACE_TEMP_DIR):
            print(f"🧹 Cleaning up global temp: {WORKSPACE_TEMP_DIR}")
            import time
            time.sleep(2) 
            shutil.rmtree(WORKSPACE_TEMP_DIR, ignore_errors=True)
            print("✨ Workspace temp cleared.")
    
    except Exception as e:
        print(f"❌ Error during final aggregation & cleanup: {e}")

def run_batch_process(task_ids: list):
    # Config
    MAX_WORKERS = 2
    MAX_TASK_RETRIES = 3 
    
    queue = deque([(t_id, 0) for t_id in task_ids])
    
    state.batch_state.start(len(task_ids))
    print(f"🚀 Starting Batch Loop for {len(task_ids)} tasks with {MAX_WORKERS} workers...")

    futures_map = {} 

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        while queue or futures_map:
            while queue and len(futures_map) < MAX_WORKERS:
                t_id, retry_count = queue.popleft()
                future = executor.submit(run_task_logic, t_id, is_batch_mode=True)
                futures_map[future] = (t_id, retry_count)
                print(f"▶️ Submitted: {t_id}")

            if futures_map:
                done, _ = concurrent.futures.wait(futures_map.keys(), return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    t_id, retry_count = futures_map.pop(future)
                    try:
                        res = future.result()
                        # Xử lý Retry 503...
                        is_overload = False
                        if res.get("status") == "error" and ("503" in str(res) or "overload" in str(res).lower()):
                            is_overload = True

                        if is_overload:
                            if retry_count < MAX_TASK_RETRIES:
                                print(f"🔄 Re-queuing {t_id}")
                                queue.append((t_id, retry_count + 1))
                            else:
                                print(f"❌ Failed {t_id}")
                                state.batch_state.processed_count += 1
                        else:
                            status = "PASS" if res.get("success") else "FAIL"
                            if res.get("status") == "error": status = "ERROR"
                            print(f"✅ Finished {t_id}: {status}")
                            state.batch_state.processed_count += 1
                    except Exception as e:
                        print(f"💥 Crash {t_id}: {e}")
                        state.batch_state.processed_count += 1

        pass

    state.batch_state.finish()
    print("\n✅ All threads finished. Starting Final Aggregation & Cleanup...")
    run_final_aggregation_and_cleanup()
    print("🎉 Batch Process Completed!")