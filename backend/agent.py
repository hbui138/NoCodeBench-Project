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

    def locate_files(self, doc_diff: str, repo_structure: str = "") -> dict:
        if not self.client: return {"edit_files": [], "context_files": []}

        if not hasattr(self, 'current_task_tokens'):
            self.reset_task_tokens()
        
        prompt = f"""
        ROLE: Senior Software Architect.
        TASK: Analyze the issue and return a JSON object classifying relevant files.

        OBJECTIVE:
        Split the files into two categories:
        1. "edit_files": The source code files that actually contain the bug and need modification.
        2. "context_files": READ-ONLY files needed to understand the bug or prevent regressions (e.g., relevant tests, base classes, interfaces).

        INPUT ISSUE:
        {doc_diff[:30000]}

        REPO STRUCTURE:
        {repo_structure[:50000]}

        STRATEGY:
        1. ROOT CAUSE -> edit_files: Traceback errors, logic bugs, imports failures usually point here.
        2. REGRESSION PREVENTION -> context_files: For every file in 'edit_files', find its corresponding test file (e.g., 'core.py' -> 'tests/test_core.py').
        3. DEFINITIONS -> context_files: If 'edit_files' uses a class/function defined elsewhere, include that definition file here.

        CONSTRAINTS:
        - OUTPUT format: A single JSON object with exactly two keys: "edit_files" (list[str]) and "context_files" (list[str]).
        - Example:
          {{
            "edit_files": ["xarray/core/dataset.py"],
            "context_files": ["xarray/tests/test_dataset.py", "xarray/core/common.py"]
          }}
        - VALIDATION: Paths must exist in REPO STRUCTURE.
        - EXCLUDE: Documentation, images, configs.
        """

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.0)
            )

            self._update_tokens(response.usage_metadata)

            result = json.loads(response.text)
            
            # Fallback if AI returns weird keys
            if "edit_files" not in result: result["edit_files"] = []
            if "context_files" not in result: result["context_files"] = []
            
            print(f"🤖 [Gemini] Plan: Edit {result['edit_files']}, Read {result['context_files']}.")
            return result
        except Exception as e:
            print(f"⚠️ Locate Error: {e}")
            return {"edit_files": [], "context_files": []}

    def generate_patch(self, doc_diff: str, files_to_edit: dict, read_only_context: str = "", instance_id: str = None) -> str:
        """
        Docstring for generate_patch
        
        :param doc_diff: The problem description
        :type doc_diff: str
        :param files_to_edit: Files that need to be edited
        :type files_to_edit: dict
        :param read_only_context: Files provided as read-only context
        :type read_only_context: str
        :param instance_id: Optional task identifier
        :type instance_id: str
        :return: The generated patch as a unified diff string
        :rtype: str
        """
        if not self.client or not files_to_edit: return ""

        if not hasattr(self, 'current_task_tokens'):
            self.reset_task_tokens()

        total_patch = ""
        edit_files_context = ""
        # Context summary 

        for fname, content in files_to_edit.items():
            limit = 30000
            truncated_content = content[:limit] + "...(truncated)" if len(content) > limit else content
            edit_files_context += f"\n--- FILE: {fname} ---\n{truncated_content}\n"

        full_reference_str = edit_files_context + "\n" + read_only_context

        # Loop files
        for target_file, original_code in files_to_edit.items():
            print(f"🔧 Processing file: {target_file}...")

            prompt = f"""
            ROLE: You are an expert Python developer.
            TASK: You are currently editing the file: '{target_file}'.
            Fix the issue described below. If this file needs no changes, output NOTHING.
            
            ISSUE DESCRIPTION:
            {doc_diff}

            REFERENCE (Other files involved in this fix):
            {full_reference_str}

            FULL CONTENT OF '{target_file}' (Editable):
            {original_code}

            INSTRUCTION:
            1. Analyze the issue and determine if '{target_file}' needs modification.
            2. If YES, output a SEARCH block (exact copy of old code) and REPLACE block (new code).
            3. DEPENDENCY INTEGRITY: If you introduce a new name (class, function, var) in File A and import it in File B, you MUST verify that File A is actually modified to define it.
            4. ARCHITECTURAL CONSISTENCY: 
                - Use existing compatibility layers (e.g., 'compat.py') for cross-version support.
                - Ensure new Exceptions inherit from appropriate project-specific base classes.
            5. TEST FILE STRATEGY (CONTEXT vs. EDIT):
               - If '{target_file}' is a TEST file (e.g., name includes 'test', inside 'tests/'):
                 * PRIMARY GOAL: Use it as READ-ONLY CONTEXT to understand how the implementation code is called (arguments, expected returns).
                 * DO NOT MODIFY the test file just to suppress errors.
                 * ONLY MODIFY the test file if:
                   a) You intentionally changed a function signature (arguments/types) in the source code and the test needs an update to match.
                   b) The issue explicitly states that the test case itself is incorrect.
                 * If neither applies, output NOTHING for this file.

            STRICT FORMATTING RULES (CRITICAL):
            1. EXACT MATCH REQUIRED: 
               - The `<<<< SEARCH` block must be a byte-for-byte copy of the original file.
               - NO REFORMATTING: Do not change indentation, spaces, or quotes (' vs ").
               - NO LINTING: Copy errors/typos exactly if they exist in original code.
            
            2. CONTEXT & BOUNDARIES:
               - Include at least 3-5 lines of UNCHANGED code before AND after your changes.
               - UNIQUENESS: Ensure the SEARCH block matches ONLY ONE location in the file.
            
            3. NO LAZINESS (ZERO TOLERANCE):
               - NEVER use "..." or comments like `# ... existing code ...` to skip lines.
               - WRITE OUT EVERY SINGLE LINE in the SEARCH block.
               - CRITICAL: When modifying a function, you MUST include the ENTIRE function body in the SEARCH block if the change affects indentation or flow. 
               - Failure to match exact content will cause the patch to be REJECTED.
            
            4. ATOMICITY:
               - Use multiple small SEARCH/REPLACE blocks for disjoint changes.
               - Do not include large chunks of unrelated code.
            
            5. NO JUNK LABELS:
               - Do NOT add labels like 'REPLACE', 'UPDATE', 'CODE', or 'INSERT' inside the blocks. 
               - Just write valid Python code.
            
            6. DOCSTRINGS & COMMENTS (READ-ONLY PREFERRED):
               - DO NOT MODIFY Docstrings or Comments unless the task explicitly asks to update documentation (e.g. deprecation warnings).
               - DO NOT FIX TYPOS in comments/docstrings. Leave them exactly as they are in the SEARCH block.
               - PREFER identifying code blocks using executable lines (def, if, return) rather than comments.

            FORMAT:
            <<<< SEARCH
            old_code_line_1
            old_code_line_2
            ====
            new_code_line_1
            new_code_line_2
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
                        2. You used "..." or comments to skip lines (LAZINESS).
                        3. You used the wrong quotes (' vs ").
                        4. You inserted a LABEL (like 'REPLACE') which corrupted the code.
                        TRY AGAIN. COPY THE CODE EXACTLY CHARACTER-BY-CHARACTER.
                        """
                        
                except Exception as e:
                    print(f"❌ Critical Error in loop: {e}")

        return total_patch

    def _construct_valid_diff(self, original_code, filename, ai_output):
        try:
            if not ai_output or not isinstance(ai_output, str): return ""

            clean_output = re.sub(r"^```[a-zA-Z]*\n", "", ai_output.strip())
            clean_output = re.sub(r"\n```$", "", clean_output)
            
            pattern = r"<{4}\s*SEARCH\s*\n(.*?)\n={4}\s*\n(.*?)\n>{4}"
            matches = re.findall(pattern, clean_output, re.DOTALL)
            
            if not matches: 
                pattern_lazy = r"<{4}\s*SEARCH\n(.*?)\n={4}\n(.*?)\n>{4}"
                matches = re.findall(pattern_lazy, clean_output, re.DOTALL)
                if not matches: return ""

            original_lines = original_code.splitlines(keepends=True)
            modified_lines = original_lines[:] 
            
            def super_normalize(s):
                s = re.sub(r'\s+', '', s).lower()
                s = s.replace("'", '"')
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
                for idx in range(len(original_lines) - n_search + 1):
                    chunk_lines = original_lines[idx : idx + n_search]
                    chunk_str = "".join([l.strip() for l in chunk_lines]) # Strip basic
                    
                    # 1. Check Exact Match
                    search_basic = "".join([l.strip() for l in search_lines])
                    if chunk_str == search_basic:
                        best_idx = idx
                        best_ratio = 1.0
                        break

                    # 2. Check Fuzzy Match
                    # Only normalize for fuzzy matching
                    chunk_norm = super_normalize("\n".join(chunk_lines))
                    
                    # Calculate similarity
                    ratio = difflib.SequenceMatcher(None, chunk_norm, search_norm).ratio()
                    
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_idx = idx
                        if ratio > 0.98: break

                # Acceptance threshold
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
                    return ""
                
            # Apply changes (from bottom to top)
            changes_to_apply.sort(key=lambda x: x["start"], reverse=True)

            for change in changes_to_apply:
                start = change["start"]
                end = change["end"]
                r_block = change["replace"]
                
                # Prepare replacement lines
                r_lines = [line + '\n' if not line.endswith('\n') else line for line in r_block.splitlines()]
                
                # Apply change
                del modified_lines[start:end]
                for l in reversed(r_lines):
                    modified_lines.insert(start, l)

            # Create diff
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