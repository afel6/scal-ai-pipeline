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
        """
        Executes a script within the hermes_skills_library.
        Args:
            category: e.g., 'research'
            skill_name: e.g., 'arxiv'
            script_name: e.g., 'search_arxiv.py'
            args: list of strings
        """
        script_path = os.path.join(SKILLS_PATH, category, skill_name, "scripts", script_name)
        
        if not os.path.exists(script_path):
            # Fallback check: some skills might not have a /scripts directory
            script_path = os.path.join(SKILLS_PATH, category, skill_name, script_name)
            if not os.path.exists(script_path):
                return {"error": f"Skill script not found: {script_path}"}

        cmd = [sys.executable, script_path]
        if args:
            cmd.extend(args)

        try:
            logger.info(f"Executing Skill: {' '.join(cmd)}")
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                check=False,
                timeout=30 # Safety timeout for production
            )
            return {
                "stdout": result.stdout,
                "stderr": result.stderr,
                "exit_code": result.returncode
            }
        except subprocess.TimeoutExpired:
            return {"error": "Skill execution timed out (30s limit)"}
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
