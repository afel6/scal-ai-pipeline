import os
import subprocess
import sys
import json
import logging

# Configure logging for production diagnostics
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SkillsEngine")

SKILLS_PATH = os.path.join(os.path.dirname(__file__), "hermes_skills_library")

class SkillsEngine:
    @staticmethod
    def run_skill(category, skill_name, script_name, args=None):
        """Synchronous version for simple calls."""
        return SkillsEngine._run_impl(category, skill_name, script_name, args)

    @staticmethod
    def run_skill_stream(category, skill_name, script_name, args=None):
        """Generator version for long-running scripts with progress."""
        script_path = SkillsEngine._get_script_path(category, skill_name, script_name)
        if isinstance(script_path, dict): # error
            yield script_path
            return

        python_exe = os.environ.get("PYTHON_EXE", r"C:\Users\Asus\AppData\Local\Programs\Python\Python313\python.exe")
        cmd = [python_exe, script_path]
        if args: cmd.extend(args)

        try:
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                bufsize=1
            )
            
            # Read stdout line by line
            for line in process.stdout:
                yield {"stdout": line}
            
            # Read stderr if any (after stdout completes or partially)
            stderr_out = process.stderr.read()
            if stderr_out:
                yield {"stderr": stderr_out}
                
            process.wait(timeout=5)
            yield {"exit_code": process.returncode}
        except Exception as e:
            yield {"error": str(e)}

    @staticmethod
    def _get_script_path(category, skill_name, script_name):
        script_path = os.path.join(SKILLS_PATH, category, skill_name, "scripts", script_name)
        if not os.path.exists(script_path):
            script_path = os.path.join(SKILLS_PATH, category, skill_name, script_name)
            if not os.path.exists(script_path):
                return {"error": f"Skill script not found: {script_name}"}
        return script_path

    @staticmethod
    def _run_impl(category, skill_name, script_name, args=None):
        script_path = SkillsEngine._get_script_path(category, skill_name, script_name)
        if isinstance(script_path, dict): return script_path

        python_exe = os.environ.get("PYTHON_EXE", r"C:\Users\Asus\AppData\Local\Programs\Python\Python313\python.exe")
        cmd = [python_exe, script_path]
        if args: cmd.extend(args)

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, timeout=60)
            return {"stdout": result.stdout, "stderr": result.stderr, "exit_code": result.returncode}
        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def list_categories():
        if not os.path.exists(SKILLS_PATH):
            return []
        return [d for d in os.listdir(SKILLS_PATH) if os.path.isdir(os.path.join(SKILLS_PATH, d))]

    @staticmethod
    def list_skills(category):
        cat_path = os.path.join(SKILLS_PATH, category)
        if not os.path.exists(cat_path):
            return []
        return [d for d in os.listdir(cat_path) if os.path.isdir(os.path.join(cat_path, d))]
