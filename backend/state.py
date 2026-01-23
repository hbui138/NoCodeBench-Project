# state.py
from typing import Dict, List

# --- GLOBAL DATASET ---
# Insead of using a database, we use an in-memory dictionary to store dataset information.
data_map: Dict = {}

# --- BATCH MANAGER STATE ---
class BatchManager:
    def __init__(self):
        self.is_running = False
        self.stop_signal = False
        self.total_tasks = 0
        self.processed_count = 0
        self.current_task_id = None
        self.results = []
        self.logs = []

    def start(self, total):
        self.is_running = True
        self.stop_signal = False
        self.total_tasks = total
        self.processed_count = 0
        self.results = []
        self.logs = []

    def stop(self):
        self.stop_signal = True
        self.is_running = False

    def finish(self):
        self.is_running = False
        self.current_task_id = None

    def log(self, message: str):
        self.logs.append(message)
        if len(self.logs) > 100: self.logs.pop(0)

# Initialize a global instance of BatchManager
batch_state = BatchManager()