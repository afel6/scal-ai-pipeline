"""Unit tests for llm_json_utils — the JSON-robustness layer of the
report/extraction pipeline (NVIDIA NIM gpt-oss-120b habitually wraps JSON in
```json fences or surrounds it with prose). Pure stdlib, fully offline."""

import pytest

from llm_json_utils import (
    LLMJsonParseError,
    CORRECTIVE_JSON_PROMPT,
    strip_code_fences,
    parse_llm_json,
    llm_json_with_retry,
)


# ── strip_code_fences ────────────────────────────────────────────────────────

def test_strip_fences_plain_text_passthrough():
    assert strip_code_fences('{"a": 1}') == '{"a": 1}'


def test_strip_fences_json_fence():
    raw = '```json\n{"a": 1}\n```'
    assert strip_code_fences(raw) == '{"a": 1}'


def test_strip_fences_bare_fence():
    raw = '```\n[1, 2, 3]\n```'
    assert strip_code_fences(raw) == '[1, 2, 3]'


def test_strip_fences_with_surrounding_prose():
    raw = 'Here is the extraction:\n```json\n{"a": 1}\n```\nLet me know if you need more.'
    assert strip_code_fences(raw) == '{"a": 1}'


# ── parse_llm_json ───────────────────────────────────────────────────────────

def test_parse_clean_object():
    assert parse_llm_json('{"Swi": 0.22, "Sor": 0.25}') == {"Swi": 0.22, "Sor": 0.25}


def test_parse_clean_array():
    assert parse_llm_json('[{"Pressure_psi": 500}]') == [{"Pressure_psi": 500}]


def test_parse_fenced_json():
    raw = '```json\n{"well_name": "C-137", "Sw_i": 0.18}\n```'
    assert parse_llm_json(raw) == {"well_name": "C-137", "Sw_i": 0.18}


def test_parse_fenced_json_with_prose():
    raw = (
        "Sure! Based on the analysis, here is the requested JSON:\n\n"
        '```json\n{"data_type": "MICP", "sample_count": 5}\n```\n\n'
        "The extraction honoured all protocols."
    )
    assert parse_llm_json(raw) == {"data_type": "MICP", "sample_count": 5}


def test_parse_prose_wrapped_json_no_fences():
    raw = 'The result is {"m_cementation": 2.1, "n_saturation": 1.9} as computed.'
    assert parse_llm_json(raw) == {"m_cementation": 2.1, "n_saturation": 1.9}


def test_parse_prose_wrapped_array():
    raw = "Extracted rows follow: [\n{\"Porosity_percent\": 14.2}\n] end of data."
    assert parse_llm_json(raw) == [{"Porosity_percent": 14.2}]


def test_parse_skips_non_json_braces():
    raw = 'Note {this is not json} but {"valid": true} is.'
    assert parse_llm_json(raw) == {"valid": True}


def test_parse_nested_object_survives():
    raw = '```json\n{"extracted_data": [{"a": 1}], "protocol_1": {"sheets": ["S1"]}}\n```'
    parsed = parse_llm_json(raw)
    assert parsed["extracted_data"] == [{"a": 1}]
    assert parsed["protocol_1"]["sheets"] == ["S1"]


def test_parse_invalid_raises():
    with pytest.raises(LLMJsonParseError):
        parse_llm_json("I could not produce the JSON you asked for, sorry.")


def test_parse_empty_raises():
    with pytest.raises(LLMJsonParseError):
        parse_llm_json("")
    with pytest.raises(LLMJsonParseError):
        parse_llm_json(None)


# ── llm_json_with_retry ──────────────────────────────────────────────────────

def test_retry_not_triggered_on_first_success():
    calls = []

    def gen(corrective):
        calls.append(corrective)
        return '{"ok": 1}'

    assert llm_json_with_retry(gen) == {"ok": 1}
    assert calls == [None]  # exactly one call, no corrective prompt


def test_retry_recovers_after_bad_first_reply():
    calls = []

    def gen(corrective):
        calls.append(corrective)
        if corrective is None:
            return "Sorry, here is prose with no JSON at all."
        return '```json\n{"recovered": true}\n```'

    assert llm_json_with_retry(gen) == {"recovered": True}
    assert len(calls) == 2
    assert calls[1] == CORRECTIVE_JSON_PROMPT  # corrective prompt passed on retry


def test_retry_fails_after_two_bad_replies():
    calls = []

    def gen(corrective):
        calls.append(corrective)
        return "still not json"

    with pytest.raises(LLMJsonParseError):
        llm_json_with_retry(gen)
    assert len(calls) == 2  # exactly ONE corrective retry, no infinite loop
