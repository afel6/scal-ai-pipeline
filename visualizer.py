"""Visualization layer for the PRC SCAL AI Pipeline.

Separation of concerns is the whole point of this module:

* :func:`extract_curve_coordinates` is the **pure** core. It turns validated SCAL
  JSON into clean, serialisable ``{"x", "y", "labels", ...}`` coordinate payloads
  and touches no plotting library. This is what the API, the document engines,
  and the frontend should consume — they render from coordinates, never from
  binary images baked deep inside the processing code.
* :func:`render_coordinate_payloads` is the **thin** rendering wrapper. It takes
  those payloads and writes PNGs with Matplotlib's thread-safe object-oriented
  API. Nothing upstream depends on it.
* :func:`generate_plots` preserves the historical entry point (used by
  ``app.py``) by composing the two: extract coordinates, then render.

All diagnostics go through the project logger; ``print`` is never used.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Optional

import matplotlib
# Non-interactive Agg backend: no GUI window, no thread blocking on the server.
matplotlib.use("Agg")
from matplotlib.figure import Figure

_logger = logging.getLogger("prc-visualizer")


# ── PURE COORDINATE GENERATION (no rendering) ──────────────────────────────────

def extract_curve_coordinates(json_data: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert validated SCAL rows into decoupled plot-coordinate payloads.

    Two standard overburden curves are produced when their data is present:

    1. Porosity (%) vs. Overburden Pressure (psi)
    2. Air Permeability (mD) vs. Overburden Pressure (psi)

    Each payload is a plain JSON-serialisable dict::

        {
          "title":   "Porosity vs. Overburden Pressure",
          "x_label": "Overburden Pressure (psi)",
          "y_label": "Porosity (%)",
          "x":       [800.0, 1200.0, ...],
          "y":       [18.5, 18.2, ...],
          "labels":  ["Porosity"],
        }

    Only paired, non-null points are emitted, and points are sorted ascending by
    pressure. Curves with no valid data are omitted entirely (callers can detect
    this by the absence of that title).
    """
    pressures: List[Optional[float]] = []
    porosities: List[Optional[float]] = []
    perms: List[Optional[float]] = []

    for row in json_data:
        pressure = row.get("Pressure_psi")
        if pressure is None:
            continue  # pressure is the shared x-axis; rows without it are unusable
        pressures.append(pressure)
        porosities.append(row.get("Porosity_percent"))
        perms.append(row.get("Air_Permeability_md"))

    payloads: List[Dict[str, Any]] = []

    porosity_pts = _paired_sorted(pressures, porosities)
    if porosity_pts:
        x, y = porosity_pts
        payloads.append({
            "title": "Porosity vs. Overburden Pressure",
            "x_label": "Overburden Pressure (psi)",
            "y_label": "Porosity (%)",
            "x": x, "y": y, "labels": ["Porosity"],
        })
    else:
        _logger.warning("No valid Porosity vs Pressure points to plot.")

    perm_pts = _paired_sorted(pressures, perms)
    if perm_pts:
        x, y = perm_pts
        payloads.append({
            "title": "Air Permeability vs. Overburden Pressure",
            "x_label": "Overburden Pressure (psi)",
            "y_label": "Air Permeability (mD)",
            "x": x, "y": y, "labels": ["Air Permeability"],
        })
    else:
        _logger.warning("No valid Air Permeability vs Pressure points to plot.")

    return payloads


def _paired_sorted(xs: List[Any], ys: List[Any]):
    """Return ``(x_sorted, y_sorted)`` for non-null pairs, sorted by x; else None."""
    pairs = [(x, y) for x, y in zip(xs, ys) if x is not None and y is not None]
    if not pairs:
        return None
    pairs.sort(key=lambda pt: pt[0])
    return [float(x) for x, _ in pairs], [float(y) for _, y in pairs]


# ── THIN RENDERING WRAPPER ─────────────────────────────────────────────────────

# Per-curve styling keyed by series label — keeps the renderer declarative.
_CURVE_STYLE = {
    "Porosity": {"color": "#0F4C81", "marker": "o"},
    "Air Permeability": {"color": "#10B981", "marker": "s"},
}
_FILENAME_BY_TITLE = {
    "Porosity vs. Overburden Pressure": "porosity_vs_pressure.png",
    "Air Permeability vs. Overburden Pressure": "permeability_vs_pressure.png",
}


def render_coordinate_payloads(
    payloads: List[Dict[str, Any]], output_dir: str
) -> List[str]:
    """Render coordinate payloads to PNG files; return the written paths.

    Pure presentation: it consumes the dicts from :func:`extract_curve_coordinates`
    and never re-derives data. Filenames are stable so downstream consumers can
    locate them deterministically.
    """
    written: List[str] = []
    for payload in payloads:
        title = payload["title"]
        label = payload["labels"][0]
        style = _CURVE_STYLE.get(label, {"color": "#0F4C81", "marker": "o"})

        fig = Figure(figsize=(8, 5))
        ax = fig.subplots()
        ax.plot(payload["x"], payload["y"], marker=style["marker"], linestyle="-",
                color=style["color"], linewidth=2, markersize=6, label=label)
        ax.set_title(title, fontsize=12, fontweight="bold", pad=15)
        ax.set_xlabel(payload["x_label"], fontsize=10, fontweight="bold")
        ax.set_ylabel(payload["y_label"], fontsize=10, fontweight="bold")
        ax.grid(True, linestyle="--", alpha=0.6)
        ax.legend(loc="best")

        filename = _FILENAME_BY_TITLE.get(title, _slugify(title) + ".png")
        path = os.path.join(output_dir, filename)
        fig.savefig(path, dpi=300, bbox_inches="tight")
        fig.clf()
        written.append(path)
        _logger.info("Rendered plot: %s", path)
    return written


def _slugify(text: str) -> str:
    """Lowercase, filesystem-safe slug for an arbitrary chart title."""
    return "".join(c if c.isalnum() else "_" for c in text.lower()).strip("_")


# ── HISTORICAL COMPOSITE ENTRY POINT ───────────────────────────────────────────

def generate_plots(
    json_data: List[Dict[str, Any]],
    output_dir: Optional[str] = None,
    streamlit_code: Optional[str] = None,
) -> str:
    """Extract coordinates, render the standard PNGs, and export validated JSON.

    Backwards-compatible wrapper retained for ``app.py``: it now composes the
    pure coordinate generator with the thin renderer rather than interleaving
    data extraction and plotting. Returns the output directory.
    """
    if not output_dir:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        output_dir = os.path.join(base_dir, "outputs")
    os.makedirs(output_dir, exist_ok=True)

    if streamlit_code:
        dashboard_path = os.path.join(output_dir, "app_dashboard.py")
        with open(dashboard_path, "w", encoding="utf-8") as fh:
            fh.write(streamlit_code)
        _logger.info("Saved Streamlit dashboard: %s", dashboard_path)

    payloads = extract_curve_coordinates(json_data)
    render_coordinate_payloads(payloads, output_dir)

    json_path = os.path.join(output_dir, "validated_scal_data.json")
    with open(json_path, "w", encoding="utf-8") as fh:
        json.dump(json_data, fh, indent=2)
    _logger.info("Exported validated data JSON: %s", json_path)

    return output_dir
