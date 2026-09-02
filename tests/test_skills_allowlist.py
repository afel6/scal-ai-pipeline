"""B2 — the skills engine must run only allowlisted scripts, never model-chosen
arbitrary files. `script` reaches SkillsEngine straight from an LLM tool call
(app.py: calculate_petrophysics_properties -> run_skill(..., script, ...)), and
the tool schema's "one of: ..." string is a description, not a check.

A script that is not on the allowlist — even one that exists inside the skills
tree (e.g. vision_auditor.py), and even one reached by path traversal — must be
rejected BEFORE subprocess runs. Proven by asserting the subprocess call is
never made.
"""
from unittest.mock import patch

import pytest

import skills_engine
from skills_engine import SkillsEngine


def test_unlisted_but_existing_script_rejected_before_subprocess(caplog):
    # vision_auditor.py exists at hermes_skills_library/maintenance/auditor/ —
    # inside the tree, so containment alone would not stop it. The allowlist must.
    with patch("skills_engine.subprocess.run") as run, \
         patch("skills_engine.subprocess.Popen") as popen:
        with caplog.at_level("WARNING"):
            res = SkillsEngine.run_skill("petroleum", "../maintenance/auditor",
                                         "vision_auditor.py")
    assert "error" in res
    run.assert_not_called()
    popen.assert_not_called()
    assert any("skills allowlist" in r.message.lower() for r in caplog.records)


def test_arbitrary_script_name_rejected_before_subprocess():
    with patch("skills_engine.subprocess.run") as run:
        res = SkillsEngine.run_skill("petroleum", "", "evil_payload.py")
    assert "error" in res
    run.assert_not_called()


def test_path_traversal_outside_tree_rejected_before_subprocess():
    # category="../.." escapes the skills library entirely.
    with patch("skills_engine.subprocess.run") as run:
        res = SkillsEngine.run_skill("../..", "", "app.py")
    assert "error" in res
    run.assert_not_called()


def test_allowlisted_script_reaches_subprocess():
    # curve_fitting_skill.py is a real, invoked skill — it must NOT be blocked.
    class _Res:
        stdout = "{}"
        stderr = ""
        returncode = 0
    with patch("skills_engine.subprocess.run", return_value=_Res()) as run:
        res = SkillsEngine.run_skill("petroleum", "", "curve_fitting_skill.py")
    run.assert_called_once()
    assert res.get("exit_code") == 0


def test_allowlist_is_the_declared_skill_set():
    # Guard against the allowlist silently drifting from the scripts the app
    # actually dispatches (petrophysics/micp/centrifuge/curve_fitting/
    # history_matching/simulation_core).
    for name in ("petrophysics.py", "micp_skill.py", "centrifuge_skill.py",
                 "curve_fitting_skill.py", "history_matching_skill.py",
                 "simulation_core.py"):
        assert name in skills_engine.ALLOWED_SCRIPTS
    assert "vision_auditor.py" not in skills_engine.ALLOWED_SCRIPTS
