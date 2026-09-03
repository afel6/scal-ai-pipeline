"""D3.1 visibility — batch scal-app-2 (app.py: ledger + citation gate, tool
dispatch `_execute_tool`, formatter `_format_tool_response_impl`, the model
summary; tools_registry value sources).

Every test forces the failure (a monkeypatched skill runner / retriever, a
payload of the bad shape, a sheet with blank cells) and asserts what the
CALLER sees: the `(is_final, ok, payload)` the loop receives, the ledger row
the gate reads, the rendered text the user gets, the summary dict the model
gets, or an entry on the request degradation channel (`app.degradations()`).
A log line alone never passes.
"""
import json

import numpy as np
import pytest

import app
import tools_registry as tr
from scenario_support import EMAIL, clear_session, seed_session

SID = "d3-vis-app2"


@pytest.fixture(autouse=True)
def _fresh_request_state():
    app._tls.degradations = []
    app._tls.current_session_id = SID
    app.reset_tool_call_ledger(SID)
    yield
    app._tls.degradations = []
    clear_session(SID)
    try:
        app.db("DELETE FROM physics_audits WHERE session_id=?", (SID,))
    except Exception:
        pass


def _seed_sheet(sheet: dict, name: str = "Sheet1") -> None:
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE[SID] = {"ground_truth": "seeded", "labeled_values": {},
                                       "flat_vectors": {}, "raw_excel_data": {name: sheet}}


def _degraded(kind: str) -> bool:
    return any(d.startswith(kind + ":") for d in app.degradations())


def _run(name: str, args: dict):
    """The final (is_final, ok, payload) the chat loop receives from dispatch."""
    return list(app.assistant._execute_tool(app._ChatFuncCall(name, args)))[-1]


def _capturing_run_skill(monkeypatch, stdout: str):
    """Replace the subprocess runner; return the list of parsed params it was given."""
    seen = []

    def fake(category, skill_name, script_name, args=None):
        seen.append(json.loads(args[-1]))
        return {"stdout": stdout, "stderr": "", "exit_code": 0}
    monkeypatch.setattr(app.SkillsEngine, "run_skill", staticmethod(fake))
    return seen


def _bc(sw, swr, snr, krw_max, kro_max):
    se = np.clip((np.asarray(sw) - swr) / (1 - swr - snr), 0, 1)
    return (krw_max * se ** 2).tolist(), (kro_max * (1 - se) ** 2).tolist()


# ── _extract_fitted_values / ledger / gate ───────────────────────────────────

def test_unparseable_plot_metadata_is_degraded_and_backs_nothing():
    broken = "__PRC_PLOT__\n{\"metadata\": }\n\n"
    assert app._extract_fitted_values(broken) == {} and app._rendered_parameters(broken) == []
    assert _degraded("plot-metadata-unparseable"), app.degradations()
    # Through the ledger: the row records neither a value nor a parameter, so
    # the gate strips a stated n instead of accepting it by tool name.
    monkey = pytest.MonkeyPatch()
    monkey.setattr(app.assistant, "_format_tool_response_impl", lambda name, args, result: broken)
    try:
        app.assistant._format_tool_response("fit_petrophysical_curve", {"model": "ri"}, '{"status": "ready", "model": "ri"}')
    finally:
        monkey.undo()
    row = app.get_tool_call_records(SID)[-1]
    assert row["status"] == "success" and row["values"] == {} and row["parameters"] == []
    assert "1.987" not in app.enforce_citation_gate("the fitted exponent n = 1.987", SID)


def test_a_success_that_fitted_nothing_does_not_back_archie_n():
    """A J-function success by the same TOOL NAME used to make `not backed`
    true and pass any stated n verbatim (existence-only by name)."""
    sw, pc = [0.3, 0.5, 0.7, 0.9], [40.0, 20.0, 10.0, 5.0]
    out = app.assistant._format_tool_response("fit_petrophysical_curve",
                                              {"model": "jfunction", "sw": sw, "pc": pc, "k_md": 10, "phi_val": 0.2},
                                              '{"status": "ready", "model": "jfunction"}')
    assert out.startswith("__PRC_PLOT__")
    row = app.get_tool_call_records(SID)[-1]
    assert row["status"] == "success" and row["parameters"] == []      # produced no gated value
    gated = app.enforce_citation_gate("The Archie saturation exponent n is 1.987.", SID)
    assert "1.987" not in gated and "no successful fit produced this value" in gated


