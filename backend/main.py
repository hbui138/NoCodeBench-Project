import sys
import os
import json
import subprocess
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from datasets import load_dataset
from fastapi.middleware.cors import CORSMiddleware

# Import internal modules
from agent import NoCodeAgent
# Import utility functions for Repo handling
from utils import setup_repo, read_local_file 

# Add bench-core path to easily call eval script if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '../bench-core')))

app = FastAPI()

# Configure CORS to allow Frontend to call the API
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CONFIG ---
PREDICTIONS_FILE = "all_preds.jsonl"
LOG_DIR = "evaluation/logs"

# --- 1. LOAD DATASET (Run once when server starts) ---
print("⏳ Loading NoCode-bench Verified dataset...")
# Load dataset from HuggingFace
dataset = load_dataset('NoCode-bench/NoCode-bench_Verified', split='test')
# Convert to Dictionary for fast lookup by ID
data_map = {item['instance_id']: item for item in dataset}
print(f"✅ Dataset loaded! Ready to serve {len(data_map)} tasks.")

# Initialize Agent
agent = NoCodeAgent(model_name="gemini-2.5-flash")

# Model request body
class RunRequest(BaseModel):
    instance_id: str

# --- API ENDPOINTS ---

@app.get("/tasks")
def get_all_tasks():
    """Returns a summary list to display on the left menu"""
    summary = []
    for t_id, item in data_map.items():
        summary.append({
            "id": t_id,
            "project": item['repo'],
            "status": "Ready" # Placeholder for future status tracking
        })
    return summary[:50] # Return first 50 items for performance (or return all if desired)

@app.get("/tasks/{instance_id}")
def get_task_detail(instance_id: str):
    """Returns task details for Frontend display"""
    if instance_id not in data_map:
        raise HTTPException(status_code=404, detail="Task not found")
    
    item = data_map[instance_id]
    
    # Prioritize masked version for display
    display_diff = item.get('mask_doc_diff') or item.get('problem_statement')
    
    return {
        "instance_id": item['instance_id'],
        "repo": item['repo'],
        "doc_changes": display_diff,  # Display masked text diff
        "augmentations": item['augmentations'],
        "base_commit": item['base_commit'],
        "problem_statement": item['problem_statement'],
        "mask_doc_diff": item.get('mask_doc_diff', None)
    }

@app.post("/run")
def run_agent_and_evaluate(req: RunRequest):
    """
    Core Pipeline: 
    1. Setup Repo -> 2. Agent Locates Files -> 3. Read Files -> 4. Agent Writes Patch -> 5. Docker Eval
    """
    instance_id = req.instance_id
    if instance_id not in data_map:
        raise HTTPException(status_code=404, detail="Task not found")

    print(f"\n🚀 [START] Processing task: {instance_id}")
    task_data = data_map[instance_id]
    
    # Standard Input for Agent (Use Masked version to prevent data leakage)
    masked_input = task_data.get('mask_doc_diff') or task_data.get('problem_statement')
    augmentations = task_data.get('augmentations', {})

    # ---------------------------------------------------------
    # STEP 1: SETUP CONTEXT (REPO & COMMIT)
    # ---------------------------------------------------------
    print("1️⃣  Preparing Repository...")
    success, repo_path_or_msg = setup_repo(task_data['repo'], task_data['base_commit'])
    
    if not success:
        return {"status": "error", "step": "setup_repo", "detail": repo_path_or_msg}
    
    repo_path = repo_path_or_msg # Absolute path to the checked-out repo

    # ---------------------------------------------------------
    # STEP 2: AGENT LOCATES FILES (Localization)
    # ---------------------------------------------------------
    print("2️⃣  Agent is reading the problem to locate files to fix...")
    target_files = agent.locate_files(doc_diff=masked_input)
    print(f"   => Target: {target_files}")

    # ---------------------------------------------------------
    # STEP 3: READ REAL CODE FROM DISK
    # ---------------------------------------------------------
    code_context = {}
    if target_files:
        for rel_path in target_files:
            content = read_local_file(repo_path, rel_path)
            if content:
                code_context[rel_path] = content
            else:
                print(f"⚠️  File not found: {rel_path}")
    else:
        print("⚠️  Agent did not find any files to fix (Running in blind mode).")

    # ---------------------------------------------------------
    # STEP 4: AGENT WRITES PATCH (Generation)
    # ---------------------------------------------------------
    print("3️⃣  Agent is writing code patch...")
    patch = agent.generate_patch(
        doc_diff=masked_input,
        augmentations=augmentations,
        code_context=code_context, # Pass real code here
        instance_id=instance_id
    )

    if not patch:
        return {"status": "error", "step": "generation", "detail": "Agent returned empty patch."}

    # ---------------------------------------------------------
    # STEP 5: SAVE RESULT FILE (.jsonl)
    # ---------------------------------------------------------
    prediction_entry = {
        "model_name_or_path": agent.model_name,
        "instance_id": instance_id,
        "model_patch": patch
    }
    
    with open(PREDICTIONS_FILE, "w") as f:
        f.write(json.dumps(prediction_entry) + "\n")
    
    print("4️⃣  Patch file saved. Preparing to run Docker...")

    # ---------------------------------------------------------
    # STEP 6: RUN EVALUATION (Docker)
    # ---------------------------------------------------------
    # Command to call eval.py

    # 1. Determine absolute paths (To avoid errors when changing directories)
    current_dir = os.path.dirname(os.path.abspath(__file__)) # Backend folder
    root_dir = os.path.abspath(os.path.join(current_dir, '..')) # Project root folder
    bench_core_path = os.path.join(root_dir, 'bench-core') # Bench-core folder
    
    abs_pred_file = os.path.abspath(PREDICTIONS_FILE)
    abs_log_dir = os.path.abspath(LOG_DIR)

    # 2. Setup PYTHONPATH environment variable
    # Helps eval.py see 'utils' folder in bench-core
    env = os.environ.copy()
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = bench_core_path + os.pathsep + env["PYTHONPATH"]
    else:
        env["PYTHONPATH"] = bench_core_path

    cmd = [
        "python", "evaluation/eval.py", # Run from inside bench-core
        "--predictions_path", abs_pred_file, # Use absolute path
        "--log_dir", abs_log_dir,
        "--bench_tasks", "NoCode-bench/NoCode-bench_Verified",
        "--image_level", "repo",
        "--max_workers", "1",
        "--timeout", "300"
    ]

    try:
        # 4. Run subprocess with new environment and cwd
        result = subprocess.run(
            cmd, 
            cwd=bench_core_path, # <--- IMPORTANT: Change working directory to bench-core
            env=env,             # <--- IMPORTANT: Load PYTHONPATH
            capture_output=True, 
            text=True
        )
        
        # Merge logs
        output_log = result.stdout + "\nErrors:\n" + result.stderr
        
        is_passed = "PASSED" in output_log
        status_msg = "PASSED" if is_passed else "FAILED"
        print(f"🏁 Evaluation finished: {status_msg}")

        return {
            "status": "completed",
            "patch": patch,
            "read_files": list(code_context.keys()),
            "eval_output": output_log,
            "success": is_passed
        }

    except Exception as e:
        print(f"❌ Error running eval: {e}")
        return {"status": "error", "step": "evaluation", "detail": str(e)}

if __name__ == "__main__":
    import uvicorn
    # Reload=True helps the server auto-restart when you modify code
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)