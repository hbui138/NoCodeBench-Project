import pytest
from fastapi.testclient import TestClient
from unittest.mock import MagicMock, patch
import sys
import os

# ==========================================
# IMPORT PATH
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(current_dir, "..", "backend")
sys.path.append(os.path.abspath(backend_dir))

# ==========================================
# 👇 IMPORT MODULES
# ==========================================
from main import app
import state
import service

client = TestClient(app)

class TestMainAPI:

    @pytest.fixture(autouse=True)
    def setup_state(self):
        """
        Fixture to reset the global state before every test function.
        """
        # 1. Mock Task Data
        state.data_map = {
            "task_1": {
                "instance_id": "task_1",
                "repo": "test/repo",
                "problem_statement": "Fix the bug",
                "base_commit": "abc12345",
                "mask_doc_diff": "diff",
                "feature_patch": ""
            }
        }
        
        # 2. Reset Batch State
        state.batch_state.is_running = False
        state.batch_state.processed_count = 0
        state.batch_state.total_tasks = 0
        state.batch_state.logs = []
        state.batch_state.results = []

        # 3. FIX: Mock Global Variables in Service
        # (Đây là đoạn sửa lỗi TypeError NoneType)
        service.LOG_DIR = "/tmp/dummy_logs"
        service.MAIN_PREDICTIONS_FILE = "/tmp/dummy_preds.jsonl"
        service.CURRENT_RUN_DIR = "/tmp/dummy_run"

    # ==========================================
    # 1. TEST READ (GET) ENDPOINTS
    # ==========================================

    def test_get_all_tasks(self):
        response = client.get("/tasks")
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "task_1"

    def test_get_task_detail_success(self):
        response = client.get("/tasks/task_1")
        assert response.status_code == 200
        data = response.json()
        assert data["instance_id"] == "task_1"

    def test_get_task_detail_not_found(self):
        response = client.get("/tasks/INVALID_ID")
        assert response.status_code == 404

    @patch("main.load_results_from_file")
    @patch("service.initialize_paths")
    def test_get_task_result(self, mock_init, mock_load_results):
        # Mock result reading
        mock_load_results.return_value = {
            "task_1": {
                "model_patch": "print('ok')",
                "success": True,
                "token_usage": {"total": 10},
                "p2p_stats": {"success": [], "fail": []}
            }
        }

        response = client.get("/results/task_1")
        assert response.status_code == 200
        data = response.json()
        assert data["result"]["patch"] == "print('ok')"

    def test_get_task_result_not_found_in_map(self):
        """Test asking for result of a task ID that doesn't exist in data_map."""
        response = client.get("/results/INVALID_ID")
        assert response.status_code == 404

    # ==========================================
    # 2. TEST EXECUTION (POST) ENDPOINTS
    # ==========================================

    @patch("service.run_final_aggregation_and_cleanup")
    @patch("service.run_task_logic")
    @patch("service.initialize_paths")
    def test_run_single_task_sync(self, mock_init, mock_run_logic, mock_agg):
        mock_run_logic.return_value = {"status": "completed", "success": True}

        payload = {"instance_id": "task_1"}
        response = client.post("/run", json=payload)

        assert response.status_code == 200
        mock_run_logic.assert_called_once_with("task_1", is_batch_mode=False)

    @patch("service.run_batch_process")
    @patch("service.initialize_paths")
    def test_start_batch_limit_mode(self, mock_init, mock_batch_process):
        payload = {"limit": 1}
        response = client.post("/batch/start", json=payload)
        
        assert response.status_code == 200
        assert response.json()["status"] == "success"

    def test_start_batch_already_running(self):
        state.batch_state.is_running = True
        payload = {"limit": 1}
        response = client.post("/batch/start", json=payload)
        assert response.status_code == 400

    # ==========================================
    # 3. TEST STATUS & REPORT
    # ==========================================

    def test_get_batch_status(self):
        state.batch_state.is_running = True
        state.batch_state.total_tasks = 10
        state.batch_state.processed_count = 5
        
        response = client.get("/batch/status")
        assert response.status_code == 200
        assert response.json()["progress_percent"] == 50.0

    @patch("service.get_summary_report_content")
    def test_get_batch_report(self, mock_get_report):
        mock_get_report.return_value = "Report..."
        response = client.get("/batch/report")
        assert response.status_code == 200
        assert response.json()["content"] == "Report..."