def test_a_success_that_fitted_n_still_backs_n_and_only_n():
    app.record_tool_call(SID, "fit_petrophysical_curve", "success", {"model": "ri"}, ["n"], values={"n": 1.85})
    assert app.enforce_citation_gate("the exponent n is 1.850", SID) == "the exponent n is 1.850"
    assert "[unverified" in app.enforce_citation_gate("the cementation exponent m is 2.1", SID)


# ── execute_python_simulation ────────────────────────────────────────────────

def _fake_stream(monkeypatch, stdout: str, exit_code: int = 0):
    seen = []

    def fake(category, skill_name, script_name, args=None):
        seen.append(json.loads(args[0]))
        yield {"stdout": stdout}
        yield {"exit_code": exit_code}
    monkeypatch.setattr(app.SkillsEngine, "run_skill_stream", staticmethod(fake))
    return seen


def test_simulation_error_payload_with_exit_0_is_a_failed_step(monkeypatch):
    _fake_stream(monkeypatch, json.dumps({"status": "error", "message": "success was not achieved: nx missing"}))
    final = _run("execute_python_simulation", {"model": "brooks_corey", "mode": "2d", "params": {"swr": 0.2}})
    assert final[1] is False
    assert json.loads(final[2])["status"] == "error" and "nx missing" in json.loads(final[2])["error"]
    assert "__SIMULATION_START__" not in final[2]          # the 'success' substring no longer wraps it


def test_simulation_defaults_are_filled_once_and_marked_everywhere(monkeypatch):
    sw = np.linspace(0.2, 0.8, 20).tolist()
    krw, kro = _bc(sw, 0.2, 0.2, 0.5, 0.8)
    seen = _fake_stream(monkeypatch, "")

    def fake(category, skill_name, script_name, args=None):
        p = json.loads(args[0])
        seen.append(p)
        yield {"stdout": json.dumps({"status": "success", "mode": "1d", "sw": sw, "krw": krw, "kro": kro, "params": p})}
        yield {"exit_code": 0}
    monkeypatch.setattr(app.SkillsEngine, "run_skill_stream", staticmethod(fake))

    final = _run("execute_python_simulation", {"model": "brooks_corey", "mode": "1d", "params": {"nw": 2, "no": 2}})
    assert final[1] is True
    assert seen[0]["swr"] == 0.2 and seen[0]["defaulted"] == ["swr", "snr", "krw_max", "kro_max"]
    assert _degraded("simulation-defaults"), app.degradations()
    summary = app.assistant._tool_result_summary("execute_python_simulation", final[2], True)
    assert summary["defaulted"] == ["swr", "snr", "krw_max", "kro_max"] and "NOT supplied" in summary["note"]
    fmt = app.assistant._format_tool_response("execute_python_simulation", {"mode": "1d"}, final[2])
    meta = json.loads(fmt.split("__PRC_PLOT__", 1)[1].strip())["metadata"]
    assert meta["endpoints"]["Swi"] == pytest.approx(0.2)         # was 0.15: a second, different default


def test_formatter_no_longer_invents_endpoints_for_a_payload_without_them():
    raw = json.dumps({"status": "success", "mode": "1d", "sw": [0.2, 0.5, 0.8], "krw": [0, 0.1, 0.5],
                      "kro": [0.8, 0.2, 0], "params": {}})
    fmt = app.assistant._format_tool_response("execute_python_simulation", {"mode": "1d"}, raw)
    assert fmt.startswith("⚠️") and "KeyError" in fmt
    assert app.get_tool_call_records(SID)[-1]["status"] == "error"


def test_defaulted_simulation_values_carry_a_defaulted_source():
    raw = ("__SIMULATION_START__\n" + json.dumps({"status": "success", "mode": "2d",
           "params": {"swr": 0.2, "nw": 2.5, "defaulted": ["swr"]}}) + "\n__SIMULATION_END__")
    res = tr.normalize(tr.REGISTRY["execute_python_simulation"], raw, raw, True)
    assert res.values["swr"]["source"] == "defaulted:simulation-core"
    assert res.values["nw"]["source"] == "simulated:model-args"


# ── calculate_petrophysics_properties dispatch ───────────────────────────────

