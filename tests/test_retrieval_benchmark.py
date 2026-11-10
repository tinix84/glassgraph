"""Behavior tests for the retrieval benchmark metric interface."""
from __future__ import annotations

import pytest


def test_evaluate_counts_interchangeable_passages_once(retrieval_benchmark_mod):
    queries = [
        {
            "id": "q1",
            "required_groups": [
                [
                    {"evidence_id": "e-a", "path": "a.md", "text": "Direct passage A", "grade": "direct"},
                    {"evidence_id": "e-b", "path": "b.md", "text": "Direct passage B", "grade": "direct"},
                ],
                [
                    {"evidence_id": "e-c", "path": "c.md", "text": "Supporting passage", "grade": "supporting"},
                ],
            ],
        }
    ]
    runs = {
        "q1": {
            "hits": [
                {"path": "b.md", "text": "Direct passage B"},
                {"path": "c.md", "text": "Supporting passage"},
            ]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["positive_queries"] == 1
    assert report["group_recall_at_5"] == 1.0


def test_evaluate_uses_graded_relevance_for_ndcg_at_10(retrieval_benchmark_mod):
    queries = [
        {
            "id": "q1",
            "required_groups": [
                [{"evidence_id": "e-direct", "path": "direct.md", "text": "Direct", "grade": "direct"}],
                [{"evidence_id": "e-support", "path": "support.md", "text": "Supporting", "grade": "supporting"}],
            ],
        }
    ]
    runs = {
        "q1": {
            "hits": [
                {"path": "support.md", "text": "Supporting"},
                {"path": "direct.md", "text": "Direct"},
            ]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["ndcg_at_10"] == pytest.approx(0.79670758)


def test_evaluate_reports_negative_false_positive_rate_at_5(retrieval_benchmark_mod):
    queries = [
        {"id": "n1", "required_groups": []},
        {"id": "n2", "required_groups": []},
    ]
    runs = {
        "n1": {"hits": [{"path": "distractor.md", "text": "Not an answer"}]},
        "n2": {"hits": []},
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["negative_queries"] == 2
    assert report["negative_false_positive_rate_at_5"] == 0.5


def test_evaluate_reports_latency_percentiles_and_peak_working_set(retrieval_benchmark_mod):
    queries = [{"id": f"n{index}", "required_groups": []} for index in range(1, 5)]
    runs = {
        "n1": {"hits": [], "latency_ms": 10.0, "peak_working_set_bytes": 100},
        "n2": {"hits": [], "latency_ms": 20.0, "peak_working_set_bytes": 200},
        "n3": {"hits": [], "latency_ms": 30.0, "peak_working_set_bytes": 300},
        "n4": {"hits": [], "latency_ms": 40.0, "peak_working_set_bytes": 400},
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["latency_ms_p50"] == 25.0
    assert report["latency_ms_p95"] == 40.0
    assert report["peak_working_set_bytes"] == 400


def test_evaluate_reports_group_recall_at_10_and_mrr(retrieval_benchmark_mod):
    queries = [
        {
            "id": "q1",
            "required_groups": [
                [{"evidence_id": "e-answer", "path": "answer.md", "text": "Answer", "grade": "direct"}],
            ],
        }
    ]
    distractors = [
        {"path": f"distractor-{index}.md", "text": "Not the answer"}
        for index in range(1, 6)
    ]
    runs = {
        "q1": {
            "hits": distractors + [{"path": "answer.md", "text": "Answer"}],
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["group_recall_at_5"] == 0.0
    assert report["group_recall_at_10"] == 1.0
    assert report["mrr"] == pytest.approx(1 / 6)


def test_evaluate_reports_exact_evidence_span_accuracy(retrieval_benchmark_mod):
    queries = [
        {
            "id": "q1",
            "required_groups": [
                [{"evidence_id": "e-answer", "path": "answer.md", "text": "Exact passage", "grade": "direct"}],
            ],
        }
    ]
    runs = {
        "q1": {
            "hits": [
                {"path": "answer.md", "text": "Wrong passage from the correct file"},
                {"path": "answer.md", "text": "Exact passage"},
            ]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["evidence_span_accuracy"] == 0.5


def test_evaluate_reports_context_and_explanation_density(retrieval_benchmark_mod):
    queries = [
        {"id": "n1", "required_groups": []},
        {"id": "n2", "required_groups": []},
    ]
    runs = {
        "n1": {
            "hits": [
                {"path": "a.md", "text": "A", "context_tokens": 10, "explanation": {"kind": "span", "value": [1]}},
                {"path": "b.md", "text": "B", "context_tokens": 20, "explanation": None},
            ]
        },
        "n2": {
            "hits": [
                {"path": "c.md", "text": "C", "context_tokens": 30, "explanation": {"kind": "score", "value": {"score": 1}}},
            ]
        },
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["mean_context_tokens_top_5"] == 30.0
    assert report["mean_explained_hits_top_5"] == 1.0


def test_evaluate_finds_exact_passage_inside_returned_chunk(retrieval_benchmark_mod):
    queries = [
        {
            "id": "q1",
            "required_groups": [
                [{"evidence_id": "e-answer", "path": "answer.md", "text": "Exact passage.", "grade": "direct"}],
            ],
        }
    ]
    runs = {
        "q1": {
            "hits": [
                {
                    "path": "answer.md",
                    "text": "Context before.\nExact passage.\nContext after.",
                }
            ]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["group_recall_at_5"] == 1.0
    assert report["evidence_span_accuracy"] == 1.0


def test_evaluate_separates_raw_negative_hits_from_explicit_abstention(
    retrieval_benchmark_mod,
):
    queries = [{"id": "n1", "required_groups": []}]
    raw_hit = {"path": "distractor.md", "text": "Not an answer"}
    runs = {
        "n1": {
            "raw_hits": [raw_hit],
            "hits": [],
            "abstained": True,
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["negative_raw_false_positive_rate_at_5"] == 1.0
    assert report["negative_false_positive_rate_at_5"] == 0.0


def test_evaluate_scores_positive_retrieval_before_confidence_abstention(
    retrieval_benchmark_mod,
):
    queries = [
        {
            "id": "q1",
            "required_groups": [
                [{"evidence_id": "e-answer", "path": "answer.md", "text": "Exact answer.", "grade": "direct"}]
            ],
        }
    ]
    raw_hit = {"path": "answer.md", "text": "Context. Exact answer. More context."}
    runs = {
        "q1": {
            "raw_hits": [raw_hit],
            "hits": [],
            "abstained": True,
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["group_recall_at_5"] == 1.0


def test_evaluate_mrr_uses_first_relevant_document_path(retrieval_benchmark_mod):
    queries = [
        {
            "id": "q1",
            "required_groups": [
                [{"evidence_id": "e-answer", "path": "answer.md", "text": "Exact answer.", "grade": "direct"}]
            ],
        }
    ]
    runs = {
        "q1": {
            "hits": [
                {"path": "answer.md", "text": "Wrong span in the relevant document"},
                {"path": "answer.md", "text": "Exact answer."},
            ]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["mrr"] == 1.0
    assert report["evidence_span_accuracy"] == 0.5


def test_evaluate_rejects_wrong_explicit_evidence_id(retrieval_benchmark_mod):
    queries = [
        {
            "id": "q1",
            "required_groups": [[{
                "evidence_id": "expected-id",
                "path": "answer.md",
                "text": "Repeated answer.",
                "grade": "direct",
            }]],
        }
    ]
    runs = {
        "q1": {
            "hits": [{
                "evidence_id": "different-id",
                "path": "answer.md",
                "text": "Repeated answer.",
            }]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["group_recall_at_5"] == 0.0
    assert report["evidence_span_accuracy"] == 0.0


def test_evaluate_rejects_ambiguous_unverified_duplicate_passage(
    retrieval_benchmark_mod,
):
    queries = [
        {
            "id": "q1",
            "required_groups": [[
                {
                    "evidence_id": "first-id",
                    "path": "answer.md",
                    "text": "Repeated answer.",
                    "grade": "direct",
                },
                {
                    "evidence_id": "second-id",
                    "path": "answer.md",
                    "text": "Repeated answer.",
                    "grade": "direct",
                },
            ]],
        }
    ]
    runs = {
        "q1": {"hits": [{"path": "answer.md", "text": "Repeated answer."}]}
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["group_recall_at_5"] == 0.0


def test_evaluate_counts_only_nonempty_explanation_traces(retrieval_benchmark_mod):
    queries = [{"id": "n1", "required_groups": []}]
    runs = {
        "n1": {
            "hits": [
                {"path": "a.md", "text": "A", "explanation": {"kind": "span", "value": []}},
                {"path": "b.md", "text": "B", "explanation": {"kind": "score", "value": None}},
                {"path": "c.md", "text": "C", "explanation": {"kind": "score", "value": {"score": 1}}},
            ]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["mean_explained_hits_top_5"] == 1.0
