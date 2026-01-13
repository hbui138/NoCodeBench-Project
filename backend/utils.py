# backend/utils.py
import os
import subprocess
import fnmatch

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPOS_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, "..", "bench-core", "repos"))

if not os.path.exists(REPOS_ROOT):
    os.makedirs(REPOS_ROOT, exist_ok=True)

print(f"📍 REPOS_ROOT points to: {REPOS_ROOT}")

def setup_repo(repo_identifier: str, base_commit: str):
    """
    Docstring for setup_repo
    
    :param repo_identifier: Description
    :type repo_identifier: str
    :param base_commit: Description
    :type base_commit: str

    Used for setting up the repository for a given task.
    This function assumes that the repository is already cloned and checked out.
    """
    # 1. Get repo name (matplotlib/matplotlib -> matplotlib)
    if "__" in repo_identifier:
        repo_name = repo_identifier.split('__')[-1]
    else:
        repo_name = repo_identifier.split('/')[-1]
        
    repo_path = os.path.join(REPOS_ROOT, repo_name)

    print(f"🔍 Looking for repo: {repo_path}")

    # 2. Check if repo folder exists
    if not os.path.exists(repo_path):
        print(f"❌ ERROR: Cannot find repo'{repo_name}' in REPOS_ROOT.")
        print(f"   (The incorrect path: {repo_path})")
        return False, f"Repo path not found: {repo_path}"

    # 3. TRUSTED MODE (Skip git operations)
    # Skip git operations to avoid permission/path issues 
    print(f"⚠️  SKIP GIT: Suppose that repo is already ready.")
    
    # 4. Check if repo is non-empty
    try:
        files = os.listdir(repo_path)
        if not files:
            return False, "Repo exists but is empty (0 files)!"
            
        print(f"✅ Valid repo found: {len(files)} items (VD: {files[:3]}...)")
        return True, repo_path
        
    except Exception as e:
        return False, f"Error reading directory: {e}"

def _read_file_safe(file_path):
    """
    """
    try:
        if not os.path.isfile(file_path): return None

        try:
            with open(file_path, "r", encoding="utf-8", newline=None) as f:
                return f.read().replace("\r\n", "\n")
        except UnicodeDecodeError:
            with open(file_path, "r", encoding="latin-1", newline=None) as f:
                return f.read().replace("\r\n", "\n")
    except Exception as e:
        print(f"⚠️ Error reading file {file_path}: {e}")
        return None

def read_local_file(repo_path, rel_path):
    """
    """
    rel_path = rel_path.strip()
    if not rel_path: return None, None
    
    clean_rel_path = rel_path.lstrip("/\\")
    
    # --- CHIẾN LƯỢC 1: Đường dẫn tuyệt đối hoặc chính xác ---
    direct_path = os.path.join(repo_path, clean_rel_path)
    if os.path.exists(direct_path):
        return _read_file_safe(direct_path), clean_rel_path

    # --- CHIẾN LƯỢC 2: Các tiền tố phổ biến (Heuristics) ---
    repo_name = os.path.basename(repo_path.rstrip("/\\"))
    common_prefixes = [
        "src/", "lib/", "core/", "python/", 
        f"{repo_name}/", f"src/{repo_name}/", f"lib/{repo_name}/"
    ]
    
    for prefix in common_prefixes:
        candidate = os.path.join(repo_path, f"{prefix}{clean_rel_path}")
        if os.path.exists(candidate):
            real_rel_path = f"{prefix}{clean_rel_path}"
            return _read_file_safe(candidate), real_rel_path # <--- Trả về đường dẫn tìm được

    # --- CHIẾN LƯỢC 3: Quét đệ quy toàn bộ (Deep Search) ---
    print(f"🕵️‍♀️ Deep searching for '{clean_rel_path}' in {repo_name}...")
    
    target_name = os.path.basename(clean_rel_path) # VD: models.py
    
    # Chuẩn hóa đường dẫn mục tiêu để so sánh (đổi \ thành /)
    norm_target = clean_rel_path.replace("\\", "/") 

    for root, dirs, files in os.walk(repo_path):
        # Bỏ qua folder rác nhưng KHÔNG bỏ qua folder code
        dirs[:] = [d for d in dirs if d not in {'.git', '__pycache__', 'venv', 'build', 'dist', '.idea', '.vscode'}]
        
        if target_name in files:
            found_path = os.path.join(root, target_name)
            
            # Kiểm tra xem đường dẫn tìm thấy có "kết thúc bằng" đường dẫn mục tiêu không
            # VD: Tìm "utils/log.py", thấy "src/utils/log.py" -> KHỚP
            norm_found = found_path.replace("\\", "/")
            
            if norm_found.endswith(norm_target):
                print(f"✅ Found via deep search: {found_path}")
                real_rel_path = os.path.relpath(found_path, repo_path).replace("\\", "/")
                return _read_file_safe(found_path), real_rel_path # <--- Trả về đường dẫn thật

    print(f"❌ Could not find file: {rel_path}")
    return None, None

def get_repo_structure(repo_path):
    """
    """
    structure_lines = []
    
    # Blacklist folders to ignore
    ignore_dirs = {
        '.git', '__pycache__', 'venv', 'env', 'build', 'dist', 
        '.github', '.circleci', '.idea', '.vscode', 
        'site-packages', 'node_modules', 'doc', 'docs'
    }
    
    # Whitelist the file extensions to include
    include_extensions = {
        '.py', '.pyi', '.pyx', '.pxd', '.c', '.cpp', '.h', 
        '.js', '.ts', '.rst', '.md', '.sh', '.toml', '.ini',
        '.json', '.yaml', '.yml'
    }

    for root, dirs, files in os.walk(repo_path):
        # Filter out ignored directories
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        # Determine the current level
        rel_root = os.path.relpath(root, repo_path)
        if rel_root == ".":
            level = 0
        else:
            level = rel_root.count(os.sep) + 1
        
        # Limit depth to avoid huge output
        if level > 10:
            continue

        indent = ' ' * 2 * level
        folder_name = os.path.basename(root)
        
        if level == 0:
            structure_lines.append(f"{folder_name}/")
        else:
            structure_lines.append(f"{indent}{folder_name}/")
        
        subindent = ' ' * 2 * (level + 1)
        for f in files:
            _, ext = os.path.splitext(f)
            if ext in include_extensions:
                structure_lines.append(f"{subindent}{f}")
                
    return "\n".join(structure_lines)