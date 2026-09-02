import os
import subprocess
import sys
import logging

# Configure logging for production diagnostics
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("SkillsEngine")

SKILLS_PATH = os.path.join(os.path.dirname(__file__), "hermes_skills_library")

# The only scripts the engine may execute. `script` reaches run_skill straight
# from an LLM tool call (app.py calculate_petrophysics_properties), and the tool
# schema's "one of: ..." string is a description, not a check — this set is the
# check. It is the union of every script the app actually dispatches: the three
# model-selectable ones plus the hardcoded simulator/curve-fitting call sites.
# vision_auditor.py is deliberately absent: it exists in the tree but no call
# site invokes it, so it must not be reachable by a model-chosen name.
ALLOWED_SCRIPTS = frozenset({
    "petrophysics.py",
    "micp_skill.py",
    "centrifuge_skill.py",
    "curve_fitting_skill.py",
    "history_matching_skill.py",
    "simulation_core.py",
})

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

        python_exe = os.environ.get("PYTHON_EXE", sys.executable)
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
        # Allowlist check FIRST, by basename: an unapproved name is rejected
        # before any path is touched — including an in-tree-but-unapproved script
        # (vision_auditor.py) reached through a crafted category/skill_name.
        base = os.path.basename(script_name or "")
        if base not in ALLOWED_SCRIPTS:
            logger.warning("[skills allowlist] rejected script %r: not in allowlist %s",
                           script_name, sorted(ALLOWED_SCRIPTS))
            return {"error": f"Skill script not permitted: {script_name}"}

        skills_root = os.path.realpath(SKILLS_PATH)
        for candidate in (
            os.path.join(SKILLS_PATH, category, skill_name, "scripts", script_name),
            os.path.join(SKILLS_PATH, category, skill_name, script_name),
        ):
            real = os.path.realpath(candidate)
            # Containment: an allowlisted basename smuggled behind traversal
            # (../../curve_fitting_skill.py) or an absolute script_name — which
            # os.path.join silently honours — must not escape the skills tree.
            try:
                contained = os.path.commonpath([real, skills_root]) == skills_root
            except ValueError:  # different drive on Windows
                contained = False
            if not contained:
                logger.warning("[skills allowlist] rejected path escape %r -> %s",
                               script_name, real)
                return {"error": f"Skill script path not permitted: {script_name}"}
            if os.path.exists(real):
                return real
        return {"error": f"Skill script not found: {script_name}"}

    @staticmethod
    def _run_impl(category, skill_name, script_name, args=None):
        script_path = SkillsEngine._get_script_path(category, skill_name, script_name)
        if isinstance(script_path, dict): return script_path

        python_exe = os.environ.get("PYTHON_EXE", sys.executable)
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
