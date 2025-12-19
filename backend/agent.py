import os
import json
import re
import difflib  # <--- Important library to automatically generate standard diffs
from google import genai
from google.genai import types
from dotenv import load_dotenv

load_dotenv()

class NoCodeAgent:
    def __init__(self, model_name="gemini-2.0-flash"):
        self.model_name = model_name
        api_key = os.getenv("GOOGLE_API_KEY")
        if not api_key:
            print("❌ ERROR: GOOGLE_API_KEY not found")
            self.client = None
        else:
            self.client = genai.Client(api_key=api_key)

    def locate_files(self, doc_diff: str, repo_structure: str = "") -> list:
        if not self.client: return []
        prompt = f"""
        ROLE: You are a senior software developer.
        TASK: Identify which PYTHON SOURCE CODE files need to be modified based on the documentation changes.
        IMPORTANT RULES:
        1. Ignore documentation files (.rst, .md). Focus on .py files.
        2. Return a JSON list of file paths.
        DOCUMENTATION CHANGES:
        {doc_diff}
        INSTRUCTION: Return JSON list only. Example: ["requests/models.py"]
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
            )
            files = json.loads(response.text)
            print(f"🤖 [Gemini] Proposed file to fix: {files}")
            return files
        except Exception as e:
            print(f"⚠️ Locate Error: {e}")
            return []

    def generate_patch(self, doc_diff: str, augmentations: dict, code_context: dict, instance_id: str = None) -> str:
        """
        New Strategy:
        1. Ask AI for the old code segment (SEARCH) and the new code segment (REPLACE).
        2. Use Python to find and replace within the original string.
        3. Use Python `difflib` to generate a 100% standard patch.
        """
        if not self.client or not code_context: return ""

        # Get content of the first file (assuming fixing 1 main file)
        target_file = list(code_context.keys())[0]
        original_code = code_context[target_file]

        prompt = f"""
        ROLE: You are an expert Python developer.
        TASK: Fix the issue described below. 
        Instead of writing a complex git diff, simply provide the **Exact Code Block to Search For** and the **New Code Block to Replace It With**.

        CONTEXT:
        Task ID: {instance_id}
        Target File: {target_file}

        ISSUE DESCRIPTION:
        {doc_diff}

        FULL FILE CONTENT (READ-ONLY):
        {original_code}

        INSTRUCTION:
        1. Find the specific block of code in `FULL FILE CONTENT` that needs fixing.
        2. Output a SEARCH block containing that EXACT code (copy-paste exactly, including indentation).
        3. Output a REPLACE block containing the corrected code.
        
        FORMAT:
        <<<< SEARCH
        def example():
            old_code_here
        ====
        def example():
            new_fixed_code_here
        >>>>

        RULES:
        - The SEARCH block must match the existing code character-for-character (including whitespace) so I can find it programmatically.
        - Only fix Python code (.py). Do not fix docs.
        """

        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(temperature=0.1) # Absolute precision required
            )
            
            # --- HANDLE "SEARCH & REPLACE" LOGIC ---
            ai_output = response.text
            patch = self._construct_valid_diff(original_code, target_file, ai_output)
            return patch
            
        except Exception as e:
            print(f"❌ Generate Patch Error: {e}")
            return ""

    def _construct_valid_diff(self, original_code, filename, ai_output):
        """
        This function receives the Search/Replace block from AI,
        performs the replacement automatically, and creates a standard Unified Diff using Python.
        """
        try:
            # 1. Parse AI Output
            pattern = r"<<<< SEARCH\n(.*?)\n====\n(.*?)\n>>>>"
            match = re.search(pattern, ai_output, re.DOTALL)
            
            if not match:
                print("⚠️ SEARCH/REPLACE block not found in correct format.")
                return ""

            search_block = match.group(1) # Do not strip() immediately to preserve indentation
            replace_block = match.group(2)

            # 2. Locate position in original code
            # Try exact match
            if search_block not in original_code:
                # If AI missed extra whitespace, try a light strip
                print("⚠️ Exact match failed, trying more flexible search...")
                if search_block.strip() in original_code:
                    # More complex logic to replace when strip matches (skipped to simplify demo)
                    # Here we prioritize that the AI must copy correctly.
                    pass 
                else:
                    print("❌ Error: AI fabricated code not found in original file (Hallucination).")
                    return ""

            # 3. Create new file content
            new_code = original_code.replace(search_block, replace_block, 1) # Replace once

            # 4. Use Python library to create a precise standard Diff
            diff = difflib.unified_diff(
                original_code.splitlines(keepends=True),
                new_code.splitlines(keepends=True),
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}"
            )
            
            diff_text = "".join(diff)
            
            if not diff_text:
                print("⚠️ New code is identical to old code, no patch created.")
                return ""

            print("✅ Valid Patch created using difflib!")
            return diff_text

        except Exception as e:
            print(f"❌ Error building diff: {e}")
            return ""