def test_klinkenberg_blank_pm_cell_drops_the_row_instead_of_14_7_psi(monkeypatch):
    _seed_sheet({"ka": [10.0, 20.0, 30.0], "pm": [50.0, None, 70.0], "depth": [100.0, 101.0, 102.0]})
    seen = _capturing_run_skill(monkeypatch, json.dumps({"status": "success", "total_samples": 2, "samples": []}))
    _run("calculate_petrophysics_properties", {"script": "petrophysics.py", "model": "klinkenberg", "params": {}})
    p = seen[0]
    assert p["ka"] == [10.0, 30.0] and p["pm"] == [50.0, 70.0] and p["depth"] == [100.0, 102.0]
    assert 14.7 not in p["pm"]
    assert _degraded("rows-dropped"), app.degradations()


def test_nmr_columns_are_filtered_row_wise_not_independently(monkeypatch):
    _seed_sheet({"t2": [1.0, 2.0, 3.0], "amplitude": [0.1, None, 0.3], "depth": [5.0, 6.0, 7.0]})
    seen = _capturing_run_skill(monkeypatch, json.dumps({"status": "success", "total_samples": 2, "samples": []}))
    _run("calculate_petrophysics_properties", {"script": "petrophysics.py", "model": "nmr_t2_distribution", "params": {}})
    p = seen[0]
    assert p["t2_times"] == [1.0, 3.0] and p["amplitudes"] == [0.1, 0.3] and p["depth"] == [5.0, 7.0]


def test_all_rows_incomplete_is_a_refusal_not_an_empty_success(monkeypatch):
    _seed_sheet({"ka": [10.0, 20.0], "pm": [None, None], "depth": [1.0, 2.0]})
    seen = _capturing_run_skill(monkeypatch, "{}")
    final = _run("calculate_petrophysics_properties", {"script": "petrophysics.py", "model": "klinkenberg", "params": {}})
    assert final[1] is False and "no complete data rows" in json.loads(final[2])["error"]
    assert seen == []                                            # the script never ran on empty arrays


def test_xrd_blank_mineral_drops_the_row_and_synthetic_depth_is_labelled(monkeypatch):
    _seed_sheet({"Quartz (%)": [50.0, None, 60.0], "Calcite (%)": [50.0, 40.0, 40.0]})
    orig = app.SkillsEngine.run_skill
    seen = []

    def spy(category, skill_name, script_name, args=None):
        seen.append(json.loads(args[-1]))
        return orig(category, skill_name, script_name, args)
    monkeypatch.setattr(app.SkillsEngine, "run_skill", staticmethod(spy))
    final = _run("calculate_petrophysics_properties", {"script": "petrophysics.py", "model": "xrd_mineralogy", "params": {}})
    assert seen[0]["minerals"] == {"quartz": [50.0, 60.0], "calcite": [50.0, 40.0]}
    assert seen[0]["depth"] == [1.0, 3.0]                       # row indices of the rows kept, no 0.0 mineral
    payload = json.loads(final[2])
    assert final[1] is True and payload["depth_synthetic"] is True and payload["input_source"] == "cache"
    assert _degraded("rows-dropped") and _degraded("depth-synthesized"), app.degradations()
    fmt = app.assistant._format_tool_response("calculate_petrophysics_properties",
                                              {"script": "petrophysics.py", "model": "xrd_mineralogy", "params": {}}, final[2])
    assert "| # | Row # (no depth column) |" in fmt and "| # | Depth |" not in fmt


def test_provenance_line_names_model_args_when_arrays_came_from_the_call(monkeypatch):
    _seed_sheet({"ka": [1.0, 2.0], "pm": [3.0, 4.0], "depth": [1.0, 2.0]})       # a sheet exists, but is NOT used
    _capturing_run_skill(monkeypatch, json.dumps({"status": "success", "total_samples": 1, "samples": [
        {"sample": 1, "depth": 9.0, "ka_md": 5.0, "pm_psi": 40.0, "kl_md": 4.5, "b_slippage": 0.3}]}))
    args = {"script": "petrophysics.py", "model": "klinkenberg", "params": {"ka": [5.0], "pm": [40.0]}}
    final = _run("calculate_petrophysics_properties", args)
    assert json.loads(final[2])["input_source"] == "model-args"
    fmt = app.assistant._format_tool_response("calculate_petrophysics_properties", args, final[2])
    assert "arrays supplied in the tool call (model-args)" in fmt
    assert "Aligned vectors from" not in fmt


