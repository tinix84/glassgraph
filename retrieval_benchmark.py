"""Evidence-level retrieval benchmark metrics."""
from __future__ import annotations

import hashlib
import json
import math
import statistics
import unicodedata
from pathlib import Path


def _canonical_hash(domain: str, payload) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    normalized = unicodedata.normalize("NFC", canonical)
    digest = hashlib.sha256(f"{domain}\0{normalized}".encode()).hexdigest()
    return f"sha256:{digest}"


def query_set_hash(records: list[dict]) -> str:
    """Return the frozen hash of benchmark query text and query metadata."""
    fields = ("id", "query", "type", "split", "kind", "owner_authored")
    payload = [
        {key: record[key] for key in fields if key in record}
        for record in sorted(records, key=lambda item: item["id"])
    ]
    return _canonical_hash("glassgraph:benchmark-queries:v1", payload)


def judgment_set_hash(records: list[dict]) -> str:
    """Return the frozen hash of evidence judgments and adjudication metadata."""
    fields = (
        "id",
        "required_groups",
        "adjudication_note",
        "owner_adjudicated",
        "adjudicated_by",
        "adjudicated_date",
    )
    payload = [
        {key: record[key] for key in fields if key in record}
        for record in sorted(records, key=lambda item: item["id"])
    ]
    return _canonical_hash("glassgraph:benchmark-judgments:v1", payload)


def corpus_snapshot_hash(corpus_root: str | Path) -> str:
    """Return the frozen hash of all Markdown bytes below one corpus root."""
    root = Path(corpus_root)
    documents = [
        {
            "path": path.relative_to(root).as_posix(),
            "sha256": "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest(),
        }
        for path in sorted(root.rglob("*.md"))
    ]
    return _canonical_hash("glassgraph:benchmark-corpus:v1", documents)


def _passages(groups: list[list[dict]]) -> list[dict]:
    passages = [passage for group in groups for passage in group]
    if any(not passage.get("evidence_id") for passage in passages):
        raise ValueError("Every positive evidence judgment needs an evidence_id")
    return passages


def _matches(hit: dict, passage: dict, passages: list[dict]) -> bool:
    explicit = hit.get("evidence_id")
    if explicit is not None:
        return str(explicit) == passage["evidence_id"]
    passage_text = passage.get("text")
    if (
        hit.get("path") != passage.get("path")
        or not isinstance(passage_text, str)
        or not passage_text
        or passage_text not in str(hit.get("text") or "")
    ):
        return False
    identical_locations = {
        candidate["evidence_id"]
        for candidate in passages
        if candidate.get("path") == passage.get("path")
        and candidate.get("text") == passage_text
    }
    return len(identical_locations) == 1


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))


def _ranked_group_matches(groups: list[list[dict]], hits: list[dict]):
    grade_value = {"direct": 2, "supporting": 1}
    passages = _passages(groups)
    unused = set(range(len(groups)))
    for hit in hits:
        matching = [
            (
                max(
                    grade_value[passage["grade"]]
                    for passage in groups[index]
                    if _matches(hit, passage, passages)
                ),
                index,
            )
            for index in unused
            if any(_matches(hit, passage, passages) for passage in groups[index])
        ]
        if not matching:
            yield 0, None
            continue
        grade, index = max(matching, key=lambda item: (item[0], -item[1]))
        unused.remove(index)
        yield grade, index


def _ndcg_at_10(groups: list[list[dict]], hits: list[dict]) -> float:
    grade_value = {"direct": 2, "supporting": 1}
    ranked_grades = [grade for grade, _index in _ranked_group_matches(groups, hits[:10])]

    ideal = sorted(
        (max(grade_value[passage["grade"]] for passage in group) for group in groups),
        reverse=True,
    )[:10]
    ideal_dcg = _dcg(ideal)
    return _dcg(ranked_grades) / ideal_dcg if ideal_dcg else 0.0


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _has_explanation(hit: dict) -> bool:
    explanation = hit.get("explanation")
    if not isinstance(explanation, dict):
        return False
    return bool(explanation.get("value"))


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
            sum(_has_explanation(hit) for hit in raw_hits[:5])
        )
        groups = query.get("required_groups", [])
        if not groups:
            negative_queries += 1
            if raw_hits[:5]:
                negative_raw_false_positives += 1
            if accepted_hits[:5]:
                negative_false_positives += 1
            continue
        passages = _passages(groups)
        for limit, recalls in ((5, recalls_at_5), (10, recalls_at_10)):
            satisfied = sum(
                any(
                    _matches(hit, passage, passages)
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
        for _grade, matching_group in _ranked_group_matches(groups, raw_hits[:10]):
            if matching_group is not None:
                exact_evidence_hits += 1

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
