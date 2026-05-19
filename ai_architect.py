import json
import logging
import re
from typing import Dict, Any
from openai import OpenAI
from config import config
from smart_features import SmartProjectDetector

logger = logging.getLogger(__name__)

class AIArchitect:
    def __init__(self):
        self.client = OpenAI(api_key=config.DEEPSEEK_API_KEY, base_url=config.DEEPSEEK_BASE_URL)

    async def generate_blueprint(self, prompt: str) -> Dict[str, Any]:
        lang = SmartProjectDetector.detect_language(prompt)
        size = SmartProjectDetector.detect_size(prompt)
        ptype = SmartProjectDetector.detect_type(prompt)

        max_files = 5
        if size == "small":
            max_files = 5
        elif size == "medium":
            max_files = 12
        else:
            max_files = 30

        sys_prompt = f"""You are a software architect. Output JSON blueprint for a {size} {ptype} project in {lang}.
Max {max_files} files.
Do NOT include README.md.
Keep descriptions short (<30 chars).
Structure:
{{
  "project_name": "string",
  "description": "string",
  "tech_stack": ["{lang}"],
  "file_structure": [
    {{"path": "src/main.{'py' if lang=='python' else 'php' if lang=='php' else 'js'}", "description": "main", "dependencies": []}}
  ],
  "setup_instructions": []
}}
"""
        response = self.client.chat.completions.create(
            model=config.DEEPSEEK_FLASH_MODEL,
            messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=2000,
            response_format={"type": "json_object"}
        )
        blueprint = json.loads(response.choices[0].message.content)
        # remove any README
        blueprint['file_structure'] = [f for f in blueprint.get('file_structure', []) if f['path'] != 'README.md']
        return blueprint

    async def generate_file(self, file_info: Dict, blueprint: Dict, file_index: int, total: int, progress_callback=None) -> str:
        path = file_info['path']
        desc = file_info.get('description', '')
        deps = file_info.get('dependencies', [])
        tech = ", ".join(blueprint.get('tech_stack', []))
        sys_prompt = f"""You are an expert {tech} engineer. Write production-ready code for {path}.
- Full error handling, type hints (Python) or proper types.
- Docstrings.
- No TODOs, no placeholders.
- Use these dependencies: {deps}.
Output ONLY raw code, no markdown, no explanations.
"""
        try:
            response = self.client.chat.completions.create(
                model=config.DEEPSEEK_CODER_MODEL,
                messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": f"Purpose: {desc}"}],
                temperature=0.1,
                max_tokens=config.MAX_TOKENS_CODER
            )
            content = response.choices[0].message.content
            # clean markdown
            if content.startswith('```'):
                lines = content.split('\n')
                if lines[0].startswith('```'):
                    lines = lines[1:]
                if lines and lines[-1].strip() == '```':
                    lines = lines[:-1]
                content = '\n'.join(lines)
            if config.SELF_REVIEW_CODE:
                content = await self._self_review(content, path)
            if progress_callback:
                await progress_callback(f"✅ {path}")
            return content.strip()
        except Exception as e:
            logger.error(f"Error generating {path}: {e}")
            return f"# Error generating {path}\npass\n"

    async def _self_review(self, code: str, path: str) -> str:
        sys_prompt = f"""Review the code for {path}. If you find any syntax error, missing imports, logical errors, or incomplete code, rewrite the entire file with fixes. If no issues, output exactly the original code. No extra comments."""
        try:
            response = self.client.chat.completions.create(
                model=config.DEEPSEEK_CODER_MODEL,
                messages=[{"role": "system", "content": sys_prompt}, {"role": "user", "content": code}],
                temperature=0.0,
                max_tokens=config.MAX_TOKENS_CODER
            )
            reviewed = response.choices[0].message.content
            if reviewed.startswith('```'):
                reviewed = '\n'.join(reviewed.split('\n')[1:-1])
            return reviewed.strip()
        except:
            return code

    async def generate_all_files(self, blueprint: Dict, progress_callback=None) -> Dict[str, str]:
        files = {}
        file_list = blueprint.get('file_structure', [])
        total = len(file_list)
        for i, finfo in enumerate(file_list, 1):
            if progress_callback:
                await progress_callback(f"📝 [{i}/{total}] Generating {finfo['path']}...")
            content = await self.generate_file(finfo, blueprint, i, total, progress_callback)
            files[finfo['path']] = content
        # add requirements.txt if python
        if any('python' in t.lower() for t in blueprint.get('tech_stack', [])):
            files['requirements.txt'] = "fastapi\nuvicorn\n"
        if '.gitignore' not in files:
            files['.gitignore'] = "__pycache__/\n.env\n*.pyc\n"
        return files