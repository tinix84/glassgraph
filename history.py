"""Per-backfill timeseries tracking + delta reporting.

Appends one JSONL entry per backfill run. The `--history` flag on
`link.py backfill` reads the previous entry, computes deltas, and includes
a 'Changes since last backfill' section in the report.
"""
from __future__ import annotations

import json
from pathlib import Path

import networkx as nx


def append_run(path: Path, entry: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False))
        f.write("\n")


def read_last_run(path: Path) -> dict | None:
    if not path.exists():
        return None
    last = None
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                last = json.loads(line)
            except json.JSONDecodeError:
                continue
    return last


def build_history_entry(
    ts: str,
    match_rate: float,
    sources: list[str],
    orphans: int,
    phantoms: int,
    G_current: nx.DiGraph,
    G_stage1: nx.DiGraph,
    entity_nodes: set[str],
    top_n: int = 50,
) -> dict:
    """Shape a backfill result into a JSONL entry. Caps tracked entities at top_n by combined in-degree."""
    def _in(G, n):
        return G.in_degree(n) if G.has_node(n) else 0

    combined = [(n, _in(G_current, n) + _in(G_stage1, n)) for n in entity_nodes]
    combined.sort(key=lambda x: -x[1])
    tracked = [n for n, _ in combined[:top_n]]

    in_degrees = {
        n: {"current": _in(G_current, n), "stage1": _in(G_stage1, n)}
        for n in tracked
    }

    return {
        "ts": ts,
        "match_rate": round(match_rate, 4),
        "sources": len(sources),
        "orphans": orphans,
        "phantoms": phantoms,
        "entity_in_degrees": in_degrees,
    }


def compute_delta(prev: dict, curr: dict, min_abs_delta: int = 3) -> dict:
    """Compute changes since the previous run for the report."""
    prev_rate = prev.get("match_rate", 0.0)
    curr_rate = curr.get("match_rate", 0.0)

    prev_in = prev.get("entity_in_degrees", {})
    curr_in = curr.get("entity_in_degrees", {})

    all_nodes = set(prev_in.keys()) | set(curr_in.keys())
    movers = []
    for n in all_nodes:
        p_cur = prev_in.get(n, {}).get("current", 0)
        c_cur = curr_in.get(n, {}).get("current", 0)
        p_s1 = prev_in.get(n, {}).get("stage1", 0)
        c_s1 = curr_in.get(n, {}).get("stage1", 0)
        d_cur = c_cur - p_cur
        d_s1 = c_s1 - p_s1
        if abs(d_cur) >= min_abs_delta or abs(d_s1) >= min_abs_delta:
            movers.append({
                "canonical": n,
                "current_before": p_cur, "current_after": c_cur, "current_delta": d_cur,
                "stage1_before": p_s1, "stage1_after": c_s1, "stage1_delta": d_s1,
            })
    movers.sort(key=lambda m: -(abs(m["current_delta"]) + abs(m["stage1_delta"])))

    return {
        "prev_ts": prev.get("ts"),
        "curr_ts": curr.get("ts"),
        "match_rate_delta": round(curr_rate - prev_rate, 4),
        "top_movers": movers,
    }


def format_delta_section(delta: dict) -> str:
    if not delta.get("prev_ts"):
        return "\n## First backfill — no previous run to compare against\n"
    lines = [
        "",
        f"## Changes since last backfill ({delta['prev_ts']})",
        "",
        f"- Match rate delta: {delta['match_rate_delta']:+.4f}",
        "",
        "### Top movers (|Δ| ≥ 3 on current or Stage 1 in-degree)",
    ]
    if not delta["top_movers"]:
        lines.append("- (none above threshold)")
    for m in delta["top_movers"][:20]:
        lines.append(
            f"- [[{m['canonical']}]] | current {m['current_before']} → {m['current_after']} "
            f"({m['current_delta']:+d}), Stage 1 {m['stage1_before']} → {m['stage1_after']} "
            f"({m['stage1_delta']:+d})"
        )
    return "\n".join(lines) + "\n"
