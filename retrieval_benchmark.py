"""Evidence-level retrieval benchmark metrics."""
from __future__ import annotations

import math
import statistics


def _matches(hit: dict, passage: dict) -> bool:
    passage_text = passage.get("text")
    return (
        hit.get("path") == passage.get("path")
        and isinstance(passage_text, str)
        and passage_text != ""
        and passage_text in str(hit.get("text") or "")
    )


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))


def _ndcg_at_10(groups: list[list[dict]], hits: list[dict]) -> float:
    grade_value = {"direct": 2, "supporting": 1}
    unused = set(range(len(groups)))
    ranked_grades = []
    for hit in hits[:10]:
        matching = [
            (max(grade_value[passage["grade"]] for passage in groups[index] if _matches(hit, passage)), index)
            for index in unused
            if any(_matches(hit, passage) for passage in groups[index])
        ]
        if not matching:
            ranked_grades.append(0)
            continue
        grade, index = max(matching)
        unused.remove(index)
        ranked_grades.append(grade)

    ideal = sorted(
        (max(grade_value[passage["grade"]] for passage in group) for group in groups),
        reverse=True,
    )[:10]
    ideal_dcg = _dcg(ideal)
    return _dcg(ranked_grades) / ideal_dcg if ideal_dcg else 0.0


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def evaluate(queries: list[dict], runs: dict[str, dict]) -> dict:
    """Return aggregate metrics for ranked retrieval runs."""
    recalls_at_5 = []
    recalls_at_10 = []
    reciprocal_ranks = []
    ndcgs = []
    negative_queries = 0
    negative_false_positives = 0
    negative_raw_false_positives = 0
    latencies = []
    peak_working_sets = []
    path_relevant_hits = 0
    exact_evidence_hits = 0
    context_tokens_top_5 = []
    explained_hits_top_5 = []
    for query in queries:
        run = runs.get(query["id"], {"hits": []})
        accepted_hits = run.get("hits", [])
        raw_hits = run.get("raw_hits", accepted_hits)
        if "latency_ms" in run:
            latencies.append(run["latency_ms"])
        if "peak_working_set_bytes" in run:
            peak_working_sets.append(run["peak_working_set_bytes"])
        context_tokens_top_5.append(
            sum(hit.get("context_tokens", 0) for hit in raw_hits[:5])
        )
        explained_hits_top_5.append(
            sum(bool(hit.get("explanation")) for hit in raw_hits[:5])
        )
        groups = query.get("required_groups", [])
        if not groups:
            negative_queries += 1
            if raw_hits[:5]:
                negative_raw_false_positives += 1
            if accepted_hits[:5]:
                negative_false_positives += 1
            continue
        for limit, recalls in ((5, recalls_at_5), (10, recalls_at_10)):
            satisfied = sum(
                any(
                    _matches(hit, passage)
                    for hit in raw_hits[:limit]
                    for passage in group
                )
                for group in groups
            )
            recalls.append(satisfied / len(groups))
        expected_paths = {passage["path"] for group in groups for passage in group}
        first_relevant_rank = next(
            (
                rank
                for rank, hit in enumerate(raw_hits, start=1)
                if hit.get("path") in expected_paths
            ),
            None,
        )
        reciprocal_ranks.append(1 / first_relevant_rank if first_relevant_rank else 0.0)
        ndcgs.append(_ndcg_at_10(groups, raw_hits))
        path_relevant_hits += sum(
            hit.get("path") in expected_paths for hit in raw_hits[:10]
        )
        unused_groups = set(range(len(groups)))
        for hit in raw_hits[:10]:
            matching_group = next(
                (
                    index
                    for index in unused_groups
                    if any(_matches(hit, passage) for passage in groups[index])
                ),
                None,
            )
            if matching_group is not None:
                exact_evidence_hits += 1
                unused_groups.remove(matching_group)

    return {
        "positive_queries": len(recalls_at_5),
        "group_recall_at_5": (
            sum(recalls_at_5) / len(recalls_at_5) if recalls_at_5 else 0.0
        ),
        "group_recall_at_10": (
            sum(recalls_at_10) / len(recalls_at_10) if recalls_at_10 else 0.0
        ),
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "ndcg_at_10": sum(ndcgs) / len(ndcgs) if ndcgs else 0.0,
        "evidence_span_accuracy": (
            exact_evidence_hits / path_relevant_hits if path_relevant_hits else 0.0
        ),
        "negative_queries": negative_queries,
        "negative_false_positive_rate_at_5": (
            negative_false_positives / negative_queries if negative_queries else 0.0
        ),
        "negative_raw_false_positive_rate_at_5": (
            negative_raw_false_positives / negative_queries if negative_queries else 0.0
        ),
        "latency_ms_p50": statistics.median(latencies) if latencies else 0.0,
        "latency_ms_p95": _percentile(latencies, 0.95) if latencies else 0.0,
        "peak_working_set_bytes": max(peak_working_sets, default=0),
        "mean_context_tokens_top_5": (
            statistics.mean(context_tokens_top_5) if context_tokens_top_5 else 0.0
        ),
        "mean_explained_hits_top_5": (
            statistics.mean(explained_hits_top_5) if explained_hits_top_5 else 0.0
        ),
    }
