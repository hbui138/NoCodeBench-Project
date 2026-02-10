import pytest
import os
from unittest.mock import MagicMock, patch, mock_open
import sys

# ==========================================
# IMPORT PATH
# ==========================================
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_dir = os.path.join(current_dir, "..", "backend")
sys.path.append(os.path.abspath(os.path.join(current_dir, "..")))

from backend import utils

class TestUtils:

    # =========================================================================
    # 1. TEST SETUP REPO
    # =========================================================================
    @patch("backend.utils.os.path.exists")
    @patch("backend.utils.os.listdir")
    def test_setup_repo_success(self, mock_listdir, mock_exists):
        """
        Test that setup_repo returns True and the path when the repo exists and is not empty.
        """
        mock_exists.return_value = True
        mock_listdir.return_value = ["README.md", "src"]

        success, path = utils.setup_repo("owner/myrepo", "commit_hash")
        assert success is True
        assert "myrepo" in path

        success, path = utils.setup_repo("owner__myrepo", "commit_hash")
        assert success is True
        assert "myrepo" in path

    @patch("backend.utils.os.path.exists")
    def test_setup_repo_not_found(self, mock_exists):
        """
        Test that setup_repo fails if the directory does not exist.
        """
        mock_exists.return_value = False
        
        success, msg = utils.setup_repo("owner/missing_repo", "commit_hash")
        assert success is False
        assert "Repo path not found" in msg

    @patch("backend.utils.os.path.exists")
    @patch("backend.utils.os.listdir")
    def test_setup_repo_empty(self, mock_listdir, mock_exists):
        """
        Test that setup_repo fails if the directory exists but is empty.
        """
        mock_exists.return_value = True
        mock_listdir.return_value = [] 
        
        success, msg = utils.setup_repo("owner/empty_repo", "commit_hash")
        assert success is False
        assert "empty" in msg

    # =========================================================================
    # 2. TEST _read_file_safe
    # =========================================================================
    @patch("backend.utils.os.path.isfile")
    def test_read_file_safe_not_exist(self, mock_isfile):
        """Test returns None if file does not exist."""
        mock_isfile.return_value = False
        content = utils._read_file_safe("fake_path.py")
        assert content is None

    @patch("backend.utils.os.path.isfile")
    def test_read_file_safe_utf8(self, mock_isfile):
        """Test reading a standard UTF-8 file."""
        mock_isfile.return_value = True
        fake_content = "print('hello')"
        
        with patch("builtins.open", mock_open(read_data=fake_content)):
            content = utils._read_file_safe("file.py")
            assert content == fake_content

    @patch("backend.utils.os.path.isfile")
    def test_read_file_safe_fallback_latin1(self, mock_isfile):
        """
        Test fallback to latin-1 when UTF-8 decoding fails.
        """
        mock_isfile.return_value = True
        
        m = mock_open()
        with patch("builtins.open", m):
            # First call raises UnicodeDecodeError, second call succeeds
            m.return_value.read.side_effect = [UnicodeDecodeError('utf-8', b'', 0, 1, 'bad'), "latin1_content"]
            
            content = utils._read_file_safe("file.bin")
            
            assert content == "latin1_content"
            assert m.call_count == 2

    # =========================================================================
    # 3. TEST read_local_file
    # =========================================================================
    
    # We must patch 'backend.utils.os.path.exists' because utils.py imports os
    # and calls os.path.exists.
    @patch("backend.utils._read_file_safe")
    @patch("backend.utils.os.path.exists")
    def test_read_local_file_direct(self, mock_exists, mock_read):
        """Test finding file via direct path."""
        mock_exists.return_value = True
        mock_read.return_value = "content"
        
        content, path = utils.read_local_file("/repo", "utils.py")
        
        # Debugging info if assertion fails
        if content is None:
            print("DEBUG: Content is None. Mock setup failed.")
            
        assert path == "utils.py"
        assert content == "content"

    @patch("backend.utils._read_file_safe")
    @patch("backend.utils.os.path.exists")
    def test_read_local_file_prefix_search(self, mock_exists, mock_read):
        """Test finding file in common prefixes (e.g., src/)."""
        # side_effect=[False, True] means:
        # 1st call (direct path check) -> returns False
        # 2nd call (src/utils.py check) -> returns True
        mock_exists.side_effect = [False, True] 
        mock_read.return_value = "content"
        
        content, path = utils.read_local_file("/repo", "utils.py")
        
        assert path == "src/utils.py"
        assert content == "content"

    @patch("backend.utils.os.walk")
    @patch("backend.utils._read_file_safe")
    @patch("backend.utils.os.path.exists")
    def test_read_local_file_deep_search(self, mock_exists, mock_read, mock_walk):
        """Test finding file via os.walk when direct/prefixes fail."""
        # Always return False for direct checks (force it to go to deep search)
        mock_exists.return_value = False 
        
        # Mock os.walk structure
        mock_walk.return_value = [
            ("/repo", ["nested"], []),
            ("/repo/nested", ["deep"], []),
            ("/repo/nested/deep", [], ["utils.py"])
        ]
        
        mock_read.return_value = "deep_content"
        
        content, path = utils.read_local_file("/repo", "utils.py")
        
        assert content == "deep_content"
        # Since path logic might rely on OS separators, check simple inclusion
        assert "utils.py" in path

    @patch("backend.utils.os.walk")
    @patch("backend.utils.os.path.exists")
    def test_read_local_file_not_found(self, mock_exists, mock_walk):
        """Test that it returns None if file is nowhere to be found."""
        mock_exists.return_value = False
        mock_walk.return_value = [] 
        
        content, path = utils.read_local_file("/repo", "missing.py")
        assert content is None
        assert path is None

    # =========================================================================
    # 4. TEST get_repo_structure
    # =========================================================================
    @patch("backend.utils.os.walk")
    def test_get_repo_structure(self, mock_walk):
        """
        Test generating the tree structure.
        """
        mock_walk.return_value = [
            ("/repo", [".git", "src", "build"], ["README.md"]), 
            ("/repo/src", [], ["main.py"]),                     
        ]
        
        structure = utils.get_repo_structure("/repo")
        
        assert "src/" in structure
        assert "main.py" in structure
        assert "README.md" in structure
        assert ".git" not in structure 
        assert "  main.py" in structure 

    @patch("backend.utils.os.walk")
    def test_get_repo_structure_max_depth(self, mock_walk):
        """Test that the structure stops printing after a certain depth."""
        deep_path = "/repo/1/2/3/4/5/6/7/8/9/10/11"
        mock_walk.return_value = [
            (deep_path, [], ["file.py"])
        ]
        
        structure = utils.get_repo_structure("/repo")
        assert "file.py" not in structure