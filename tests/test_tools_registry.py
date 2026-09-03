"""D3.2 — one declarative tool registry and one tool contract.

Tool identity (name, schema, validation, error shape, owning agent) lives in
tools_registry.REGISTRY — the single place D8's manifest will read — and every
tool result reaching the loop is a ToolResult: ok, values (each with a
source), error, text. No tool returns a bare number: a numeric result without
a source is the pattern this project exists to eliminate.
"""
import json

import pytest

import app
import tools_registry as tr

EXPECTED_TOOLS = {
    "calculate_petrophysics_properties", "execute_python_simulation", "generate_mermaid_diagram",
    "fit_petrophysical_curve", "agentic_history_matching", "generate_executive_report",
    "get_audit_history", "sandbox_fit_brooks_corey", "sandbox_fit_archie", "hybrid_geological_search",
}


# --- the registry is the single source of tool identity ---------------------------

def test_registry_lists_every_tool_with_owner_schema_and_error_shape():
    assert set(tr.REGISTRY) == EXPECTED_TOOLS
    for name, spec in tr.REGISTRY.items():
        assert spec.name == name and spec.owner == "hviel"
        assert spec.parameters["type"] == "OBJECT" and isinstance(spec.parameters.get("properties"), dict)
        assert spec.error_shape in ("warning-prefix", "json-status")
        assert spec.description


def test_the_model_facing_schema_is_derived_from_the_registry():
    decls = app._HVIEL_TOOLS[0]["function_declarations"]
    assert [d["name"] for d in decls] == list(tr.REGISTRY)
    assert app._HVIEL_TOOLS == tr.schemas()           # derived, not duplicated


def test_dispatch_and_render_know_no_tool_outside_the_registry():
    """Every name the loop can dispatch or render is registered — grep the
    dispatcher for its `name == "…"` branches."""
    import inspect
    import re
    src = inspect.getsource(app.PRCChatAssistant._execute_tool) + inspect.getsource(app.PRCChatAssistant._format_tool_response_impl)
    dispatched = set(re.findall(r'name == "([a-z_]+)"', src))
    assert dispatched <= set(tr.REGISTRY), dispatched - set(tr.REGISTRY)


def test_validate_args_reports_missing_required_and_unknown_keys():
    spec = tr.REGISTRY["sandbox_fit_archie"]
    assert tr.validate_args(spec, {"x": [1], "y": [1], "model_type": "RI"}) == []
    problems = tr.validate_args(spec, {"x": [1], "bogus": 1})
    assert any("y" in p and "missing" in p for p in problems)
    assert any("bogus" in p for p in problems)


# --- the contract: ok / values with sources / error ------------------------------------

def test_a_refusal_is_a_failed_result_with_no_values():
    spec = tr.REGISTRY["fit_petrophysical_curve"]
    res = tr.normalize(spec, raw='{"status": "ready", "model": "ri"}',
                       rendered="⚠️ Physics boundary check failed for the Resistivity Index fit: …", dispatch_ok=True)
    assert res.ok is False and res.values == {} and "Physics boundary" in res.error


def test_a_successful_fit_carries_fitted_values_with_sources():
    spec = tr.REGISTRY["fit_petrophysical_curve"]
    plot = {"title": "RI", "curves": [], "metadata": {"archie": {"n": 1.85}}}
    res = tr.normalize(spec, raw='{"status": "ready", "model": "ri"}',
                       rendered=f"__PRC_PLOT__\n{json.dumps(plot)}\n\n", dispatch_ok=True)
    assert res.ok is True and res.error is None
    assert res.values["n"] == {"value": 1.85, "source": "fitted:cache"}


def test_a_corrected_sandbox_fit_yields_no_numeric_value():
    spec = tr.REGISTRY["sandbox_fit_archie"]
    plot = {"metadata": {"archie": {"n": None, "fitted": False, "note": "out of bounds (n=1.200)"}}}
    res = tr.normalize(spec, raw="{}", rendered=f"__PRC_PLOT__\n{json.dumps(plot)}\n\n", dispatch_ok=True)
    assert res.ok is True and res.values == {}


def test_model_supplied_inputs_are_labelled_as_such():
    spec = tr.REGISTRY["sandbox_fit_archie"]
    plot = {"metadata": {"archie": {"n": 2.1, "fitted": True}}}
    res = tr.normalize(spec, raw="{}", rendered=f"__PRC_PLOT__\n{json.dumps(plot)}\n\n", dispatch_ok=True)
    assert res.values["n"]["source"] == "fitted:model-args"


def test_petrophysics_numbers_carry_a_source():
    spec = tr.REGISTRY["calculate_petrophysics_properties"]
    raw = json.dumps({"status": "success", "samples": {"S1": {"porosity": 0.21, "permeability_md": 12.5, "name": "S1"}}})
    res = tr.normalize(spec, raw=raw, rendered="table", dispatch_ok=True)
    assert res.ok is True
    assert res.values["S1.porosity"] == {"value": 0.21, "source": "computed:model-args"}
    assert all("source" in v for v in res.values.values())


def test_every_numeric_tool_declares_how_its_values_are_sourced():
    for name, spec in tr.REGISTRY.items():
        if spec.numeric:
            assert spec.values_from != "none", name


def test_a_dispatch_failure_is_a_failed_result():
    spec = tr.REGISTRY["execute_python_simulation"]
    res = tr.normalize(spec, raw='{"status": "error", "error": "simulation crashed"}', rendered="", dispatch_ok=False)
    assert res.ok is False and res.error == "simulation crashed" and res.values == {}


# --- through the loop on mock: failure → ok False, no success text reaches the model ---------

@pytest.mark.parametrize("tool", sorted(EXPECTED_TOOLS))
def test_every_tools_failure_reaches_the_model_as_a_failure(tool, monkeypatch):
    spec = tr.REGISTRY[tool]
    res = tr.normalize(spec, raw='{"status": "error", "error": "forced failure"}', rendered="", dispatch_ok=False)
    summary = app.assistant._tool_result_summary(tool, res.raw, res.ok)
    assert summary["status"] == "error" and "forced failure" in summary["error"]
    assert "computed" not in json.dumps(summary).lower() and "success" not in summary["status"]
