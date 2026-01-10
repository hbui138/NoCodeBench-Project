import requests
import json
import time
import sys

# Configuration
BASE_URL = "http://localhost:8000"

def print_separator(title):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)

def test_first_task():
    # 1. CHECK SERVER CONNECTION
    print("🔌 Connecting to Backend...")
    try:
        # Get list of tasks
        resp = requests.get(f"{BASE_URL}/tasks")
        tasks = resp.json()
        
        if not tasks:
            print("❌ Error: Task list is empty. Check if dataset is loaded.")
            return

        # 2. SELECT FIRST TASK
        target_task = tasks[0]
        instance_id = target_task['id']
        project_name = target_task['project']
        
        print(f"✅ Connection successful! Found {len(tasks)} tasks.")
        print(f"🎯 Selecting first Task: [ {instance_id} ]")
        print(f"📂 Project: {project_name}")

        # 3. SEND RUN COMMAND (POST /run)
        print_separator("STARTING PIPELINE (Please wait 2-5 minutes...)")
        print("   1. Setup Repo & Checkout Commit...")
        print("   2. Agent reads problem & Locates code file...")
        print("   3. Agent writes Patch...")
        print("   4. Docker runs Test...")
        
        start_time = time.time()
        
        # Call API with long timeout (10 minutes) because Docker runs for a long time
        run_resp = requests.post(
            f"{BASE_URL}/run", 
            json={"instance_id": instance_id},
            timeout=6000 
        )

        duration = time.time() - start_time

        # 4. PROCESS RESULTS
        if run_resp.status_code == 200:
            result = run_resp.json()
            
            # --- CHECK STEP 1 & 2: READ FILE ---
            print_separator(f"RESULTS (Completed in {duration:.1f}s)")
            
            read_files = result.get("read_files", [])
            if read_files:
                print(f"✅ Agent successfully read {len(read_files)} real code files:")
                for f in read_files:
                    print(f"   - {f}")
            else:
                print("⚠️  Agent did NOT read any files (Possibly wrong filename guess or Repo not downloaded).")

            # --- CHECK STEP 3: GENERATE PATCH ---
            patch = result.get("patch", "")
            if patch:
                print("\n✅ Agent generated Patch (Modified Code):")
                # Print only first 10 lines for brevity
                print("--- Start of Patch ---")
                print("\n".join(patch.split("\n")[:10]))
                print("... (continued) ...")
            else:
                print("\n❌ Agent did NOT generate a Patch!")

            # --- CHECK STEP 4: DOCKER EVAL ---
            eval_log = result.get("eval_output", "")
            is_success = result.get("success", False)
            
            print_separator("DOCKER EVALUATION LOG")
            
            # Filter to get the final part of the log for better visibility
            log_lines = eval_log.split("\n")
            last_lines = log_lines[-15:] if len(log_lines) > 15 else log_lines
            
            for line in last_lines:
                print(line)
            
            print("-" * 30)
            if is_success:
                print("🎉 FINAL RESULT: PASSED (Congratulations!)")
            else:
                print("💥 FINAL RESULT: FAILED (Don't worry, this is normal for a base model)")

        else:
            print(f"\n❌ Server Error ({run_resp.status_code}):")
            print(run_resp.text)

    except requests.exceptions.ConnectionError:
        print("\n❌ CANNOT CONNECT: Server is not running.")
        print("👉 Open another Terminal and run: python backend/main.py")
    except requests.exceptions.ReadTimeout:
        print("\n⚠️  TIMEOUT: Server is still running but taking too long (over 10 minutes).")
        print("👉 Check Backend Terminal to see progress.")
    except Exception as e:
        print(f"\n❌ Unknown Error: {e}")

if __name__ == "__main__":
    test_first_task()