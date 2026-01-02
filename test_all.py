import requests
import time
import sys

# Cấu hình
BASE_URL = "http://localhost:8000"

def draw_progress_bar(current, total, bar_length=40):
    """Hàm vẽ thanh tiến trình trên terminal"""
    if total == 0:
        percent = 0
        arrow = '-' * bar_length
    else:
        percent = float(current) / total
        arrow = '-' * int(round(percent * bar_length) - 1) + '>'
        spaces = ' ' * (bar_length - len(arrow))
        arrow = arrow + spaces

    sys.stdout.write(f"\rProcess: [{arrow}] {int(percent * 100)}% ({current}/{total})")
    sys.stdout.flush()

def monitor_batch():
    print_separator("BATCH PROCESSING DASHBOARD")

    # 1. Gửi lệnh START
    print("🚀 Sending START command to Server...")
    try:
        resp = requests.post(f"{BASE_URL}/batch/start")
        
        if resp.status_code == 200:
            print(f"✅ Success: {resp.json()['message']}")
        elif resp.status_code == 400:
            print(f"⚠️  Info: {resp.json()['detail']} (Connecting to existing session...)")
        else:
            print(f"❌ Error: {resp.text}")
            return

    except requests.exceptions.ConnectionError:
        print("❌ Cannot connect to backend. Is 'python main.py' running?")
        return

    print("👀 Monitoring progress... (Press Ctrl+C to exit monitor, background task will continue)\n")

    # 2. Vòng lặp MONITORING
    try:
        while True:
            try:
                status_resp = requests.get(f"{BASE_URL}/batch/status")
                if status_resp.status_code != 200:
                    break
                
                data = status_resp.json()
                
                is_running = data['is_running']
                processed = data['processed']
                total = data['total']
                logs = data['logs']

                # Vẽ thanh tiến trình
                draw_progress_bar(processed, total)

                # In log mới nhất (nếu có thay đổi)
                if logs:
                    # Di chuyển con trỏ xuống dòng dưới để in log, rồi lại quay về vẽ bar
                    # (Để đơn giản, ta chỉ in log cuối cùng bên cạnh status)
                    sys.stdout.write(f" | Last: {logs[-1]}")

                # Kiểm tra điều kiện dừng
                if not is_running:
                    if processed >= total and total > 0:
                        print("\n\n🎉 BATCH COMPLETED! All tasks finished.")
                    else:
                        print("\n\n⏹️  Batch stopped by user or finished.")
                    break

                time.sleep(1) # Cập nhật mỗi 1 giây

            except Exception as e:
                print(f"\n❌ Monitoring Error: {e}")
                break

    except KeyboardInterrupt:
        print("\n\n👋 Stopped monitoring.")

def stop_batch():
    """Hàm phụ trợ để dừng khẩn cấp"""
    print("\n🛑 Sending STOP command...")
    requests.post(f"{BASE_URL}/batch/stop")
    print("✅ Stop signal sent.")

def print_separator(title):
    print("\n" + "=" * 60)
    print(f" {title}")
    print("=" * 60)

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "stop":
        stop_batch()
    else:
        monitor_batch()