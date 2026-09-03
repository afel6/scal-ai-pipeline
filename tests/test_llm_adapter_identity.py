"""The two repos carry a byte-identical copy of the single chat adapter.
This guard fails the moment the copies drift. It is skipped only when the
sibling checkout is not present (CI runs one repo at a time)."""
import hashlib
import pathlib

import pytest

HERE = pathlib.Path(__file__).resolve().parents[1] / "llm_adapter.py"
SIBLING = HERE.parents[1] / "pvt-ai-pipeline" / "src" / "utils" / "llm_adapter.py"


def test_adapter_copies_are_byte_identical():
    if not SIBLING.exists():
        pytest.skip("sibling pvt-ai-pipeline checkout not present")
    a = hashlib.sha256(HERE.read_bytes()).hexdigest()
    b = hashlib.sha256(SIBLING.read_bytes()).hexdigest()
    assert a == b, "llm_adapter.py drifted between scal-ai-pipeline and pvt-ai-pipeline"


def test_scripted_mock_behaves_identically_in_both_copies():
    """D2.1 — the drift guard covers the mock: the same scenario fixture played
    through the scal copy and the pvt copy yields the same turns, tool calls,
    failures and transcript."""
    if not SIBLING.exists():
        pytest.skip("sibling pvt-ai-pipeline checkout not present")
    import importlib.util
    import llm_adapter as scal_copy
    import sys
    spec = importlib.util.spec_from_file_location("pvt_llm_adapter_copy", SIBLING)
    pvt_copy = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = pvt_copy               # dataclasses resolve the module by name
    spec.loader.exec_module(pvt_copy)

    fixture = HERE.parent / "tests" / "fixtures" / "scenarios" / "fabricated_value_after_failed_fit.json"
    msgs = [{"role": "user", "content": "report n"}]
    tools = [{"type": "function", "function": {"name": "fit_petrophysical_curve"}}]

    def play(mod):
        ad = mod.ChatAdapter(mod.load_config({}), opener=lambda *a, **k: (_ for _ in ()).throw(AssertionError("no network")))
        ad.load_script(mod.MockScript.from_file(fixture))
        out = []
        for _ in range(3):                                   # 2 scripted steps, then exhaustion
            try:
                r = ad.complete(msgs, tools=tools)
                out.append(("ok", r.text, [(c.name, c.args) for c in r.tool_calls], r.model))
            except mod.ChatAdapterError as exc:
                out.append(("error", str(exc)))
        return out, ad.script.transcript

    assert play(scal_copy) == play(pvt_copy)