def test_regress_archie_result_is_rendered_labelled_and_gate_safe(monkeypatch):
    _capturing_run_skill(monkeypatch, json.dumps({"n": 2.1234, "r_squared": 0.9912}))
    args = {"script": "petrophysics.py", "model": "regress_archie_n", "params": {"sw": [0.9, 0.5], "ri": [1.2, 4.0]}}
    final = _run("calculate_petrophysics_properties", args)
    fmt = app.assistant._format_tool_response("calculate_petrophysics_properties", args, final[2])
    assert "2.1234" in fmt and "model-args" in fmt and "not the verified" in fmt
    assert app.enforce_citation_gate(fmt, SID) == fmt            # neither accepted as fitted nor garbled


def test_history_matching_timeout_is_a_failed_step(monkeypatch):
    monkeypatch.setattr(app.SkillsEngine, "run_skill",
                        staticmethod(lambda *a, **k: {"error": "Skill execution timed out after 60s"}))
    final = _run("agentic_history_matching", {"sw": [0.2, 0.5], "krw": [0, 0.3], "kro": [0.8, 0.2]})
    assert final[1] is False and "timed out" in json.loads(final[2])["error"]


def test_hybrid_vector_outage_is_reported_as_an_outage_not_no_matches(monkeypatch):
    import rag_database

    class Boom:
        def __init__(self, *a, **k):
            raise RuntimeError("chroma store unreadable (simulated)")
    monkeypatch.setattr(rag_database, "RAGDatabase", Boom)
    args = {"query_text": "Sirte basin analogs", "porous_low": 0.1, "porous_high": 0.2, "perm_low": 1, "perm_high": 50}
    final = _run("hybrid_geological_search", args)
    assert final[1] is True
    assert "chroma store unreadable" in json.loads(final[2])["vector_unavailable"]
    fmt = app.assistant._format_tool_response("hybrid_geological_search", args, final[2])
    assert "vector search unavailable" in fmt and "no vector matches" not in fmt
    assert _degraded("vector-retriever"), app.degradations()


# ── the formatter: outcome, not "reached this line" ──────────────────────────

def test_analytic_guard_fall_through_is_a_refusal_the_ledger_and_model_see():
    raw = '{"status": "ready", "model": "micp"}'
    fmt = app.assistant._format_tool_response("fit_petrophysical_curve", {"model": "micp", "pc": [10.0], "s_hg": [0.1]}, raw)
    assert fmt.startswith("⚠️") and "MICP fit not performed" in fmt
    assert app.get_tool_call_records(SID)[-1]["status"] == "error"
    assert tr.normalize(tr.REGISTRY["fit_petrophysical_curve"], raw, fmt, True).ok is False


@pytest.mark.parametrize("args, expect", [
    ({"model": "jfunction", "sw": [0.5], "pc": [10.0]}, "J-Function not computed"),
    ({"model": "pc_centrifuge", "sw": [0.5], "pc": [10.0]}, "Capillary pressure curve not computed"),
    ({"model": "poroperm", "porosity": [0.0, 0.0, 0.1], "perm": [1.0, 1.0, 1.0]}, "positive porosity/permeability pair"),
    ({"model": "poroperm_depth", "depth": [1.0], "porosity": [0.1, 0.2], "perm": [1.0, 2.0]}, "vs depth plot not computed"),
    ({"model": "overburden", "pressure": [5000.0], "porosity": [0.2, 0.19, 0.18], "perm": [10.0, 9.0, 8.0]},
     "cannot be synthesized"),
    ({"model": "overburden", "pressure": [], "porosity": [0.2], "perm": [10.0]}, "Overburden fit not performed"),
])
def test_every_analytic_guard_refuses_explicitly(args, expect):
    fmt = app.assistant._format_tool_response("fit_petrophysical_curve", dict(args),
                                              json.dumps({"status": "ready", "model": args["model"]}))
    assert fmt.startswith("⚠️") and expect in fmt, fmt
    assert "__PRC_PLOT__" not in fmt                            # no synthesized depth axis / curve


def test_ri_and_ff_short_cache_vectors_refuse_explicitly():
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE[SID] = {"ground_truth": "x", "labeled_values": {},
                                       "flat_vectors": {"water_saturation_sw": [0.9, 0.8, 0.7],
                                                        "resistivity_index_ri": [1.2, 1.6]},
                                       "raw_excel_data": {}}
    fmt = app.assistant._format_tool_response_impl("fit_petrophysical_curve", {"model": "ri"}, '{"status":"ready","model":"ri"}')
    assert fmt.startswith("⚠️") and "equal in length" in fmt


