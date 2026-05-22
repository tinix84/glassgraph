"""Defensive parser for graphify's graph.json output.

graphify schema (best-effort, defensive):
  {
    "nodes": [
      {"id": "src_001", "type": "source", "label": "raw/A.md", ...},
      {"id": "ent_001", "type": "entity", "label": "Tesla", "confidence": "EXTRACTED" | "INFERRED" | "AMBIGUOUS", ...},
      ...
    ],
    "edges": [
      {"source": "src_001", "target": "ent_001", "type": "mentions", ...},
      ...
    ]
  }

Defensive behavior:
- Missing or extra fields are tolerated; only `id`, `type`, `label` are required.
- Unknown node types are skipped (logged in info dict).
- Edges referencing unknown nodes are skipped (logged).
- An empty or missing `graph.json` returns an empty DiGraph + info dict with error key.

The DiGraph uses source-page stems (filename without .md) as source-node IDs and
entity labels as entity-node IDs, matching `load_ours.py`'s convention.
"""
from __future__ import annotations

import json
from pathlib import Path

import networkx as nx


def _strip_md_extension(label: str) -> str:
    """'raw/拆解Tesla.md' → '拆解Tesla'; 'raw/A.md' → 'A'."""
    p = Path(label)
    return p.stem


def load_graphify_graph(
    graph_json_path: Path,
    only_extracted: bool = False,
) -> tuple[nx.DiGraph, dict]:
    """Parse graph.json into a DiGraph with source-stem → entity-label edges.

    Supports two schemas:
      - Old schema: nodes have `type: source|entity`, edges in `edges` key.
      - Current schema (graphify ≥ 2025): nodes have `file_type:
        document|paper|concept|rationale|code|image` and carry their
        attribution as a `source_file` field. Entity edges live in `links`.
        There is no explicit source→entity edge — every concept/rationale
        node is implicitly attached to its source_file.

    Confidence for the new schema is derived from incident edges: a node is
    EXTRACTED if any incident edge has confidence='EXTRACTED', else INFERRED
    if any incident edge is INFERRED, else AMBIGUOUS; nodes with no incident
    edges fall back to EXTRACTED (they were named by the model directly).

    Args:
        graph_json_path: Path to graphify's `graph.json`.
        only_extracted: If True, only include entities with confidence='EXTRACTED'.

    Returns:
        (DiGraph, info_dict) where info_dict has:
          - nodes_parsed: int
          - nodes_skipped: int
          - edges_parsed: int
          - edges_skipped: int
          - error: str | None
    """
    G = nx.DiGraph()
    info = {"nodes_parsed": 0, "nodes_skipped": 0, "edges_parsed": 0, "edges_skipped": 0, "error": None}

    if not graph_json_path.exists():
        info["error"] = f"file not found: {graph_json_path}"
        return G, info

    try:
        data = json.loads(graph_json_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        info["error"] = f"parse error: {e}"
        return G, info

    nodes = data.get("nodes") or []
    edges = data.get("edges") or data.get("links") or []

    # Detect schema: new schema has `file_type` on at least one node.
    is_new_schema = any(isinstance(n, dict) and n.get("file_type") for n in nodes)

    if is_new_schema:
        return _load_new_schema(nodes, edges, only_extracted, G, info)
    return _load_old_schema(nodes, edges, only_extracted, G, info)


_ENTITY_FILE_TYPES = {"concept", "rationale"}
_SOURCE_FILE_TYPES = {"document", "paper", "code", "image"}
_CONFIDENCE_RANK = {"EXTRACTED": 3, "INFERRED": 2, "AMBIGUOUS": 1}


def _load_new_schema(nodes, edges, only_extracted, G, info):
    """New graphify schema: file_type + links + per-node source_file."""
    # Index nodes by id; remember which are entity vs source-summary.
    node_by_id: dict[str, dict] = {}
    for n in nodes:
        if not isinstance(n, dict) or n.get("id") is None or n.get("label") is None:
            info["nodes_skipped"] += 1
            continue
        node_by_id[n["id"]] = n

    # Derive per-node confidence from incident edges.
    best_conf: dict[str, str] = {}
    for e in edges:
        if not isinstance(e, dict):
            continue
        ec = e.get("confidence", "EXTRACTED")
        for endpoint in (e.get("source"), e.get("target")):
            if endpoint in node_by_id:
                prev = best_conf.get(endpoint)
                if prev is None or _CONFIDENCE_RANK.get(ec, 0) > _CONFIDENCE_RANK.get(prev, 0):
                    best_conf[endpoint] = ec

    # Emit (source_stem, entity_label) edges for entity-typed nodes.
    for nid, n in node_by_id.items():
        ft = n.get("file_type")
        if ft in _SOURCE_FILE_TYPES:
            info["nodes_skipped"] += 1  # source-summary node, not an entity
            continue
        if ft not in _ENTITY_FILE_TYPES:
            info["nodes_skipped"] += 1
            continue
        source_file = n.get("source_file")
        if not source_file:
            info["nodes_skipped"] += 1
            continue
        confidence = best_conf.get(nid, "EXTRACTED")
        if only_extracted and confidence != "EXTRACTED":
            info["nodes_skipped"] += 1
            continue
        info["nodes_parsed"] += 1
        u = _strip_md_extension(str(source_file))
        v = str(n["label"])
        if G.has_edge(u, v):
            G[u][v]["weight"] += 1
        else:
            G.add_edge(u, v, weight=1, confidence=confidence)
        info["edges_parsed"] += 1

    return G, info


def _load_old_schema(nodes, edges, only_extracted, G, info):
    """Legacy graphify schema: type: source|entity, edges key."""
    node_index: dict[str, dict] = {}
    for n in nodes:
        if not isinstance(n, dict):
            info["nodes_skipped"] += 1
            continue
        nid = n.get("id")
        ntype = n.get("type")
        label = n.get("label")
        if nid is None or ntype is None or label is None:
            info["nodes_skipped"] += 1
            continue
        if ntype == "source":
            node_index[nid] = {"type": "source", "stem": _strip_md_extension(str(label))}
            info["nodes_parsed"] += 1
        elif ntype == "entity":
            confidence = n.get("confidence", "EXTRACTED")
            if only_extracted and confidence != "EXTRACTED":
                info["nodes_skipped"] += 1
                continue
            node_index[nid] = {"type": "entity", "label": str(label), "confidence": confidence}
            info["nodes_parsed"] += 1
        else:
            info["nodes_skipped"] += 1

    for e in edges:
        if not isinstance(e, dict):
            info["edges_skipped"] += 1
            continue
        src = e.get("source")
        tgt = e.get("target")
        if src is None or tgt is None:
            info["edges_skipped"] += 1
            continue
        src_node = node_index.get(src)
        tgt_node = node_index.get(tgt)
        if src_node is None or tgt_node is None:
            info["edges_skipped"] += 1
            continue
        if src_node["type"] != "source" or tgt_node["type"] != "entity":
            info["edges_skipped"] += 1
            continue
        u = src_node["stem"]
        v = tgt_node["label"]
        if G.has_edge(u, v):
            G[u][v]["weight"] += 1
        else:
            G.add_edge(u, v, weight=1)
        info["edges_parsed"] += 1

    return G, info


def per_source_extracted(G: nx.DiGraph) -> dict[str, set[str]]:
    """Return {source_stem: {entity_label, ...}} for precision/recall computation."""
    out: dict[str, set[str]] = {}
    for u, v in G.edges():
        out.setdefault(u, set()).add(v)
    return out
