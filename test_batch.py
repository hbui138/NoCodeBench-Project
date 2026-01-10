# test_batch.py
import requests
import time
import sys
import argparse

# Configuration
BASE_URL = "http://localhost:8000"

def draw_progress_bar(current, total, bar_length=40):
    if total == 0: total = 1 # Tránh chia cho 0
    percent = float(current) / total
    arrow = '-' * int(round(percent * bar_length) - 1) + '>'
    spaces = ' ' * (bar_length - len(arrow))
    
    sys.stdout.write(f"\r🚀 Progress: [{arrow+spaces}] {int(percent * 100)}% ({current}/{total})")
    sys.stdout.flush()

def monitor_batch():
    """Hàm này sẽ gọi liên tục lên server để xem tiến độ"""
    print("\n👀 Monitoring Batch Progress...")
    start_time = time.time()
    
    while True:
        try:
            resp = requests.get(f"{BASE_URL}/batch/status")
            data = resp.json()
            
            is_running = data.get("is_running", False)
            processed = data.get("processed", 0)
            total = data.get("total", 0)
            
            draw_progress_bar(processed, total)
            
            if not is_running and total > 0 and processed >= total:
                print("\n\n✅ Batch Completed Successfully!")
                break
            
            if not is_running and total == 0:
                # Trường hợp vừa start xong server chưa kịp cập nhật state
                time.sleep(1)
                continue

            # Nếu server đã dừng nhưng chưa xong hết
            if not is_running and processed < total and (time.time() - start_time > 5):
                print("\n\n⚠️ Batch stopped unexpectedly.")
                break

            time.sleep(2) # Cập nhật mỗi 2 giây

        except Exception as e:
            print(f"\n❌ Monitoring Error: {e}")
            break
            
    print(f"⏱️ Total Execution Time: {time.time() - start_time:.1f}s")

def start_batch_test(limit_arg):
    print(f"🔌 Connecting to Backend at {BASE_URL}...")
    
    # 1. LẤY DANH SÁCH TASK TỪ SERVER
    try:
        resp = requests.get(f"{BASE_URL}/tasks")
        all_tasks = resp.json()
    except Exception:
        print("❌ CANNOT CONNECT: Server is not running. Did you run 'python backend/main.py'?")
        return

    if not all_tasks:
        print("❌ Server returned empty task list.")
        return

    # 2. XÁC ĐỊNH SỐ LƯỢNG VÀ CẮT LIST (CLIENT-SIDE SLICING)
    limit = 0 
    if limit_arg.lower() != "all":
        try:
            limit = int(limit_arg)
        except ValueError:
            print("❌ Error: Argument must be a number or 'all'")
            return

    selected_tasks = []
    if limit > 0:
        selected_tasks = all_tasks[:limit]
        print(f"✂️  Slicing: Taking first {limit} tasks.")
    else:
        selected_tasks = all_tasks
        print(f"🚀 Full Run: Taking ALL {len(all_tasks)} tasks.")

    # Lấy ra danh sách ID
    selected_ids = [t['id'] for t in selected_tasks]
    print(f"📋 Running IDs: {selected_ids}")

    # 3. GỬI LỆNH START BATCH VỚI LIST ID
    print("\n🔥 Sending START command...")
    try:
        # Quan trọng: Gửi trường 'ids' thay vì 'limit'
        payload = {"ids": selected_ids} 
        resp = requests.post(f"{BASE_URL}/batch/start", json=payload)
        
        if resp.status_code == 200:
            data = resp.json()
            if data.get("status") == "error":
                print(f"❌ Server Error: {data.get('message')}")
            else:
                print(f"✅ Batch Started! Server scheduled {data.get('count')} tasks.")
                # 4. Chuyển sang chế độ theo dõi
                monitor_batch()
        else:
            print(f"❌ Failed to start batch: {resp.text}")

    except Exception as e:
        print(f"❌ Error sending trigger: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Control the Batch Test Runner")
    parser.add_argument("count", nargs="?", default="10", help="Number of tasks to run (e.g., 5, 10, or 'all')")
    
    args = parser.parse_args()
    
    start_batch_test(args.count)