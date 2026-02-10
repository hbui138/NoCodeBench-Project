import pytest
from unittest.mock import MagicMock, patch
import sys
import os

current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(current_dir, "..", "backend")
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))
from backend.agent import NoCodeAgent

class TestNoCodeAgent:

    @pytest.fixture
    def agent(self):
        """Initialize agent with a dummy API key for testing."""
        with patch.dict("os.environ", {"GOOGLE_API_KEY": "fake-key"}):
            return NoCodeAgent()

    # --- Token Management Tests ---
    def test_reset_task_tokens(self, agent):
        agent.current_task_tokens = {"prompt": 10, "completion": 20, "total": 30}
        agent.reset_task_tokens()
        assert agent.current_task_tokens["total"] == 0
        assert agent.current_task_tokens["prompt"] == 0

    def test_update_tokens(self, agent):
        agent.reset_task_tokens()
        mock_metadata = MagicMock()
        mock_metadata.prompt_token_count = 100
        mock_metadata.candidates_token_count = 50
        mock_metadata.total_token_count = 150
        
        agent._update_tokens(mock_metadata)
        assert agent.current_task_tokens["prompt"] == 100
        assert agent.current_task_tokens["total"] == 150

    # --- Response Cleaning Tests ---
    def test_clean_response_markdown(self, agent):
        text = "Here is the patch:\n```diff\n--- a/file.py\n+++ b/file.py\n```"
        cleaned = agent._clean_response(text)
        assert "--- a/file.py" in cleaned
        assert "```" not in cleaned

    def test_clean_response_raw(self, agent):
        text = "diff --git a/test.py b/test.py"
        assert agent._clean_response(text) == text

    # --- Diff Construction Logic (Sliding Window & Fuzzy Match) ---
    def test_construct_valid_diff_exact_match(self, agent):
        original_code = "line1\nline2\nline3\n"
        filename = "test.py"
        ai_output = "<<<< SEARCH\nline2\n====\nline_fixed\n>>>>"
        
        diff = agent._construct_valid_diff(original_code, filename, ai_output)
        assert "-line2" in diff
        assert "+line_fixed" in diff
        assert "@@ -1,3 +1,3 @@" in diff

    def test_construct_valid_diff_fuzzy_match(self, agent):
        # AI uses single quotes, original uses double quotes
        original_code = 'print("hello world")\n'
        filename = "test.py"
        # Search block has slight variation (single quotes and extra space)
        ai_output = "<<<< SEARCH\nprint ( 'hello world' )\n====\nprint('fixed')\n>>>>"
        
        diff = agent._construct_valid_diff(original_code, filename, ai_output)
        assert "print('fixed')" in diff
        assert "print(\"hello world\")" in diff # Original line should be marked as removed

    def test_construct_valid_diff_fail_below_threshold(self, agent):
        original_code = "important_logic_a()\n"
        filename = "test.py"
        # Search block is completely unrelated
        ai_output = "<<<< SEARCH\ncompletely_different_code()\n====\nfix()\n>>>>"
        
        diff = agent._construct_valid_diff(original_code, filename, ai_output)
        assert diff == "" # Should return empty string if threshold not met

    # --- AI Logic Mocking ---
    @patch("google.genai.Client")
    def test_locate_files_mock(self, mock_client_class, agent):
        # Setup mock response
        mock_response = MagicMock()
        mock_response.text = '{"edit_files": ["app.py"], "context_files": ["utils.py"]}'
        mock_response.usage_metadata.prompt_token_count = 10
        
        agent.client.models.generate_content = MagicMock(return_value=mock_response)
        
        result = agent.locate_files("fix the bug", "app.py\nutils.py")
        
        assert result["edit_files"] == ["app.py"]
        assert agent.current_task_tokens["prompt"] == 10

    def test_construct_valid_diff_multiple_blocks(self, agent):
        original_code = "start\nmiddle\nend\n"
        ai_output = """
<<<< SEARCH
start
====
START_NEW
>>>>
<<<< SEARCH
end
====
END_NEW
>>>>
"""
        diff = agent._construct_valid_diff(original_code, "test.py", ai_output)
        assert "+START_NEW" in diff
        assert "+END_NEW" in diff
        assert "middle" in diff # Context line