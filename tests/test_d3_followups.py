"""D3.1 follow-ups: the rows the batch fixers deferred across a batch boundary,
closed here with the same rule - force the failure, assert the CALLER sees it."""
import json

import pandas as pd
import pytest

import app
import llm_adapter as la
import prc_physics
from extractors.micp import MICPExtractor


# prc_physics.calculate_washburn_radius: Pc <= 0 has no pore radius. The old code
# substituted 1e-9 psia and returned a ~10^12 micron "radius" as a float.
def test_washburn_zero_pressure_is_a_refusal_not_a_giant_radius():
    with pytest.raises(ValueError, match="positive"):
        prc_physics.calculate_washburn_radius(0.0)


# extractors/micp.py called the radius per row unguarded: a Pc = 0 first row
# either crashed the whole extraction (after the fix above) or carried the giant
# radius into the curve (before it). The row is left out and the omission is on
# the extracted curve where the caller reads it.
def test_micp_extractor_leaves_out_a_zero_pressure_row_and_says_so():
    df = pd.DataFrame([["Pressure (psia)", "Hg Saturation (PV)"],
                       [0.0, 0.0], [10.0, 0.05], [20.0, 0.10], [50.0, 0.20], [100.0, 0.30], [200.0, 0.40]])
    out = MICPExtractor({"MICP_TestA": df}).extract()
    curves = [d for d in _walk(out) if isinstance(d, dict) and isinstance(d.get("pressure"), list) and d["pressure"]]
    assert curves, out
    for c in curves:
        assert 0.0 not in c["pressure"] and 10.0 in c["pressure"]
        assert all(r > 0 for r in c["calculated_pore_radius_microns"])
    notes = [d["rows_left_out"] for d in _walk(out) if isinstance(d, dict) and d.get("rows_left_out")]
    assert notes and any("Pc <= 0" in str(n) for n in notes), out


def _walk(obj):
    yield obj
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _walk(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _walk(v)


# app.py graph context: hybrid_search returns {"graph": {"matched_nodes", "subgraphs"}, "vector": [...]}
# and the chat path iterated the DICT - injecting the strings '"matched_nodes"' and
# '"subgraphs"' as knowledge-base context instead of the subgraphs.
def test_graph_context_chunks_are_subgraphs_not_dict_keys():
    res = {"graph": {"matched_nodes": [{"id": "CE03-41"}],
                     "subgraphs": [{"nodes": ["CE03-41"], "edges": [["CE03-41", "analog", "C228"]]},
                                   {"nodes": ["lonely"], "edges": []}]},
           "vector": [{"id": 1, "text": "analog well report"}]}
    chunks = app._graph_context_chunks(res)
    assert chunks == [json.dumps(res["graph"]["subgraphs"][0]), json.dumps(res["vector"][0])]
    assert not any(c.strip('"') in ("matched_nodes", "subgraphs") for c in chunks)
    assert app._graph_context_chunks({}) == [] and app._graph_context_chunks({"graph": None}) == []


# llm_adapter.stream(): a scripted (or real) turn that requests a tool has no place
# in a text-only stream; the mock dropped the tool calls and yielded the text.
def test_stream_refuses_a_tool_bearing_turn_instead_of_dropping_the_calls():
    script = la.MockScript.from_dict({"name": "stream-tool", "steps": [
        {"assistant": {"text": "calling", "tool_calls": [{"name": "fit_petrophysical_curve", "args": {"model": "ri"}}]}}]})
    app.CHAT.load_script(script)
    try:
        with pytest.raises(la.ChatAdapterError, match="fit_petrophysical_curve"):
            list(app.CHAT.stream([{"role": "user", "content": "fit it"}]))
    finally:
        app.CHAT.load_script(None)
