"""Harness for the D2 regression corpus.

A scenario is a JSON fixture under tests/fixtures/scenarios/ (a `MockScript`:
the model's scripted turns). `run_scenario` installs it on the app's chat
adapter and drives the REAL chat loop — tool dispatch, the tool-call ledger,
the citation gate, provenance-token resolution, answer assembly — with no
network (the D0 egress guard is armed for every test run). Tool results are
produced by the real tools on a seeded session cache, exactly as after an
upload; the scenario only scripts what the model says.

Seeding follows the B0.1 protocol: one Sw/RI sheet whose true Archie n is
chosen per test (n < 1.5 makes the cache-path fit REFUSE; 1.5 <= n <= 3.0
makes it succeed and record the fitted value), plus wettability labeled values
for provenance tokens.
"""
from __future__ import annotations

import dataclasses
import pathlib
from typing import Dict, List, Optional

import app
import llm_adapter as la

FIXTURES = pathlib.Path(__file__).parent / "fixtures" / "scenarios"
EMAIL = "test@prc.local"          # chat() bypasses response_cache for this identity
SW = [1.0, 0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3]
WETTABILITY = {
    "Wettability.Amott_Water_Index_Iw": 0.68,
    "Wettability.Amott_Oil_Index_Io": 0.05,
    "Wettability.USBM_Area_A1": 3.2,
    "Wettability.USBM_Area_A2": 1.0,
}


def ri_series(n: float) -> List[float]:
    """RI = Sw^-n, so the cache-path Archie fit recovers exactly n."""
    return [round(s ** -n, 5) for s in SW]


def load_scenario(name: str) -> la.MockScript:
    return la.MockScript.from_file(FIXTURES / f"{name}.json")


_SEEDS = 0


def seed_session(sid: str, *, n: float = 1.85, labeled: Optional[Dict[str, float]] = None,
                 fname: Optional[str] = None) -> List[float]:
    """Populate the in-memory session cache the way an upload does.

    The file name carries a per-seed counter: chat() hashes the enriched
    prompt (which embeds this inventory) as its response-cache key, and a
    repeated identical run would otherwise spend the db() retry budget on a
    UNIQUE collision. Scripted output never depends on the name."""
    global _SEEDS
    _SEEDS += 1
    fname = fname or f"SCAL_Well-D2_D2-1_run{_SEEDS}.xlsx"
    ri = ri_series(n)
    ground_truth = (
        "MANDATORY GROUND TRUTH INVENTORY (Python-verified from binary file)\n"
        f"File: {fname}\n"
        "Sheets found: ['Archie_VariableSw', 'Wettability']\n\n"
        f"Sheet 'Archie_VariableSw' (shape {len(SW)}x2):\n"
        "  Columns: ['Water_Saturation_Sw', 'Resistivity_Index_RI']\n"
        f"  Water_Saturation_Sw: {SW}\n"
        f"  Resistivity_Index_RI: {ri}\n\n"
        "Sheet 'Wettability' (shape 1x4):\n"
        "  Columns: ['Amott_Water_Index_Iw', 'Amott_Oil_Index_Io', 'USBM_Area_A1', 'USBM_Area_A2']\n"
        "  Row 1: Amott_Water_Index_Iw = 0.68, Amott_Oil_Index_Io = 0.05, USBM_Area_A1 = 3.2, USBM_Area_A2 = 1.0\n"
    )
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE[sid] = {
            "ground_truth": ground_truth,
            "labeled_values": dict(WETTABILITY if labeled is None else labeled),
            "flat_vectors": {
                "Archie_VariableSw.Water_Saturation_Sw": list(SW),
                "water_saturation_sw": list(SW),
                "Archie_VariableSw.Resistivity_Index_RI": list(ri),
                "resistivity_index_ri": list(ri),
            },
        }
    app.reset_tool_call_ledger(sid)
    return ri


def clear_session(sid: str) -> None:
    with app.SESSION_DATA_CACHE_LOCK:
        app.SESSION_DATA_CACHE.pop(sid, None)
    app.reset_tool_call_ledger(sid)
    app._tls.current_session_id = None


@dataclasses.dataclass
class ScenarioRun:
    reply: str
    ledger: List[Dict[str, object]]
    transcript: List[Dict[str, object]]     # what the model was sent, per step
    script: la.MockScript

    def calls(self, tool: str) -> List[Dict[str, object]]:
        return [r for r in self.ledger if r["tool"] == tool]

    def tool_messages(self, step: int) -> List[Dict[str, object]]:
        """Tool-result messages the model saw at `step` (0-based)."""
        return [m for m in self.transcript[step]["messages"] if m.get("role") == "tool"]


def run_scenario(name: str, *, sid: str, question: str,
                 history: Optional[List[Dict[str, str]]] = None,
                 seed: bool = True, n: float = 1.85,
                 labeled: Optional[Dict[str, float]] = None,
                 adapter: Optional[la.ChatAdapter] = None,
                 email: Optional[str] = EMAIL) -> ScenarioRun:
    """Play `name` through the real chat loop for session `sid`."""
    script = load_scenario(name)
    ad = adapter or app.CHAT
    ad.load_script(script)
    try:
        if seed:
            seed_session(sid, n=n, labeled=labeled)
        reply = app.assistant.chat(list(history or []), question, stream=False,
                                   sid=sid, email=email)
    finally:
        ad.load_script(None)
    return ScenarioRun(reply=reply, ledger=app.get_tool_call_records(sid),
                       transcript=list(script.transcript), script=script)