def test_micp_values_the_data_cannot_support_are_null_with_reasons():
    fmt = app.assistant._format_tool_response_impl("fit_petrophysical_curve",
                                                   {"model": "micp", "pc": [10.0, 20.0], "s_hg": [0.005, 0.008]},
                                                   '{"status":"ready","model":"micp"}')
    micp = json.loads(fmt.split("__PRC_PLOT__", 1)[1].split("__PRC_PLOT__")[0].strip())["metadata"]["micp"]
    assert micp["entry_pressure_psia"] is None and micp["threshold_pressure_psia"] is None
    assert micp["modal_pore_radius_um"] is None and micp["sorting_index"] is None
    assert len(micp["notes"]) == 3 and any("1% Hg" in n for n in micp["notes"])


def test_formatter_crash_is_a_refusal_not_an_empty_success(monkeypatch):
    class Broken:
        def validate_micp(self, *a, **k):
            raise RuntimeError("guard exploded (simulated)")
    monkeypatch.setattr(app, "PhysicsGuard", Broken)
    pc, shg = [5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 320.0], [0.02, 0.1, 0.3, 0.5, 0.6, 0.7, 0.75]
    fmt = app.assistant._format_tool_response("fit_petrophysical_curve", {"model": "micp", "pc": pc, "s_hg": shg},
                                              '{"status":"ready","model":"micp"}')
    assert fmt.startswith("⚠️") and "response formatting failed" in fmt and "guard exploded" in fmt
    assert app.get_tool_call_records(SID)[-1]["status"] == "error"


def test_rqi_binds_only_present_keys_and_only_after_the_table_renders():
    _seed_sheet({"porosity": [0.1], "perm": [1.0]})
    sample = {"sample": 1, "depth": 1.0, "phi_pct": 10.0, "perm_md": 5.0, "phi_z": 0.11, "fzi": 1.2, "hu": 1, "hu_quality": "Good"}
    raw = json.dumps({"status": "success", "input_source": "cache", "total_samples": 1, "samples": [sample],
                      "summary": [], "thresholds": {}})
    fmt = app.assistant._format_tool_response("calculate_petrophysics_properties", {"model": "rqi_fzi"}, raw)
    assert fmt.startswith("⚠️") and "KeyError" in fmt               # 'rqi' missing: the table cannot render
    with app.SESSION_DATA_CACHE_LOCK:
        labeled = dict(app.SESSION_DATA_CACHE[SID]["labeled_values"])
    assert "rqi_1" not in labeled and "fzi_1" not in labeled         # nothing bound, no 0.0 placeholder
    sample["rqi"] = 0.7
    raw = json.dumps({"status": "success", "input_source": "cache", "total_samples": 1, "samples": [sample],
                      "summary": [], "thresholds": {}})
    fmt = app.assistant._format_tool_response("calculate_petrophysics_properties", {"model": "rqi_fzi"}, raw)
    assert "RQI / FZI Calculation" in fmt
    with app.SESSION_DATA_CACHE_LOCK:
        labeled = dict(app.SESSION_DATA_CACHE[SID]["labeled_values"])
    assert labeled["rqi_1"] == 0.7 and labeled["fzi_1"] == 1.2 and labeled["hu_1"] == 1


def test_text_results_reach_the_user_and_the_audit_rows_reach_the_model():
    fmt = app.assistant._format_tool_response("generate_mermaid_diagram", {"type": "flow", "content": "graph TD; A-->B"},
                                              "__MERMAID_START__\ngraph TD; A-->B\n__MERMAID_END__")
    assert "__MERMAID_START__" in fmt and "graph TD; A-->B" in fmt
    assert app._log_physics_audit(SID, "micp", {"score": 77, "violations": [{"rule": "non-monotonic Pc"}]}, "w.xlsx")
    final = _run("get_audit_history", {})
    assert final[1] is True and "PRC AUDIT LEDGER" in final[2] and "non-monotonic Pc" in final[2]
    fmt = app.assistant._format_tool_response("get_audit_history", {}, final[2])
    assert "PRC AUDIT LEDGER" in fmt and "non-monotonic Pc" in fmt
    summary = app.assistant._tool_result_summary("get_audit_history", final[2], True)
    assert "non-monotonic Pc" in summary["ledger"]


def test_default_summary_hands_the_model_the_raw_payload():
    summary = app.assistant._tool_result_summary("calculate_petrophysics_properties", '{"sw_face": [0.31, 0.29]}', True)
    assert summary["status"] == "executed" and "sw_face" in summary["result"] and "0.31" in summary["result"]


