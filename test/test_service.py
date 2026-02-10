import pytest
import os
import json
import shutil
import subprocess
from unittest.mock import MagicMock, patch, mock_open
import sys

# ==========================================
# IMPORT PATH
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from backend import service
from backend import state

class TestService:
    @pytest.fixture(scope="session", autouse=True)
    def cleanup_artifacts(self):
        """
        Run once per test session to clean up any artifacts from previous runs before starting new tests.
        """
        service.CURRENT_RUN_DIR = None
        yield 
        
        print("\n🧹 [TEARDOWN] Cleaning up artifacts...")
        current_dir = os.path.dirname(os.path.abspath(__file__))
        project_root = os.path.abspath(os.path.join(current_dir, ".."))

        workspace_path = os.path.join(project_root, "workspace_temp")
        if os.path.exists(workspace_path):
            try:
                shutil.rmtree(workspace_path)
                print(f"✅ Đã xóa workspace: {workspace_path}")
            except: pass

        # Delete the latest results_ folder if it exists (to ensure clean state for next run)
        results_base_dir = os.path.join(project_root, "results")
        
        if os.path.exists(results_base_dir):
            all_runs = [
                d for d in os.listdir(results_base_dir) 
                if d.startswith("results_") and os.path.isdir(os.path.join(results_base_dir, d))
            ]
            
            all_runs.sort()
            
            if all_runs:
                latest_run = all_runs[-1]
                latest_run_path = os.path.join(results_base_dir, latest_run)
                
                try:
                    shutil.rmtree(latest_run_path)
                except Exception as e:
                    print(f"⚠️ Cannot delete {latest_run}: {e}")
            else:
                print("ℹ️ Did not find any results_ folders to clean.")

    @pytest.fixture(autouse=True)
    def setup_state(self):
        """
        Reset global state before each test.
        """
        # 1. Reset data locally
        state.data_map = {
            "task_123": {
                "problem_statement": "Fix the bug in Django models",
                "repo": "django/django",
                "base_commit": "abc12345",
                "instance_id": "task_123",
                "mask_doc_diff": "diff",
                "augmentations": {}
            },
            "task_1": {"instance_id": "task_1"},
            "task_2": {"instance_id": "task_2"},
            "task_3": {"instance_id": "task_3"}
        }
        
        # 2. Reset batch state
        state.batch_state.is_running = True
        state.batch_state.processed_count = 0
        state.batch_state.logs = []

        # 3. Sync global variables in service module
        service.state = state

    # =========================================================================
    # 1. TEST PATH INITIALIZATION
    # =========================================================================
    @patch("os.makedirs")
    @patch("os.path.exists")
    def test_initialize_paths_creates_directories(self, mock_exists, mock_makedirs):
        mock_exists.return_value = False
        service.initialize_paths(force_new=True)
        assert service.CURRENT_RUN_DIR is not None
        assert "results_" in service.CURRENT_RUN_DIR
        assert mock_makedirs.call_count >= 2

    # =========================================================================
    # 2. TEST DIRECTORY CLEANUP
    # =========================================================================
    @patch("subprocess.run")
    @patch("shutil.rmtree")
    @patch("os.path.exists")
    def test_force_delete_directory_fallback(self, mock_exists, mock_rmtree, mock_subproc):
        """
        Test 'Nuclear Option': Fallback to Windows CMD if Python fails.
        """
        mock_exists.return_value = True 
        mock_rmtree.side_effect = OSError("Access Denied")
        
        service.force_delete_directory("C:/fake/path", retries=1)
        
        mock_subproc.assert_called_with(
            ["rmdir", "/S", "/Q", "C:/fake/path"], 
            shell=True, 
            check=False
        )

    # =========================================================================
    # 3. TEST RUN TASK LOGIC (Core Logic)
    # =========================================================================
    @patch("backend.service.get_repo_structure")
    @patch("backend.service.read_local_file")
    @patch("backend.service.setup_repo")
    @patch("backend.service.NoCodeAgent")
    @patch("subprocess.run")
    @patch("shutil.copytree")
    @patch("shutil.rmtree")
    def test_run_task_logic_success_flow(
        self, mock_rm, mock_cp, mock_subproc, mock_agent_cls, mock_setup_repo, mock_read_file, mock_structure
    ):
        # 1. Setup Mocks
        mock_setup_repo.return_value = (True, "/tmp/base_repo")
        mock_structure.return_value = "src/main.py"
        mock_read_file.return_value = ("print('hello')", "/tmp/base_repo/src/main.py")

        # Mock Agent
        mock_agent_instance = MagicMock()
        mock_agent_instance.locate_files.return_value = {"edit_files": ["src/main.py"], "context_files": []}
        mock_agent_instance.generate_patch.return_value = "patch_content"
        mock_agent_instance.model_name = "gemini-flash-fake"
        mock_agent_instance.current_task_tokens = {"prompt": 10, "completion": 20, "total": 30}
        
        mock_agent_cls.return_value = mock_agent_instance

        # Mock Eval
        mock_eval_res = MagicMock()
        mock_eval_res.stdout = "PASSED"
        mock_eval_res.stderr = ""
        mock_subproc.return_value = mock_eval_res

        # 2. Execute
        with patch("builtins.open", mock_open()):
            result = service.run_task_logic("task_123")

        # 3. Assert
        if result["status"] == "error":
            print(f"DEBUG FAIL REASON: {result.get('detail')}")

        assert result["status"] == "completed"
        assert result["success"] is True

    @patch("backend.service.NoCodeAgent")
    @patch("backend.service.setup_repo")
    @patch("shutil.copytree")
    @patch("shutil.rmtree")
    def test_run_task_logic_api_overload(self, mock_rm, mock_cp, mock_setup, mock_agent_cls):
        mock_setup.return_value = (True, "/tmp/repo")
        
        mock_agent = MagicMock()
        # Overload error simulation
        mock_agent.generate_patch.return_value = {"error_type": "overload"}
        mock_agent_cls.return_value = mock_agent

        result = service.run_task_logic("task_123")
        
        assert result["status"] == "error"
        assert result["detail"] == "api_overload_skip"

    # =========================================================================
    # 4. TEST BATCH PROCESS
    # =========================================================================
    @patch("backend.service.run_final_aggregation_and_cleanup")
    @patch("backend.service.run_task_logic")
    def test_run_batch_process_orchestration(self, mock_run_logic, mock_aggregation):
        mock_run_logic.return_value = {"status": "completed", "success": True}
        
        task_ids = ["task_1", "task_2", "task_3"]
        
        service.run_batch_process(task_ids)
        
        # Call count should match number of tasks
        assert mock_run_logic.call_count == 3
        
        # Check that batch state is updated correctly
        assert state.batch_state.processed_count == 3 
        
        mock_aggregation.assert_called_once()

    # =========================================================================
    # 5. TEST REPORT READING
    # =========================================================================
    @patch("os.path.exists")
    @patch("os.listdir")
    def test_get_summary_report_content(self, mock_ls, mock_exists):
        service.CURRENT_RUN_DIR = "/tmp/runs/run_1"
        mock_exists.return_value = True
        mock_ls.return_value = ["run_1_summary_report.txt"]
        
        with patch("builtins.open", mock_open(read_data="Report Content")):
            content = service.get_summary_report_content()
            
        assert content == "Report Content"