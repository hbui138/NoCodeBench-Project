# backend/utils.py
import os
import subprocess

# Path to the directory containing 10 downloaded repos (Step 1)
# Note: Adjust "../bench-core/repos" if your directory structure is different
REPOS_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '../bench-core/repos'))

def setup_repo(repo_identifier: str, base_commit: str):
    """
    Prepare repo: Find the correct directory and checkout to the past.
    repo_identifier: example "psf/requests"
    base_commit: commit hash (example "a1b2c3d")
    """
    # 1. Process name: "psf/requests" -> "requests"
    repo_name = repo_identifier.split('/')[-1]
    repo_path = os.path.join(REPOS_ROOT, repo_name)

    if not os.path.exists(repo_path):
        raise FileNotFoundError(f"❌ Repo not found at: {repo_path}. Have you run collect.sh?")

    print(f"🔄 Checking out '{repo_name}' to commit {base_commit}...")
    
    try:
        # Git command: Checkout to old version, force to ignore trash changes
        subprocess.run(
            ["git", "checkout", "-f", base_commit],
            cwd=repo_path,      # Run command IN the repo directory
            check=True,         # Raise error if git fails
            capture_output=True # Hide git logs to reduce clutter
        )
        return True, repo_path
    except subprocess.CalledProcessError as e:
        return False, f"Git Error: {e}"

def read_local_file(repo_path: str, file_rel_path: str):
    """
    Read file content.
    repo_path: absolute path to the repo directory
    file_rel_path: relative path (e.g., "requests/models.py")
    """
    full_path = os.path.join(repo_path, file_rel_path)
    
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None # File does not exist (agent guessed wrong name)
    except Exception as e:
        return f"Error reading file: {str(e)}"