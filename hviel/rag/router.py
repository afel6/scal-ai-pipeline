"""Dual-RAG query router for the PRC AI Hub.

Classifies a chat query into the retrieval strategy the Hviel pipeline should
use before context assembly:

- VECTOR_SEARCH : exact numeric / snippet lookups → KnowledgeBase embedding
                  search (app.py `KnowledgeBase.search`).
- GRAPH_SEARCH  : entity-relationship / formation- and well-level questions →
                  geological graph traversal (geological_graph.hybrid_search).
- HYBRID        : both signal families fire → combined global (graph) + local
                  (vector) retrieval.

Deterministic and lexical by design: the router runs on every turn, needs no
API key, and must be testable offline (Layer 0). NOTE: `src/` is a namespace
package (no __init__.py) — the sister pvt-ai-pipeline checkout shares the
`src` root in the hub layout, and a regular package here would shadow it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from typing import List


class RagRoute(str, Enum):
    VECTOR_SEARCH = "VECTOR_SEARCH"
    GRAPH_SEARCH = "GRAPH_SEARCH"
    HYBRID = "HYBRID"


# Entity-relationship / cross-well signals → the geological graph.
_GRAPH_SIGNALS = [
    r"\banalog(?:ue)?s?\b",
    r"\bsimilar wells?\b",
    r"\boffset wells?\b",
    r"\brelated\b",
    r"\brelationships?\b",
    r"\bcorrelat\w*\b",
    r"\bformation\b",
    r"\bbasin\b",
    r"\bfield[- ]level\b",
    r"\bacross (?:the )?(?:wells|field|samples)\b",
    r"\btrends? across\b",
    r"\bconnected\b",
    r"\bneighbou?rs?\b",
    r"\bporosity between\b",
    r"\bpermeability between\b",
]

# Exact-value / snippet / definition signals → vector search over embeddings.
_VECTOR_SIGNALS = [
    r"\d",                                  # any literal number in the ask
    r"\bwhat is the\b",
    r"\bdefin(?:e|ition)\b",
    r"\bexact\b",
    r"\bvalue of\b",
    r"\blook ?up\b",
    r"\bequation\b",
    r"\bformula\b",
    r"\bpsi\b|\bmd\b|\bscf\b|\bcp\b",       # engineering units
    r"\"[^\"]+\"|'[^']+'",                  # quoted snippet
    r"\bthreshold pressure\b|\bentry pressure\b|\bporosity\b|\bpermeability\b"
    r"|\bswi\b|\bsor\b|\barchie\b|\bbrooks[- ]corey\b",
]


@dataclass
class RouteDecision:
    route: RagRoute
    confidence: float
    signals: List[str] = field(default_factory=list)


def _matches(patterns: List[str], text: str) -> List[str]:
    return [p for p in patterns if re.search(p, text, re.IGNORECASE)]


def classify_query(query: str) -> RouteDecision:
    """Classify one user query into a retrieval route.

    Both signal families firing means the question needs global entity context
    AND local exact facts → HYBRID. Neither firing defaults to VECTOR_SEARCH:
    embeddings are always available and are the cheapest safe retrieval.
    """
    text = (query or "").strip()
    if not text:
        return RouteDecision(RagRoute.VECTOR_SEARCH, 0.0, [])

    graph_hits = _matches(_GRAPH_SIGNALS, text)
    vector_hits = _matches(_VECTOR_SIGNALS, text)

    if graph_hits and vector_hits:
        route = RagRoute.HYBRID
    elif graph_hits:
        route = RagRoute.GRAPH_SEARCH
    else:
        route = RagRoute.VECTOR_SEARCH

    hits = len(graph_hits) + len(vector_hits)
    confidence = 0.5 if hits == 0 else min(1.0, 0.5 + 0.15 * hits)
    return RouteDecision(route, round(confidence, 2), graph_hits + vector_hits)


# ── Rakeza master routing: WHICH knowledge base serves this query ────────────
# classify_query (above) picks HOW to retrieve inside one pipeline;
# classify_domain picks WHERE — Hviel's SCAL KB, Aviel's PVT fluid KB, or the
# cross-department master summaries owned by the Rakeza supervisor.

class RagDomain(str, Enum):
    HVIEL_LOCAL = "HVIEL_LOCAL"      # SCAL knowledge base (Hviel)
    AVIEL_LOCAL = "AVIEL_LOCAL"      # PVT fluid knowledge base (Aviel)
    RAKEZA_GLOBAL = "RAKEZA_GLOBAL"  # cross-department master reservoir summaries


_GLOBAL_SIGNALS = [
    r"\bcross[- ]department\b",
    r"\bmaster reservoir\b",
    r"\bfield[- ]wide\b",
    r"\bcompany[- ]wide\b",
    r"\ball departments\b",
    r"\bboth pipelines\b",
    r"\bscal and pvt\b|\bpvt and scal\b",
    r"\bfull reservoir summary\b",
]


@dataclass
class DomainDecision:
    domain: RagDomain
    confidence: float
    signals: List[str] = field(default_factory=list)


def classify_domain(query: str) -> DomainDecision:
    """Route a query to the owning knowledge base.

    Explicit cross-department language — or vocabulary from BOTH domains —
    goes to the Rakeza master summaries. Pure PVT vocabulary goes to Aviel's
    fluid KB. Everything else (SCAL vocabulary or no signal) defaults to
    Hviel's SCAL KB, the hub's primary domain.
    """
    # Single source of domain vocabulary: the Rakeza worker-routing keywords.
    from hviel.rakeza.contracts import PVT_KEYWORDS, SCAL_KEYWORDS

    text = (query or "").strip()
    if not text:
        return DomainDecision(RagDomain.HVIEL_LOCAL, 0.0, [])

    global_hits = _matches(_GLOBAL_SIGNALS, text)
    low = f" {text.lower()} "
    pvt_hits = [k for k in PVT_KEYWORDS if k in low]
    scal_hits = [k for k in SCAL_KEYWORDS if k in low]

    if global_hits or (pvt_hits and scal_hits):
        domain = RagDomain.RAKEZA_GLOBAL
        signals = global_hits + pvt_hits + scal_hits
    elif pvt_hits:
        domain = RagDomain.AVIEL_LOCAL
        signals = pvt_hits
    else:
        domain = RagDomain.HVIEL_LOCAL
        signals = scal_hits

    hits = len(signals)
    confidence = 0.5 if hits == 0 else min(1.0, 0.5 + 0.15 * hits)
    return DomainDecision(domain, round(confidence, 2), signals)


def merge_context_chunks(vector_ctx: str, extra_chunks: List[str]) -> str:
    """Merge vector-search context with graph-search chunks, de-duplicating by
    normalized content snippet (whitespace-collapsed, case-folded, first 120
    chars) so the HYBRID route never injects the same passage twice."""
    seen = set()
    merged: List[str] = []
    base = [c.strip() for c in (vector_ctx or "").split("\n\n") if c.strip()]
    extra = [c.strip() for c in extra_chunks if c and c.strip()]
    for chunk in base + extra:
        key = " ".join(chunk.lower().split())[:120]
        if key in seen:
            continue
        seen.add(key)
        merged.append(chunk)
    return "\n\n".join(merged)