def test_non_json_result_without_a_branch_is_not_rendered_silently():
    fmt = app.assistant._format_tool_response("calculate_petrophysics_properties", {"model": "x"}, "[1, 2, 3]")
    assert fmt.startswith("⚠️") and "not rendered" in fmt
    assert app.get_tool_call_records(SID)[-1]["status"] == "error"


# ── through the real loop on the scripted mock ───────────────────────────────

def test_guard_fall_through_reaches_the_model_as_a_failure_and_the_user_as_a_refusal():
    script = app.llm_adapter.MockScript.from_dict({
        "name": "d3-app2-fallthrough", "on_exhausted": "error",
        "steps": [
            {"assistant": {"text": "", "tool_calls": [{"name": "fit_petrophysical_curve",
                                                        "args": {"model": "jfunction", "sw": [0.5], "pc": [10.0]}}]}},
            {"assistant": {"text": "Done."}},
        ]})
    seed_session(SID)
    app.CHAT.load_script(script)
    try:
        reply = app.assistant.chat([], "Compute the Leverett J-function for sample D3-2.", stream=False, sid=SID, email=EMAIL)
    finally:
        app.CHAT.load_script(None)
    tool_msg = [m for m in script.transcript[1]["messages"] if m.get("role") == "tool"][0]["content"]
    assert "TOOL FAILURE" in tool_msg and "J-Function not computed" in tool_msg and "computed." not in tool_msg
    assert app.get_tool_call_records(SID)[-1]["status"] == "error"
    assert "⚠️ J-Function not computed" in reply


# ── repair round: model-args pm default, overburden remap, query-time vector outage ──

def test_klinkenberg_without_pm_refuses_instead_of_defaulting_14_7_psi(monkeypatch):
    """Model-args path: params carry ka but no pm. petrophysics.py would fill
    pm=14.7 and the table would print 'Mean Pressure (psi) 14.70' as measured."""
    seen = _capturing_run_skill(monkeypatch, json.dumps({"status": "success", "total_samples": 2,
                                                         "samples": [{"pm_psi": 14.7}]}))
    final = _run("calculate_petrophysics_properties",
                 {"script": "petrophysics.py", "model": "klinkenberg", "params": {"ka": [5.0, 6.0]}})
    assert final[1] is False, final
    assert "14.7" in json.loads(final[2])["error"] and "pm" in json.loads(final[2])["error"]
    assert seen == []                                            # the script never ran with the default


def test_overburden_non_series_pressure_refuses_instead_of_remapping_to_poroperm():
    args = {"model": "overburden", "pressure": [50.0], "porosity": [0.2, 0.19, 0.18], "perm": [10.0, 9.0, 8.0]}
    raw = json.dumps({"status": "ready", "model": "overburden"})
    fmt = app.assistant._format_tool_response("fit_petrophysical_curve", args, raw)
    assert fmt.startswith("⚠️") and "poroperm" in fmt and "__PRC_PLOT__" not in fmt, fmt
    assert args["model"] == "overburden"                         # the ledger row keeps the requested model
    row = app.get_tool_call_records(SID)[-1]
    assert row["status"] == "error" and row["args"]["model"] == "overburden"
    ok = tr.normalize(tr.REGISTRY["fit_petrophysical_curve"], raw, fmt, True).ok
    assert ok is False
    summary = app.assistant._tool_result_summary("fit_petrophysical_curve", raw, ok=ok)
    assert summary["status"] == "error" and "computed" not in json.dumps(summary)


def test_hybrid_query_time_vector_failure_is_reported_as_an_outage(monkeypatch):
    """Construction succeeds; the QUERY raises. geological_graph.hybrid_search
    swallows that (logs, returns vector=[]), which read as 'no vector matches'."""
    import rag_database

    class Flaky:
        def __init__(self, *a, **k):
            pass

        def query_analog_wells(self, **kw):
            raise RuntimeError("embedding model missing (simulated)")
    monkeypatch.setattr(rag_database, "RAGDatabase", Flaky)
    args = {"query_text": "Sirte basin analogs", "porous_low": 0.1, "porous_high": 0.2, "perm_low": 1, "perm_high": 50}
    final = _run("hybrid_geological_search", args)
    assert final[1] is True
    assert "embedding model missing" in json.loads(final[2]).get("vector_unavailable", "")
    fmt = app.assistant._format_tool_response("hybrid_geological_search", args, final[2])
    assert "vector search unavailable" in fmt and "no vector matches" not in fmt
    assert _degraded("vector-retriever"), app.degradations()
