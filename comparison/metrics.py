"""Metrics for graphify vs entity_linker comparison.

Three families:
  1. Precision / Recall / F1 against a per-source ground-truth dict
  2. Jaccard similarity between two extraction runs (determinism check)
  3. Graph-structural summaries (node/edge counts, in-degree distribution)

Plus a name-normalization helper to compare entity names across tools that may
emit "Tesla, Inc." vs "Tesla" for the same canonical entity.
"""
from __future__ import annotations

import re

import networkx as nx


# ── Name normalization ─────────────────────────────────────────────────────

_SUFFIX_RE = re.compile(
    r"[\s,]+("
    r"inc\.?|incorporated|"
    r"corp\.?|corporation|"
    r"co\.?(?:\s+ltd\.?)?|company|"
    r"ltd\.?|limited|"
    r"llc|llp|gmbh|sa|ag|nv|bv|"
    r"plc"
    r")\.?\s*$",
    re.IGNORECASE,
)
_LEADING_ARTICLE_RE = re.compile(r"^\s*(the|a|an)\s+", re.IGNORECASE)
_PARENTHETICAL_RE = re.compile(r"\s*\([^)]*\)\s*")
_NONALNUM_CJK_RE = re.compile(r"[^a-z0-9一-鿿]+")


def normalize_name(s: str) -> str:
    """Aggressive slugify: handles SiC-MOSFET vs SiC MOSFET, Tesla, Inc. vs Tesla,
    Texas Instruments (TI) vs Texas-Instruments. Result is lowercase ASCII alnum +
    CJK only — all whitespace, hyphens, punctuation, parentheticals dropped.
    """
    s = s.strip()
    s = _LEADING_ARTICLE_RE.sub("", s)
    s = _PARENTHETICAL_RE.sub(" ", s)  # drop parenthetical aliases like "(TI)"
    # Drop corp suffixes iteratively (handles "Co. Ltd." cases)
    while True:
        new = _SUFFIX_RE.sub("", s)
        if new == s:
            break
        s = new.strip()
    s = s.lower()
    # Slugify: keep ASCII alphanumerics + CJK ideographs; drop everything else
    return _NONALNUM_CJK_RE.sub("", s)


def match_sets_normalized(a: set[str], b: set[str]) -> set[tuple[str, str]]:
    """Return the set of (a_name, b_name) pairs that normalize to the same string."""
    a_by_norm = {}
    for name in a:
        a_by_norm.setdefault(normalize_name(name), name)
    matches = set()
    for name_b in b:
        norm = normalize_name(name_b)
        if norm in a_by_norm:
            matches.add((a_by_norm[norm], name_b))
    return matches


def _normalized_intersection(a: set[str], b: set[str]) -> int:
    return len(match_sets_normalized(a, b))


# ── Precision / Recall ──────────────────────────────────────────────────────

def precision_recall(extracted: dict[str, set[str]], truth: dict[str, set[str]]) -> dict:
    """Per-source P/R/F1, then macro-averaged. Skips sources with empty truth.

    Args:
        extracted: {source_stem: {entity_name, ...}} from the tool under test.
        truth: {source_stem: {entity_name, ...}} ground truth.

    Uses name normalization (Tesla, Inc. == Tesla) when computing intersections.
    """
    precisions, recalls, f1s = [], [], []
    sources_scored = 0
    sources_skipped_empty_truth = 0
    sources_skipped_empty_extracted = 0
    per_source: dict[str, dict] = {}

    common_sources = set(truth.keys()) | set(extracted.keys())
    for src in common_sources:
        t = truth.get(src, set())
        e = extracted.get(src, set())
        if not t:
            sources_skipped_empty_truth += 1
            continue
        if not e:
            sources_skipped_empty_extracted += 1
            per_source[src] = {"precision": 0.0, "recall": 0.0, "f1": 0.0, "tp": 0, "fp": 0, "fn": len(t)}
            continue
        intersection = _normalized_intersection(e, t)
        p = intersection / len(e) if e else 0.0
        r = intersection / len(t) if t else 0.0
        f1 = 2 * p * r / (p + r) if (p + r) > 0 else 0.0
        precisions.append(p)
        recalls.append(r)
        f1s.append(f1)
        sources_scored += 1
        per_source[src] = {
            "precision": p, "recall": r, "f1": f1,
            "tp": intersection, "fp": len(e) - intersection, "fn": len(t) - intersection,
        }

    return {
        "macro_precision": sum(precisions) / len(precisions) if precisions else 0.0,
        "macro_recall": sum(recalls) / len(recalls) if recalls else 0.0,
        "macro_f1": sum(f1s) / len(f1s) if f1s else 0.0,
        "sources_scored": sources_scored,
        "sources_skipped_empty_truth": sources_skipped_empty_truth,
        "sources_skipped_empty_extracted": sources_skipped_empty_extracted,
        "per_source": per_source,
    }


# ── Jaccard (determinism) ──────────────────────────────────────────────────

def mean_jaccard(run_a: dict[str, set[str]], run_b: dict[str, set[str]]) -> float:
    """Mean per-source Jaccard similarity. Returns 1.0 if both empty."""
    common_sources = set(run_a.keys()) | set(run_b.keys())
    if not common_sources:
        return 1.0
    scores = []
    for src in common_sources:
        a = run_a.get(src, set())
        b = run_b.get(src, set())
        if not a and not b:
            scores.append(1.0)
            continue
        intersection = _normalized_intersection(a, b)
        union = len(a | b)  # simple union count for denominator
        if union == 0:
            scores.append(1.0)
        else:
            scores.append(intersection / union)
    return sum(scores) / len(scores)


# ── Graph-structural summaries ─────────────────────────────────────────────

def graph_summary(G: nx.DiGraph, top_n: int = 20) -> dict:
    """Return basic graph stats: node/edge counts, density, top-N in-degree entities."""
    nodes = G.number_of_nodes()
    edges = G.number_of_edges()
    if nodes > 1:
        density = edges / (nodes * (nodes - 1))
    else:
        density = 0.0
    in_degrees = sorted(G.in_degree(), key=lambda x: -x[1])[:top_n]
    return {
        "nodes": nodes,
        "edges": edges,
        "density": density,
        "top_in_degree": in_degrees,
    }
