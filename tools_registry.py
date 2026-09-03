"""One declarative tool registry and one tool contract (D3.2).

Tool identity — name, model-facing schema, argument validation, error shape,
owning agent — lives HERE and nowhere else. `app.py` derives the model-facing
declaration list from `schemas()`, dispatches and renders by these names, and
turns every raw result into a `ToolResult` through `normalize()`:

    ok       True only when the tool actually succeeded (a "⚠" refusal, a
             status:"error" payload or a dispatch failure is ok=False)
    values   {name: {"value": number, "source": "<how it was obtained>"}} —
             no tool returns a bare number; a value without a source is the
             pattern this project exists to eliminate
    error    the failure detail when ok is False (never a fabricated result)
    text     the rendered result for the user (empty when the tool failed)

Sources name the provenance of the NUMBER, not the tool that printed it:
    fitted:cache        regression on the verified cached column vectors
    fitted:model-args   regression on arrays the model supplied
    computed:model-args analytics on parameters the model supplied
    simulated:model-args
    retrieved:vector-store
    ledger:physics-audit
Only `fitted:cache` is evidence the citation gate accepts for a fitted
parameter (app._CACHE_BACKED_FITTERS); the other sources are visible to the
model and the ledger so a number can always say where it came from.

D8's agent manifest reads this registry; build changes here, not in the loop.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional, Tuple

OWNER = "hviel"
_PLOT_BLOCK_RE = re.compile(r"__PRC_PLOT__\s*\{.*?\}\s*(?=\n|$)", re.DOTALL)
_GATED_PARAMS = ("n", "m", "a", "nw", "no")


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: Dict[str, Any]          # model-facing JSON schema (Gemini-style uppercase types)
    owner: str = OWNER
    numeric: bool = False               # returns numbers → values must carry a source
    values_from: str = "none"           # plot_metadata | json:samples | json:optimal_parameters | simulation:params | json:vector | json:audits | none
    source_kind: str = ""               # provenance label for the numbers this tool returns
    error_shape: str = "json-status"    # json-status: {"status":"error","error":…} | warning-prefix: rendered "⚠ …"

    @property
    def required(self) -> Tuple[str, ...]:
        return tuple(self.parameters.get("required") or ())


@dataclass
class ToolResult:
    ok: bool
    values: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    error: Optional[str] = None
    text: str = ""
    raw: Any = None


# --- the registry ----------------------------------------------------------------------

_SPECS: List[ToolSpec] = [
    ToolSpec(
        name="calculate_petrophysics_properties",
        description="**MANDATORY for centrifuge Hassler-Brunner / Forbes corrections and for FZI/RQI calculations. Do not produce Pc(Sw) or RQI values without calling this tool first.** Calculation Engine for SCAL Tracks A, B, D, E. Does NOT generate charts, only returns calculated JSON data.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "script": {"type": "STRING", "description": "One of: petrophysics.py, micp_skill.py, centrifuge_skill.py"},
                "model": {"type": "STRING", "description": "For petrophysics.py: regress_archie_m_a, regress_archie_n, rqi_fzi. For centrifuge: pc_only, full, hassler_brunner. rqi_fzi params: {phi: [fractions 0-1], perm: [mD], depth: [optional array]}. Returns full per-sample table with HU classification."},
                "params": {"type": "OBJECT", "description": "Parameters required for the selected script and model."},
            },
            "required": ["script", "params"],
        },
        numeric=True, values_from="json:samples", source_kind="computed:model-args", error_shape="json-status",
    ),
    ToolSpec(
        name="execute_python_simulation",
        description="Universal petrophysical simulation (Brooks-Corey, 1D Kr curves, 2D IMPES reservoir waterflood). Returns JSON for PRC plotting.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "model": {"type": "STRING"},
                "mode": {"type": "STRING"},
                "params": {
                    "type": "OBJECT",
                    "properties": {
                        "swr": {"type": "NUMBER"}, "snr": {"type": "NUMBER"},
                        "krw_max": {"type": "NUMBER"}, "kro_max": {"type": "NUMBER"},
                        "nw": {"type": "NUMBER"}, "no": {"type": "NUMBER"},
                        "nx": {"type": "NUMBER"}, "ny": {"type": "NUMBER"},
                        "steps": {"type": "NUMBER"},
                    },
                },
            },
            "required": ["model", "mode", "params"],
        },
        numeric=True, values_from="simulation:params", source_kind="simulated:model-args", error_shape="json-status",
    ),
    ToolSpec(
        name="generate_mermaid_diagram",
        description="Generates Mermaid.js diagram code for complex workflows.",
        parameters={"type": "OBJECT", "properties": {"type": {"type": "STRING"}, "content": {"type": "STRING"}},
                    "required": ["type", "content"]},
        numeric=False, values_from="none", error_shape="warning-prefix",
    ),
    ToolSpec(
        name="fit_petrophysical_curve",
        description=(
            "**MANDATORY before reporting any fitted parameter (Archie n, m, a, MICP Pe/Pd/modal radius, Corey exponents, J-function values). Never report these values without calling this tool first. If the tool fails, report the failure  -  do not estimate.** "
            "Fits raw SCAL lab data to standard petrophysical models. Select model by curve type:\n"
            "  model='brooks_corey' or 'let'  ->  Relative Permeability (pass sw, krw, kro arrays).\n"
            "  model='micp'  ->  Mercury Injection (pass pc=[psia], s_hg=[fraction 0-1]). "
            "For imbibition (recovery) cycle: also pass pc_imb=[psia], s_hg_imb=[fraction]. "
            "Auto-generates log-scale Pc curve (drainage solid, imbibition dashed) + PSD.\n"
            "  model='ri'  ->  Resistivity Index Archie fit (pass sw=[...], ri=[...]). Log-log plot, fits n exponent.\n"
            "  model='ff'  ->  Formation Factor Archie fit (pass porosity=[...], ff=[...]). Log-log plot, fits m and a.\n"
            "  model='jfunction'  ->  Leverett J-Function (pass sw=[...], pc=[psia], k_md=X, phi_val=Y, ift_cos_theta=26.5).\n"
            "  model='pc_centrifuge'  ->  Capillary Pressure direct (pass sw=[...], pc=[psia values]).\n"
            "  model='overburden'  ->  Compaction curves (pass pressure=[psia], porosity=[...], perm=[mD]). Dual-axis.\n"
            "  model='poroperm'  ->  Porosity vs Permeability cross-plot with log-linear fit (pass porosity=[...], perm=[mD]).\n"
            "  model='poroperm_depth'  ->  Porosity & Permeability vs Depth (pass depth=[...], porosity=[...], perm=[mD]). Dual-axis.\n"
            "Pass sample_name='Core-1' to label multi-sample charts."
        ),
        parameters={
            "type": "OBJECT",
            "properties": {
                "model": {"type": "STRING"},
                "sw": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "krw": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "kro": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "pc": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "s_hg": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "pc_imb": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "s_hg_imb": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "ri": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "ff": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "porosity": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "perm": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "pressure": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "depth": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "k_md": {"type": "NUMBER"},
                "phi_val": {"type": "NUMBER"},
                "ift_cos_theta": {"type": "NUMBER"},
                "sample_name": {"type": "STRING"},
            },
            "required": ["model"],
        },
        numeric=True, values_from="plot_metadata", source_kind="fitted:cache", error_shape="warning-prefix",
    ),
    ToolSpec(
        name="agentic_history_matching",
        description="Simulated Annealing history matching on SCAL lab data.",
        parameters={"type": "OBJECT", "properties": {"sw": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                                                     "krw": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                                                     "kro": {"type": "ARRAY", "items": {"type": "NUMBER"}}},
                    "required": ["sw", "krw", "kro"]},
        numeric=True, values_from="json:optimal_parameters", source_kind="fitted:model-args", error_shape="json-status",
    ),
    ToolSpec(
        name="generate_executive_report",
        description=(
            "**REFUSE this call if no SCAL analysis tools have been invoked in the current session. A report cannot be generated when no analysis has been performed. Return an error message asking the user to upload data and run analysis first.** "
            "Generates a professional PRC Executive SCAL Report (.docx) for the current "
            "engineering session. Call this when the user asks for a report, summary "
            "document, or engineering deliverable. Pass the well name extracted from the "
            "conversation context."
        ),
        parameters={"type": "OBJECT", "properties": {"well_name": {"type": "STRING"}, "report_title": {"type": "STRING"}},
                    "required": ["well_name"]},
        numeric=False, values_from="none", error_shape="warning-prefix",
    ),
    ToolSpec(
        name="get_audit_history",
        description="Retrieves the historical record of physics audits (the Auditor's Ledger) for the current session.",
        parameters={"type": "OBJECT", "properties": {}},
        numeric=True, values_from="json:audits", source_kind="ledger:physics-audit", error_shape="json-status",
    ),
    ToolSpec(
        name="sandbox_fit_brooks_corey",
        description="Fits Brooks-Corey relative permeability curves (exponent nw and no) to Sw, Krw, Kro data in a secure physics sandbox. Automatically enforces physical constraints and corrects anomalies.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "sw": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "krw": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "kro": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "swi": {"type": "NUMBER"}, "sor": {"type": "NUMBER"},
                "krw_max": {"type": "NUMBER"}, "kro_max": {"type": "NUMBER"},
                "sample_name": {"type": "STRING"},
            },
            "required": ["sw", "krw", "kro", "swi", "sor"],
        },
        numeric=True, values_from="plot_metadata", source_kind="fitted:model-args", error_shape="warning-prefix",
    ),
    ToolSpec(
        name="sandbox_fit_archie",
        description="Fits Archie parameters (a, m or b, n) securely in a sandbox. model_type='FF' fits a/m from porosity vs formation factor. model_type='RI' fits b/n from Sw vs resistivity index.",
        parameters={"type": "OBJECT", "properties": {"x": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                                                     "y": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                                                     "model_type": {"type": "STRING"}, "sample_name": {"type": "STRING"}},
                    "required": ["x", "y", "model_type"]},
        numeric=True, values_from="plot_metadata", source_kind="fitted:model-args", error_shape="warning-prefix",
    ),
    ToolSpec(
        name="hybrid_geological_search",
        description="Hybrid geological knowledge search: fuses the SQLite Geological Knowledge Graph (Libyan basins, formations, lithologies, fluids, wells, and the lab samples extracted from uploaded SCAL files, linked Well -[HAS_SAMPLE]-> Sample) with vector analog-well retrieval. Mention basin/formation/well names in query_text to anchor the graph traversal (a well anchors its linked samples too); pass porosity (porous_low/porous_high, fraction) and permeability (perm_low/perm_high, mD) windows to fetch analog wells from the vector store.",
        parameters={
            "type": "OBJECT",
            "properties": {
                "query_text": {"type": "STRING"},
                "porous_low": {"type": "NUMBER"}, "porous_high": {"type": "NUMBER"},
                "perm_low": {"type": "NUMBER"}, "perm_high": {"type": "NUMBER"},
                "depth_limit": {"type": "INTEGER"}, "n_results": {"type": "INTEGER"},
            },
            "required": ["query_text"],
        },
        numeric=True, values_from="json:vector", source_kind="retrieved:vector-store", error_shape="json-status",
    ),
]

REGISTRY: Dict[str, ToolSpec] = {s.name: s for s in _SPECS}


def schemas() -> List[Dict[str, Any]]:
    """The model-facing declaration list, in registry order (the shape app.py expects)."""
    return [{"function_declarations": [
        {"name": s.name, "description": s.description, "parameters": s.parameters} for s in _SPECS]}]


def validate_args(spec: ToolSpec, args: Mapping[str, Any]) -> List[str]:
    problems = [f"missing required argument: {k}" for k in spec.required if k not in args]
    known = set(spec.parameters.get("properties") or {})
    problems += [f"unknown argument: {k}" for k in args if k not in known]
    return problems


# --- the contract ------------------------------------------------------------------------

def tool_result_error(result: Any) -> Optional[str]:
    """The failure detail a raw tool payload encodes, or None for success.
    Plain text and plot payloads are success."""
    if result is None or (isinstance(result, str) and not result.strip()):
        return "tool returned no result"
    if isinstance(result, str):
        if result.startswith("Unknown tool:"):
            return result
        stripped = result.lstrip()
        if stripped.startswith("ERROR:") or stripped.startswith("Traceback (most recent call last):"):
            return stripped[:500]
        try:
            payload = json.loads(result)
        except Exception:                                   # noqa: BLE001 — not JSON: plain text / plot
            return None
    else:
        payload = result
    if isinstance(payload, dict):
        if payload.get("status") == "error":
            return str(payload.get("error") or payload)[:500]
        if payload.get("error") and "status" not in payload:
            return str(payload["error"])[:500]
    return None


def _is_num(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _json(raw: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    try:
        return json.loads(raw)
    except Exception:                                       # noqa: BLE001
        return None


def _values(spec: ToolSpec, raw: Any, rendered: str) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}

    def put(key: str, value: Any) -> None:
        if _is_num(value):
            out[key] = {"value": float(value), "source": spec.source_kind}

    kind = spec.values_from
    if kind == "plot_metadata":
        for m in _PLOT_BLOCK_RE.finditer(rendered or ""):
            try:
                meta = json.loads(m.group(0).split("__PRC_PLOT__", 1)[1].strip()).get("metadata") or {}
            except Exception:                               # noqa: BLE001 — not a payload
                continue
            archie = meta.get("archie") or {}
            if isinstance(archie, dict) and archie.get("fitted") is not False:
                for k in _GATED_PARAMS:
                    put(k, archie.get(k))
            fp = meta.get("fit_params") or {}
            if isinstance(fp, dict):
                for k in ("nw", "no"):
                    put(k, fp.get(k))
    elif kind == "json:samples":
        data = _json(raw)
        samples = (data or {}).get("samples") if isinstance(data, dict) else None
        items = samples.items() if isinstance(samples, dict) else \
            [(str(s.get("name", i)), s) for i, s in enumerate(samples or []) if isinstance(s, dict)]
        for name, s in items:
            if isinstance(s, dict):
                for k, v in s.items():
                    put(f"{name}.{k}", v)
    elif kind == "json:optimal_parameters":
        data = _json(raw)
        for k, v in ((data or {}).get("optimal_parameters") or {}).items() if isinstance(data, dict) else []:
            put(k, v)
    elif kind == "simulation:params":
        text = raw if isinstance(raw, str) else json.dumps(raw)
        if "__SIMULATION_START__" in text:
            try:
                data = json.loads(text.split("__SIMULATION_START__")[1].split("__SIMULATION_END__")[0].strip())
            except Exception:                               # noqa: BLE001
                data = {}
            params = data.get("params") or {}
            for k, v in params.items():
                put(k, v)
            # app._execute_tool fills simulation_core's silent defaults and lists
            # them; such a number was never supplied, and its source says so.
            for k in params.get("defaulted") or []:
                if k in out:
                    out[k]["source"] = "defaulted:simulation-core"
    elif kind == "json:vector":
        data = _json(raw)
        for item in (data or {}).get("vector") or [] if isinstance(data, dict) else []:
            if isinstance(item, dict):
                for k, v in (item.get("historical_data") or {}).items():
                    put(f"{item.get('id', '?')}.{k}", v)
    elif kind == "json:audits":
        data = _json(raw)
        audits = data.get("audits") if isinstance(data, dict) else data
        for i, a in enumerate(audits or []):
            if isinstance(a, dict):
                for k, v in a.items():
                    put(f"audit[{i}].{k}", v)
    return out


def normalize(spec: ToolSpec, raw: Any, rendered: str, dispatch_ok: bool) -> ToolResult:
    """Every tool result reaching the loop passes through here.

    ok is derived from the OUTCOME: a dispatch failure, a status:"error"
    payload, or a rendered "⚠" refusal (the analytic fits run inside the
    renderer) all make ok False with the detail in `error`. Values are
    extracted only from successful results and always carry a source.
    """
    error: Optional[str] = None
    rendered_text = rendered if isinstance(rendered, str) else ""
    if not dispatch_ok:
        error = tool_result_error(raw) or "tool failed"
    elif rendered_text.lstrip().startswith("⚠"):
        error = rendered_text.strip().lstrip("⚠️ ").strip()[:500]
    else:
        error = tool_result_error(raw)
    if error is not None:
        return ToolResult(ok=False, values={}, error=error, text="", raw=raw)
    return ToolResult(ok=True, values=_values(spec, raw, rendered_text), error=None, text=rendered_text, raw=raw)
