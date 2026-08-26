"""Geological Knowledge Graph for the PRC SCAL AI Pipeline.

A lightweight, queryable relational layer that complements the vector RAG store
(:mod:`rag_database`) without polluting it. Where ChromaDB answers *semantic*
questions ("find a report that reads like this"), this module answers *relational*
ones ("which formations sit in the Sirte Basin and carry carbonate lithology?").

Design notes
------------
* Persistence is a single SQLite file (stdlib ``sqlite3`` — no extra deps). The
  path is resolved from :data:`config.settings` so it lands on the same
  persistent disk as the rest of the pipeline.
* The schema is a classic property-graph-on-SQL: an append-friendly ``nodes``
  table and a directed ``edges`` table. Edge metadata is stored as a JSON blob.
* All SQL is parameterised — never string-interpolated — per the project's
  SQL-injection invariants (see CLAUDE.md §4).
* Graph traversal is a bounded breadth-first search executed in Python so that
  ``depth_limit`` is honoured deterministically regardless of SQLite version.

The class is intentionally decoupled from the vector store: :meth:`hybrid_search`
accepts an optional retriever so the caller (or a test) injects the dependency,
keeping this module import-light and unit-testable offline.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from collections import deque
from contextlib import contextmanager
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

_logger = logging.getLogger("prc-graph")


class NodeType(str, Enum):
    """The entity kinds the geological graph models."""

    BASIN = "Basin"
    FORMATION = "Formation"
    LITHOLOGY = "Lithology"
    WELL = "Well"
    FLUID_TYPE = "FluidType"
    SAMPLE = "Sample"


class RelationType(str, Enum):
    """Directed relationships connecting the node kinds."""

    LOCATED_IN = "LOCATED_IN"        # Formation  -> Basin
    HAS_LITHOLOGY = "HAS_LITHOLOGY"  # Formation  -> Lithology
    PENETRATES = "PENETRATES"        # Well       -> Formation
    CONTAINS_FLUID = "CONTAINS_FLUID"  # Formation -> FluidType
    HAS_SAMPLE = "HAS_SAMPLE"        # Well       -> Sample


def _coerce_type(value: "str | NodeType", enum_cls) -> str:
    """Normalise a node/relation type argument to its canonical string value.

    Accepts either the enum member or its string value so callers parsing raw
    document text are not forced to import the enums.
    """
    if isinstance(value, enum_cls):
        return value.value
    candidate = str(value).strip()
    # Validate against the known vocabulary; reject unknown types loudly rather
    # than silently corrupting the graph.
    valid = {member.value for member in enum_cls}
    if candidate not in valid:
        raise ValueError(
            f"{enum_cls.__name__} '{candidate}' is not one of {sorted(valid)}"
        )
    return candidate


class GeologicalGraph:
    """SQLite-backed directed knowledge graph of basins, formations and wells.

    Parameters
    ----------
    db_path:
        Destination SQLite file. When ``None`` the path is taken from
        :data:`config.settings.graph_db_path`. Pass ``":memory:"`` for an
        ephemeral in-process graph (used heavily by the test-suite).
    seed:
        When ``True`` (default) an empty database is populated with the
        default Libyan basin/formation/well slice via
        :meth:`_seed_default_relations`. Pass ``False`` for a pristine graph
        (the unit tests rely on this).
    """

    def __init__(self, db_path: Optional[str] = None, seed: bool = True) -> None:
        if db_path is None:
            # Imported lazily so the module stays usable in minimal environments
            # (e.g. isolated unit tests) where the full settings stack is absent.
            from config import settings

            db_path = settings.graph_db_path

        self._db_path = db_path
        # An in-memory database only persists while a connection is open, so we
        # hold a single shared connection for ":memory:" and reconnect per call
        # for file-backed stores (keeps file handles short-lived on Render).
        self._shared_conn: Optional[sqlite3.Connection] = (
            sqlite3.connect(db_path) if db_path == ":memory:" else None
        )
        self._initialise_schema()
        if seed:
            self._seed_default_relations()
        _logger.info("GeologicalGraph ready at %s", db_path)

    # ── connection management ─────────────────────────────────────────────────

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        """Yield a connection, committing on success and closing file-backed ones."""
        conn = self._shared_conn or sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            if self._shared_conn is None:
                conn.close()

    def _initialise_schema(self) -> None:
        """Create the node/edge tables and supporting indexes if absent."""
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS nodes (
                    name       TEXT NOT NULL,
                    node_type  TEXT NOT NULL,
                    PRIMARY KEY (name, node_type)
                );

                CREATE TABLE IF NOT EXISTS edges (
                    source_name  TEXT NOT NULL,
                    source_type  TEXT NOT NULL,
                    target_name  TEXT NOT NULL,
                    target_type  TEXT NOT NULL,
                    relation     TEXT NOT NULL,
                    metadata     TEXT NOT NULL DEFAULT '{}',
                    PRIMARY KEY (source_name, source_type, target_name,
                                 target_type, relation)
                );

                CREATE INDEX IF NOT EXISTS idx_edges_source
                    ON edges (source_name, source_type);
                CREATE INDEX IF NOT EXISTS idx_edges_target
                    ON edges (target_name, target_type);
                """
            )

    # ── write path ────────────────────────────────────────────────────────────

    def _seed_default_relations(self) -> int:
        """Populate an empty graph with the default Libyan geological slice.

        Idempotent: any pre-existing node means the store is already seeded (or
        deliberately curated), so nothing is written and ``0`` is returned.
        Otherwise the default basin/formation/lithology/fluid/well relations
        are bulk-loaded and the ingested count is returned.
        """
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM nodes LIMIT 1").fetchone()
        if row is not None:
            return 0

        relations: List[Sequence[Any]] = [
            # Formations in Basins
            ("Gialo Formation", "Formation", "Sirte Basin", "Basin", "LOCATED_IN"),
            ("Zelten Formation", "Formation", "Sirte Basin", "Basin", "LOCATED_IN"),
            ("Waha Formation", "Formation", "Sirte Basin", "Basin", "LOCATED_IN"),
            ("Bahi Formation", "Formation", "Sirte Basin", "Basin", "LOCATED_IN"),
            ("Dahra Formation", "Formation", "Sirte Basin", "Basin", "LOCATED_IN"),
            ("Mamuniyat Formation", "Formation", "Murzuq Basin", "Basin", "LOCATED_IN"),
            # Formation lithologies
            ("Gialo Formation", "Formation", "Carbonate", "Lithology", "HAS_LITHOLOGY"),
            ("Zelten Formation", "Formation", "Carbonate", "Lithology", "HAS_LITHOLOGY"),
            ("Waha Formation", "Formation", "Sandstone", "Lithology", "HAS_LITHOLOGY"),
            ("Bahi Formation", "Formation", "Sandstone", "Lithology", "HAS_LITHOLOGY"),
            ("Dahra Formation", "Formation", "Carbonate", "Lithology", "HAS_LITHOLOGY"),
            ("Mamuniyat Formation", "Formation", "Sandstone", "Lithology", "HAS_LITHOLOGY"),
            # Formation fluids
            ("Gialo Formation", "Formation", "Oil", "FluidType", "CONTAINS_FLUID"),
            ("Zelten Formation", "Formation", "Oil", "FluidType", "CONTAINS_FLUID"),
            ("Waha Formation", "Formation", "Oil", "FluidType", "CONTAINS_FLUID"),
            ("Bahi Formation", "Formation", "Gas", "FluidType", "CONTAINS_FLUID"),
            ("Dahra Formation", "Formation", "Oil", "FluidType", "CONTAINS_FLUID"),
            ("Mamuniyat Formation", "Formation", "Oil", "FluidType", "CONTAINS_FLUID"),
            # Wells penetrating formations (petrophysics on the edge metadata)
            ("Well-A1", "Well", "Gialo Formation", "Formation", "PENETRATES",
             {"porosity": 0.22, "permeability": 120.0}),
            ("Well-B2", "Well", "Zelten Formation", "Formation", "PENETRATES",
             {"porosity": 0.18, "permeability": 45.0}),
            ("Well-C3", "Well", "Waha Formation", "Formation", "PENETRATES",
             {"porosity": 0.25, "permeability": 350.0}),
            ("Well-T1-31", "Well", "Gialo Formation", "Formation", "PENETRATES",
             {"porosity": 0.21, "permeability": 95.0}),
        ]
        ingested = self.import_relations(relations)
        _logger.info("Seeded geological graph with %d default relations.", ingested)
        return ingested

    def add_relation(
        self,
        source_node: str,
        source_type: "str | NodeType",
        target_node: str,
        target_type: "str | NodeType",
        relation_type: "str | RelationType",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Insert (or upsert) a directed edge and its two endpoint nodes.

        The operation is idempotent: re-adding the same edge refreshes its
        metadata rather than duplicating the row.
        """
        src_type = _coerce_type(source_type, NodeType)
        tgt_type = _coerce_type(target_type, NodeType)
        rel = _coerce_type(relation_type, RelationType)
        src = source_node.strip()
        tgt = target_node.strip()
        if not src or not tgt:
            raise ValueError("source_node and target_node must be non-empty.")
        meta_json = json.dumps(metadata or {}, ensure_ascii=False, sort_keys=True)

        with self._connect() as conn:
            for name, ntype in ((src, src_type), (tgt, tgt_type)):
                conn.execute(
                    "INSERT OR IGNORE INTO nodes (name, node_type) VALUES (?, ?)",
                    (name, ntype),
                )
            conn.execute(
                """
                INSERT INTO edges
                    (source_name, source_type, target_name, target_type,
                     relation, metadata)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (source_name, source_type, target_name,
                             target_type, relation)
                DO UPDATE SET metadata = excluded.metadata
                """,
                (src, src_type, tgt, tgt_type, rel, meta_json),
            )
        _logger.debug("Edge upserted: (%s:%s)-[%s]->(%s:%s)",
                      src, src_type, rel, tgt, tgt_type)

    def import_relations(
        self, relations: Iterable[Sequence[Any]]
    ) -> int:
        """Bulk-load relations parsed from documents.

        Each item is an ``(source, source_type, target, target_type, relation,
        metadata?)`` tuple — the positional form of :meth:`add_relation`. Returns
        the count successfully ingested; malformed rows are logged and skipped so
        one bad line never aborts a whole document import.
        """
        ingested = 0
        for row in relations:
            try:
                source, s_type, target, t_type, rel = row[:5]
                metadata = row[5] if len(row) > 5 else None
                self.add_relation(source, s_type, target, t_type, rel, metadata)
                ingested += 1
            except (ValueError, IndexError, TypeError) as exc:
                _logger.warning("Skipping malformed relation %r: %s", row, exc)
        _logger.info("Imported %d/%d relations.", ingested, _safe_len(relations))
        return ingested

    def link_samples(
        self,
        well_name: str,
        samples: Dict[str, Any],
        data_type: str,
        source_file: str = "",
    ) -> int:
        """Register extracted lab samples against their well.

        Each key of ``samples`` (the per-sheet dict produced by the extractors)
        becomes a ``Sample`` node named ``"<well>/<file-stem>/<sheet>"`` —
        qualified by well AND source file, because generic sheet names
        ('Sheet1' for every CSV) would otherwise collide across a well's lab
        files and silently overwrite provenance. Re-linking the same file is
        idempotent (upsert). Each ``Well -[HAS_SAMPLE]-> Sample`` edge carries
        the SCAL data type and source filename. Returns the number of samples
        linked. Wells that could not be identified ('PROVISIONAL WELL') are
        skipped: an edge to a fake well is worse than no edge.
        """
        well = (well_name or "").strip()
        if not well or well.upper() == "PROVISIONAL WELL":
            return 0
        stem = Path(source_file).stem if source_file else ""
        linked = 0
        for sheet in samples or {}:
            meta = {"data_type": data_type, "sheet": str(sheet)}
            if source_file:
                meta["source_file"] = source_file
            sample_id = f"{well}/{stem}/{sheet}" if stem else f"{well}/{sheet}"
            self.add_relation(
                well, NodeType.WELL,
                sample_id, NodeType.SAMPLE,
                RelationType.HAS_SAMPLE, meta,
            )
            linked += 1
        if linked:
            _logger.info("Linked %d sample(s) to well '%s'.", linked, well)
        return linked

    # ── read path ─────────────────────────────────────────────────────────────

    def _neighbours(
        self, conn: sqlite3.Connection, name: str
    ) -> List[Tuple[str, str, str, Dict[str, Any], str]]:
        """Return outbound and inbound neighbours of ``name`` (undirected walk).

        Each tuple is ``(neighbour_name, neighbour_type, relation, metadata,
        direction)`` where direction is ``"out"`` or ``"in"``.
        """
        rows = conn.execute(
            """
            SELECT target_name AS nbr, target_type AS nbr_type,
                   relation, metadata, 'out' AS direction
            FROM edges WHERE source_name = ?
            UNION ALL
            SELECT source_name AS nbr, source_type AS nbr_type,
                   relation, metadata, 'in' AS direction
            FROM edges WHERE target_name = ?
            """,
            (name, name),
        ).fetchall()
        return [
            (r["nbr"], r["nbr_type"], r["relation"],
             json.loads(r["metadata"]), r["direction"])
            for r in rows
        ]

    def query_connections(
        self, node_name: str, depth_limit: int = 1
    ) -> Dict[str, Any]:
        """Breadth-first traversal of everything reachable from ``node_name``.

        Parameters
        ----------
        node_name:
            Starting node (matched by name, type-agnostic).
        depth_limit:
            Maximum hop distance to explore (``>= 1``).

        Returns
        -------
        dict
            ``{"root", "depth_limit", "nodes": [...], "edges": [...]}`` — a
            JSON-serialisable subgraph ready for UI rendering or LLM grounding.
        """
        if depth_limit < 1:
            raise ValueError("depth_limit must be >= 1.")
        root = node_name.strip()

        visited: Dict[str, int] = {root: 0}
        edges: List[Dict[str, Any]] = []
        seen_edges: set = set()
        frontier: deque = deque([(root, 0)])

        with self._connect() as conn:
            if not self._node_exists(conn, root):
                _logger.info("query_connections: node '%s' not present.", root)
                return {"root": root, "depth_limit": depth_limit,
                        "nodes": [], "edges": []}

            while frontier:
                current, depth = frontier.popleft()
                if depth >= depth_limit:
                    continue
                for nbr, nbr_type, rel, meta, direction in self._neighbours(conn, current):
                    # Canonical edge key is direction-independent so an edge
                    # surfaced from both endpoints is only reported once.
                    edge_key = tuple(sorted((current, nbr))) + (rel,)
                    if edge_key not in seen_edges:
                        seen_edges.add(edge_key)
                        src, tgt = (current, nbr) if direction == "out" else (nbr, current)
                        edges.append({"source": src, "target": tgt,
                                      "relation": rel, "metadata": meta})
                    if nbr not in visited:
                        visited[nbr] = depth + 1
                        frontier.append((nbr, depth + 1))

            node_types = self._node_types(conn, list(visited))

        nodes = [
            {"name": name, "type": node_types.get(name), "distance": dist}
            for name, dist in sorted(visited.items(), key=lambda kv: kv[1])
        ]
        return {"root": root, "depth_limit": depth_limit,
                "nodes": nodes, "edges": edges}

    def neighbours_by_relation(
        self,
        node_name: str,
        relation_type: "str | RelationType",
        target_type: Optional["str | NodeType"] = None,
    ) -> List[Dict[str, Any]]:
        """Direct (1-hop) outbound neighbours filtered by relation and type.

        Convenience accessor for the common "Formations LOCATED_IN this Basin"
        style lookup without a full BFS.
        """
        rel = _coerce_type(relation_type, RelationType)
        params: List[Any] = [node_name.strip(), rel]
        sql = (
            "SELECT target_name AS name, target_type AS type, metadata "
            "FROM edges WHERE source_name = ? AND relation = ?"
        )
        if target_type is not None:
            sql += " AND target_type = ?"
            params.append(_coerce_type(target_type, NodeType))
        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()
        return [
            {"name": r["name"], "type": r["type"],
             "metadata": json.loads(r["metadata"])}
            for r in rows
        ]

    def hybrid_search(
        self,
        query_text: str,
        porous_range: Optional[Tuple[float, float]] = None,
        perm_range: Optional[Tuple[float, float]] = None,
        retriever: Optional[Any] = None,
        depth_limit: int = 1,
        n_results: int = 3,
    ) -> Dict[str, Any]:
        """Fuse graph connectivity with semantic vector retrieval.

        The graph side anchors the answer in explicit relationships (basins,
        lithologies, fluids) while the vector side surfaces analog wells whose
        petrophysics fall inside the requested porosity/permeability windows.

        Parameters
        ----------
        query_text:
            Free-text query; node names appearing in it seed the graph traversal.
        porous_range, perm_range:
            ``(low, high)`` petrophysical filters forwarded to the vector store.
            The midpoint drives the analog-well lookup.
        retriever:
            Object exposing ``query_analog_wells(current_porosity, current_perm,
            n_results)`` — typically a :class:`rag_database.RAGDatabase`. Injected
            for testability; when ``None`` the vector half is skipped gracefully.
        depth_limit:
            Hop depth for the graph component.

        Returns
        -------
        dict
            ``{"query", "graph": {...}, "vector": [...]}``.
        """
        graph_hits = self._match_nodes(query_text)
        graph_payload = [
            self.query_connections(name, depth_limit=depth_limit)
            for name in graph_hits
        ]

        vector_payload: List[Dict[str, Any]] = []
        if retriever is not None and (porous_range or perm_range):
            porosity = _midpoint(porous_range)
            perm = _midpoint(perm_range)
            if porosity is not None and perm is not None:
                try:
                    vector_payload = retriever.query_analog_wells(
                        current_porosity=porosity,
                        current_perm=perm,
                        n_results=n_results,
                    )
                except Exception as exc:  # pragma: no cover - defensive
                    _logger.error("Vector retrieval failed in hybrid_search: %s", exc)

        return {
            "query": query_text,
            "graph": {"matched_nodes": graph_hits, "subgraphs": graph_payload},
            "vector": vector_payload,
        }

    # ── small SQL helpers ─────────────────────────────────────────────────────

    def _node_exists(self, conn: sqlite3.Connection, name: str) -> bool:
        row = conn.execute(
            "SELECT 1 FROM nodes WHERE name = ? LIMIT 1", (name,)
        ).fetchone()
        return row is not None

    def _node_types(
        self, conn: sqlite3.Connection, names: List[str]
    ) -> Dict[str, str]:
        if not names:
            return {}
        placeholders = ",".join("?" for _ in names)
        rows = conn.execute(
            f"SELECT name, node_type FROM nodes WHERE name IN ({placeholders})",
            names,
        ).fetchall()
        return {r["name"]: r["node_type"] for r in rows}

    def _match_nodes(self, query_text: str) -> List[str]:
        """Return stored node names that appear (case-insensitive) in the query."""
        with self._connect() as conn:
            rows = conn.execute("SELECT DISTINCT name FROM nodes").fetchall()
        lowered = query_text.lower()
        return [r["name"] for r in rows if r["name"].lower() in lowered]

    def all_nodes(self) -> List[Dict[str, str]]:
        """Return every node as ``{"name", "type"}`` (diagnostics / export)."""
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT name, node_type FROM nodes ORDER BY node_type, name"
            ).fetchall()
        return [{"name": r["name"], "type": r["node_type"]} for r in rows]

    def close(self) -> None:
        """Release the shared in-memory connection, if any."""
        if self._shared_conn is not None:
            self._shared_conn.close()
            self._shared_conn = None


# ── module-level helpers ───────────────────────────────────────────────────────

def _midpoint(rng: Optional[Tuple[float, float]]) -> Optional[float]:
    """Mean of a ``(low, high)`` pair, or ``None`` when the range is absent."""
    if not rng:
        return None
    low, high = rng
    return (float(low) + float(high)) / 2.0


def _safe_len(items: Iterable[Any]) -> int:
    """Length of ``items`` when sized, else ``-1`` (for log messages on iterators)."""
    try:
        return len(items)  # type: ignore[arg-type]
    except TypeError:
        return -1
