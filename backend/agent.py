import os
import json
import random
import re
import difflib
import time
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

class NoCodeAgent:
    def reset_task_tokens(self):
        self.current_task_tokens = {"prompt": 0, "completion": 0, "total": 0}

    def _update_tokens(self, metadata):
        """Support function to update token counts from metadata."""
        self.current_task_tokens["prompt"] += getattr(metadata, 'prompt_token_count', 0) or 0
        self.current_task_tokens["completion"] += getattr(metadata, 'candidates_token_count', 0) or 0
        self.current_task_tokens["total"] += getattr(metadata, 'total_token_count', 0) or 0

    def __init__(self, model_name="gemini-3-flash-preview"):
        self.model_name = model_name
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("❌ ERROR: GOOGLE_API_KEY not found")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)

    def locate_files(self, doc_diff: str, repo_structure: str = "") -> list:
        if not self.client: return []

        if not hasattr(self, 'current_task_tokens'):
            self.reset_task_tokens()
        
        prompt = f"""
        ROLE: You are a senior software architect.
        TASK: Identify ALL file paths that need to be modified or created to fix the issue.
        
        INPUT ISSUE:
        {doc_diff[:10000]}
        
        REPO STRUCTURE:
        {repo_structure[:10000]}
        
        STRATEGY:
        1. 🕵️‍♂️ ROOT CAUSE ANALYSIS: Look for the root file causing the error. If the traceback says "cannot import X from Y", then Y MUST be in your list.
        2. ⛓️ FOLLOW THE CHAIN: Trace back the ImportError path. If 'models.py' fails to import 'JSONDecodeError' from '.compat', then 'compat.py' is a primary target.
        3. 🔄 COMPATIBILITY LAYER: For issues involving cross-version support (Python 2/3) or 3rd-party wrappers (json, urllib3), ALWAYS prioritize checking 'compat.py', 'utils/compatibility.py', or similar names.
        4. 🔗 THE "INIT" GATEWAY: Checking '__init__.py' is often necessary to see how names are exposed to the rest of the package.
        5. 🧠 DEFINITION VS USAGE: If a function has a bad signature, find where it is DEFINED (e.g., 'core.py'), not just where the crash occurred.
        6. 🛡️ PRIVATE & INTERNAL: Do NOT ignore files starting with '_' (e.g., '_internal_utils.py'). Core logic is often hidden there.

        CRITICAL RULES:
        - 🚫 IGNORE non-code files: Do not list .rst, .md, .txt, .html
        - ✅ PRIORITIZE IMPLEMENTATION: Prefer 'core.py', 'models.py', '_axes.py' over 'test_*.py' or 'conftest.py'. Only list tests if the task is explicitly to fix a test case.
        - ⚠️ PRIVATE MODULES: Do NOT ignore files starting with '_' (e.g., '_axes.py', '_base.py'). These often contain the core logic.
        - 🎯 EXACT MATCH: Return paths exactly as they appear in the REPO STRUCTURE. Do not invent paths.
        - 📦 DEPENDENCIES: If you modify a function signature in File A, check if you need to update its usage in File B? If yes, list both.
        
        OUTPUT FORMAT: 
        Return ONLY a JSON list of strings. Example: ["requests/models.py", "requests/api.py"]
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
            )

            self._update_tokens(response.usage_metadata)

            files = json.loads(response.text)
            print(f"🤖 [Gemini] Proposed files to fix: {files}")
            return files
        except Exception as e:
            print(f"⚠️ Locate Error: {e}")
            return []

    def generate_patch(self, doc_diff: str, code_context: dict, instance_id: str = None) -> str:
        if not self.client or not code_context: return ""

        if not hasattr(self, 'current_task_tokens'):
            self.reset_task_tokens()

        total_patch = ""
        
        # Context summary 
        all_files_context_str = ""
        for fname, content in code_context.items():
            limit = 60000 
            truncated_content = content[:limit] + "...(truncated)" if len(content) > limit else content
            all_files_context_str += f"\n--- FILE: {fname} ---\n{truncated_content}\n"

        # Loop files
        for target_file, original_code in code_context.items():
            print(f"🔧 Processing file: {target_file}...")

            prompt = f"""
            ROLE: You are an expert Python developer.
            TASK: You are currently editing the file: '{target_file}'.
            Fix the issue described below. If this file needs no changes, output NOTHING.

            CONTEXT:
            Task ID: {instance_id}
            
            ISSUE DESCRIPTION:
            {doc_diff}

            REFERENCE (Other files involved in this fix):
            {all_files_context_str}

            FULL CONTENT OF '{target_file}' (Editable):
            {original_code}

            INSTRUCTION:
            1. Does '{target_file}' need changes to fix the issue?
            2. If YES, output a SEARCH block (exact copy of old code) and REPLACE block (new code).
            3. 🛡️ DEPENDENCY INTEGRITY: If your fix introduces a new name (class, function, or constant) 
            in File A and imports it in File B, you MUST ensure that File A is actually modified to include 
            that definition. Never assume a name exists if it is not in the original code or added 
            by your own SEARCH/REPLACE blocks.
            4. 🧱 ATOMIC CHANGES: Keep SEARCH/REPLACE blocks small and focused.
            5. 🧩 ARCHITECTURAL CONSISTENCY: 
                - If the project uses a compatibility layer (like 'compat.py' or 'utils/six.py'), 
                use it to handle cross-version or cross-library differences.
                - If you define a new Exception, ensure it inherits from an appropriate base 
                class already used in the project to maintain backwards compatibility.

            RULES:
            1. 🔍 EXACT MATCH REQUIRED: The content of the <<<< SEARCH block must be a byte-for-byte copy of the original file.
               - ⛔️ NO REFORMATTING: Do not fix indentation, remove spaces, or change quotes (' vs ").
               - ⛔️ NO LINTING: Even if the original code has syntax errors or bad style, copy it EXACTLY.
            
            2. 🛡 CONTEXT IS KEY:
               - Include at least 3-5 lines of UNCHANGED code before AND after the lines you want to modify.
               - ⚠️ UNIQUENESS: The SEARCH block must match ONLY ONE location in the file. If the code is generic (e.g. "return x"), add more context until it is unique.
            
            3. 🚫 NO LAZINESS:
               - Do not use "..." or comments like "# ... code ..." to skip lines in the SEARCH block. Write out every single line.
            
            4. 🧱 ATOMICITY:
               - If you need to change multiple disjoint parts of the file, use multiple SEARCH/REPLACE blocks.
               - If no changes are needed, return an empty string.
            
            5. ⚠️ INDENTATION: Maintain the exact same indentation level as the original code. 
               - If you are inside a class or function, your REPLACE block must be indented correctly.

            6. ⚠️ CRITICAL PYTHON INTEGRITY:
               - SYNCHRONIZATION: If you add a new key to a mapping decorator (e.g., `replace_names`, `kwargs_mapping`), you MUST verify that the corresponding argument exists in the function definition `def func(...)`.
               - AVOID CRASHES: Adding a key to the decorator without adding the argument to the function signature will cause an `AssertionError` or `TypeError` at runtime.
               - EXAMPLE: 
                 (Bad):  @decorator(names=["new_arg"]) -> def func(old_arg):
                 (Good): @decorator(names=["new_arg"]) -> def func(old_arg, new_arg=None):
            
            🚨 STRICT FORMATTING RULES (CRITICAL):
            - DO NOT include `python` or markdown fences (```) inside the blocks.
            - DO NOT abbreviate logic with comments like `# ... existing code ...`. WRITE IT OUT.
            - DO NOT ADD LABELS like 'REPLACE', 'UPDATE', 'CODE', or 'INSERT' inside the blocks. JUST WRITE THE CODE.
            - INDENTATION MATTERS: Ensure your `<<<< SEARCH` block has the EXACT indentation as the original file.
            - If matching fails, I will reject your answer. Use enough context (3-4 lines) to make the match unique.
            
            FORMAT EXAMPLE:
            <<<< SEARCH
                def calculate_sum(a, b):
                    # old comment
                    return a + b
            ====
                def calculate_sum(a, b):
                    # fixed comment
                    return a + b + c
            >>>>
            """

            # --- RETRY LOOP ---
            max_retries = 3
            current_prompt = prompt
            
            for attempt in range(max_retries):
                # Try to get valid diff
                try:
                    ai_output = ""
                    # Try generating content
                    try:
                        response = self.client.models.generate_content(
                            model=self.model_name,
                            contents=current_prompt,
                            config=types.GenerateContentConfig(temperature=0.1) # Tăng nhẹ temp nếu retry
                        )
                        
                        self._update_tokens(response.usage_metadata)
                        
                        ai_output = response.text
                    except Exception as e:
                        error_str = str(e)
                        # Model overload handling
                        if "503" in error_str or "429" in error_str or "overloaded" in error_str.lower():
                            print(f"⚠️ Server Overloaded. Signaling to Re-queue...")
                            return {"error_type": "overload", "detail": str(e)}

                        # Other errors
                        print(f"⚠️ Gemini Error (Attempt {attempt+1}): {e}")
                        continue

                    file_diff = self._construct_valid_diff(original_code, target_file, ai_output)
                    
                    if file_diff:
                        total_patch += file_diff + "\n"
                        print(f"  ✅ Patch generated & verified for {target_file} (Attempt {attempt+1})")
                        break
                    else:
                        print(f"  ❌ Generation failed (Attempt {attempt+1}/{max_retries}). Retrying...")
                        
                        current_prompt += f"""
                        \n\nSYSTEM FEEDBACK (Attempt {attempt+1}):
                        Your previous patch FAILED to apply.
                        The content in your '<<<< SEARCH' block could not be found in the original file.
                        
                        POSSIBLE CAUSES:
                        1. You modified the indentation or spaces in the SEARCH block.
                        2. You truncated the lines or omitted code.
                        3. You used the wrong quotes (' vs ").
                        
                        TRY AGAIN. COPY THE CODE EXACTLY CHARACTER-BY-CHARACTER.
                        """
                        
                except Exception as e:
                    print(f"❌ Critical Error in loop: {e}")

        return total_patch

    def _construct_valid_diff(self, original_code, filename, ai_output):
        try:
            if not ai_output or not isinstance(ai_output, str): return ""

            # --- FIX 1: Dọn dẹp Markdown Artifacts ---
            # Gemini hay trả về ```python ở đầu và ``` ở cuối, làm hỏng regex
            clean_output = re.sub(r"^```[a-zA-Z]*\n", "", ai_output.strip())
            clean_output = re.sub(r"\n```$", "", clean_output)
            
            # --- FIX 2: Regex linh hoạt hơn ---
            # Cho phép có hoặc không có newline trước/sau các thẻ
            pattern = r"<{4}\s*SEARCH\s*\n(.*?)\n={4}\s*\n(.*?)\n>{4}"
            matches = re.findall(pattern, clean_output, re.DOTALL)
            
            if not matches: 
                # Fallback: Thử tìm pattern không có newline (trường hợp LLM viết liền)
                pattern_lazy = r"<{4}\s*SEARCH\n(.*?)\n={4}\n(.*?)\n>{4}"
                matches = re.findall(pattern_lazy, clean_output, re.DOTALL)
                if not matches: return ""

            original_lines = original_code.splitlines(keepends=True)
            modified_lines = original_lines[:] 
            
            # --- FIX 3: Super Normalize thông minh hơn ---
            def super_normalize(s):
                # 1. Xóa hết whitespace
                s = re.sub(r'\s+', '', s).lower()
                # 2. Chuẩn hóa dấu nháy: Biến tất cả ' thành " để so sánh
                s = s.replace("'", '"')
                # 3. Bỏ qua trailing commas (dấu phẩy cuối) hay gây lỗi
                s = s.replace(",)", ")").replace(",]", "]").replace(",}", "}")
                return s

            changes_to_apply = []

            for i, (search_block, replace_block) in enumerate(matches):
                search_lines = search_block.strip().splitlines()
                if not search_lines: continue

                # Normalized search block
                search_chunk_str = "\n".join(search_lines)
                search_norm = super_normalize(search_chunk_str)
                n_search = len(search_lines)
                
                best_ratio = 0.0
                best_idx = -1
                
                # --- Sliding Window ---
                # Mẹo: Giảm phạm vi search nếu file quá lớn để tiết kiệm CPU
                search_limit = len(original_lines)
                
                for idx in range(len(original_lines) - n_search + 1):
                    # Lấy chunk từ file gốc
                    chunk_lines = original_lines[idx : idx + n_search]
                    chunk_str = "".join([l.strip() for l in chunk_lines]) # Strip basic
                    
                    # 1. Check Exact Match (nhanh)
                    search_basic = "".join([l.strip() for l in search_lines])
                    if chunk_str == search_basic:
                        best_idx = idx
                        best_ratio = 1.0
                        break # Tìm thấy tuyệt đối thì dừng luôn

                    # 2. Check Fuzzy Match (chậm hơn nhưng cứu cánh)
                    # Chỉ check fuzzy nếu độ dài chunk tương đương
                    chunk_norm = super_normalize("\n".join(chunk_lines))
                    
                    # Dùng ratio của difflib
                    ratio = difflib.SequenceMatcher(None, chunk_norm, search_norm).ratio()
                    
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_idx = idx
                        if ratio > 0.98: break # Đủ tốt thì dừng

                # --- FIX 4: Giảm Threshold xuống mức chấp nhận được ---
                # 0.8 là hơi cao với NoCode-bench, 0.75 là mức an toàn cho các lỗi thụt dòng
                THRESHOLD = 0.75 
                
                if best_ratio >= THRESHOLD:
                    print(f"  ✅ Apply Block #{i+1} at line {best_idx+1} (Conf: {best_ratio:.2f})")
                    changes_to_apply.append({
                        "start": best_idx,
                        "end": best_idx + n_search,
                        "replace": replace_block
                    })
                else:
                    print(f"  ❌ Failed Block #{i+1} (Best conf: {best_ratio:.2f})")
                    # Log ra để debug xem nó lệch ở đâu
                    return ""

            # Apply changes (từ dưới lên trên để không lệch index)
            changes_to_apply.sort(key=lambda x: x["start"], reverse=True)

            for change in changes_to_apply:
                start = change["start"]
                end = change["end"]
                r_block = change["replace"]
                
                # Xử lý indentation cho block thay thế
                # (Tự động thêm \n nếu thiếu)
                r_lines = [line + '\n' if not line.endswith('\n') else line for line in r_block.splitlines()]
                
                # Xóa code cũ và chèn code mới
                del modified_lines[start:end]
                for l in reversed(r_lines):
                    modified_lines.insert(start, l)

            # Tạo diff
            final_code_str = "".join(modified_lines)
            diff = difflib.unified_diff(
                original_code.splitlines(keepends=True),
                final_code_str.splitlines(keepends=True),
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}"
            )
            return "".join(diff)

        except Exception as e:
            print(f"❌ Critical Diff Error: {e}")
            return ""