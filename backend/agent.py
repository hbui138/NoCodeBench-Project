import os
import json
import re
import difflib
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
        ROLE: You are a senior software architect.
        TASK: Identify ALL file paths that need to be modified or created to fix the issue.
        
        INPUT ISSUE:
        {doc_diff[:10000]}
        
        CRITICAL RULE:
        - If the fix requires modifying a function in File A, list "File A".
        - If the fix requires adding a NEW class/exception (e.g. JSONDecodeError), you MUST also list the file where that class is defined (e.g. "requests/exceptions.py" or "requests/utils.py").
        - Think about dependencies. Don't just list the file throwing the error.
        
        OUTPUT FORMAT: 
        Return ONLY a JSON list of strings. Example: ["requests/models.py", "requests/exceptions.py"]
        """
        try:
            response = self.client.models.generate_content(
                model=self.model_name,
                contents=prompt,
                config=types.GenerateContentConfig(response_mime_type="application/json", temperature=0.1)
            )
            files = json.loads(response.text)
            print(f"🤖 [Gemini] Proposed files to fix: {files}")
            return files
        except Exception as e:
            print(f"⚠️ Locate Error: {e}")
            return []

    def generate_patch(self, doc_diff: str, augmentations: dict, code_context: dict, instance_id: str = None) -> str:
        """
        This function generates code patches based on the provided doc_diff and code context.
        It returns a unified diff string that can be applied to the codebase.
        """
        if not self.client or not code_context: return ""

        total_patch = ""
        
        # 1. Create a summary of all files' content for context
        all_files_context_str = ""
        for fname, content in code_context.items():
            all_files_context_str += f"\n--- FILE: {fname} ---\n{content[:1000]}...\n(truncated)\n"

        # 2. Loop through each target file to generate patches
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
            3. If NO, return empty string.
            4. If you need to define a new Exception (like JSONDecodeError) and this file is 'exceptions.py', add it here.
            5. If you need to use that Exception and this file is 'models.py', import and use it here.

            FORMAT:
            <<<< SEARCH
            old_code_line_1
            old_code_line_2
            ====
            new_code_line_1
            new_code_line_2
            >>>>

            RULES:
            - SEARCH block must be character-perfect match (indentation is vital).
            - Use multiple SEARCH/REPLACE blocks if you need to edit multiple places in this file (e.g. Imports at top, Logic at bottom).
            """

            try:
                response = self.client.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=types.GenerateContentConfig(temperature=0.1)
                )
                
                ai_output = response.text
                
                # Call helper to construct valid diff from AI output
                file_diff = self._construct_valid_diff(original_code, target_file, ai_output)
                
                if file_diff:
                    total_patch += file_diff + "\n"
                    print(f"  -> Generated patch for {target_file}")
                else:
                    print(f"  -> No changes needed for {target_file}")
                
            except Exception as e:
                print(f"❌ Generate Patch Error for {target_file}: {e}")

        return total_patch

    def _construct_valid_diff(self, original_code, filename, ai_output):
        try:
            # 1. IMPORTANT: Use re.findall to find ALL change blocks
            # Instead of re.search (which only finds the first one)
            pattern = r"<<<< SEARCH\n(.*?)\n====\n(.*?)\n>>>>"
            matches = re.findall(pattern, ai_output, re.DOTALL)
            
            if not matches:
                return ""

            current_code = original_code
            applied_count = 0

            # 2. Loop through each block and apply changes
            for search_block, replace_block in matches:
                
                # Case 1: Find exact match first
                if search_block in current_code:
                    current_code = current_code.replace(search_block, replace_block, 1)
                    applied_count += 1
                    continue
                
                # Case 2: Fuzzy match by normalizing whitespace
                def normalize(s): 
                    return '\n'.join([line.rstrip() for line in s.splitlines()])

                norm_search = normalize(search_block)
                norm_code = normalize(current_code)
                
                if norm_search in norm_code:
                    print(f"  ⚠️ Fuzzy match used for block in {filename}...")
                    current_code = norm_code.replace(norm_search, normalize(replace_block), 1)
                    original_code = normalize(original_code)
                    applied_count += 1
                else:
                    print(f"  ❌ Failed to apply a block in {filename}. AI Search block mismatched.")
                    print(f"  --> AI wrote: {search_block[:50]}...")

            if applied_count == 0:
                return ""

            # 3. Create unified diff
            diff = difflib.unified_diff(
                original_code.splitlines(keepends=True),
                current_code.splitlines(keepends=True),
                fromfile=f"a/{filename}",
                tofile=f"b/{filename}"
            )
            
            return "".join(diff)

        except Exception as e:
            print(f"❌ Error logic diff: {e}")
            return ""