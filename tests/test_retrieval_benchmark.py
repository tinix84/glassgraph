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
                {"evidence_ids": ["e-b"], "path": "b.md", "text": "Direct passage B"},
                {"evidence_ids": ["e-c"], "path": "c.md", "text": "Supporting passage"},
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
                {"evidence_ids": ["e-support"], "path": "support.md", "text": "Supporting"},
                {"evidence_ids": ["e-direct"], "path": "direct.md", "text": "Direct"},
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
            "hits": distractors + [{"evidence_ids": ["e-answer"], "path": "answer.md", "text": "Answer"}],
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
                {"evidence_ids": [], "path": "answer.md", "text": "Wrong passage from the correct file"},
                {"evidence_ids": ["e-answer"], "path": "answer.md", "text": "Exact passage"},
            ]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["evidence_span_accuracy"] == 0.5


def test_evaluate_reports_context_and_explanation_density(retrieval_benchmark_mod):
    queries = [
        {"id": "n1", "query": "Alpha", "required_groups": []},
        {"id": "n2", "query": "C", "required_groups": []},
    ]
    runs = {
        "n1": {
            "hits": [
                {"path": "a.md", "text": "Alpha", "context_tokens": 10, "explanation": {"kind": "match_spans", "value": [{"start": 0, "end": 5}]}},
                {"path": "b.md", "text": "B", "context_tokens": 20, "explanation": None},
            ]
        },
        "n2": {
            "hits": [
                {"path": "c.md", "text": "C", "context_tokens": 30, "explanation": {"kind": "qmd_explain", "value": {"blendedScore": 1}}},
            ]
        },
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["mean_context_tokens_top_5"] == 30.0
    assert report["mean_explained_hits_top_5"] == 1.0
    assert report["explanation_trace_availability_rate_top_5"] == pytest.approx(2 / 3)
    assert report["explanation_fidelity_rate_top_5"] == pytest.approx(1 / 3)


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
                    "evidence_ids": ["e-answer"],
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
    raw_hit = {
        "evidence_ids": ["e-answer"],
        "path": "answer.md",
        "text": "Context. Exact answer. More context.",
    }
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
                {"evidence_ids": [], "path": "answer.md", "text": "Wrong span in the relevant document"},
                {"evidence_ids": ["e-answer"], "path": "answer.md", "text": "Exact answer."},
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


def test_evaluate_rejects_unverified_singular_evidence_id(retrieval_benchmark_mod):
    queries = [{
        "id": "q1",
        "required_groups": [[{
            "evidence_id": "expected-id",
            "path": "answer.md",
            "text": "Exact answer.",
            "grade": "direct",
        }]],
    }]
    runs = {"q1": {"hits": [{
        "evidence_id": "expected-id",
        "path": "wrong.md",
        "text": "Unrelated text.",
    }]}}

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["group_recall_at_5"] == 0.0


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
    queries = [{"id": "n1", "query": "A", "required_groups": []}]
    runs = {
        "n1": {
            "hits": [
                {"path": "a.md", "text": "A", "explanation": {"kind": "span", "value": []}},
                {"path": "b.md", "text": "B", "explanation": {"kind": "score", "value": None}},
                {"path": "c.md", "text": "C", "explanation": {"kind": "qmd_explain", "value": {"blendedScore": 1}}},
                {"path": "d.md", "text": "D", "explanation": {"kind": "unrelated", "value": {"score": 1}}},
                {"path": "e.md", "text": "E", "explanation": {"kind": "match_spans", "value": [{"start": 99, "end": 100}]}},
                {"path": "f.md", "text": "F", "explanation": {"kind": "qmd_explain", "value": {"lex": []}}},
            ]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["mean_explained_hits_top_5"] == 1.0
    assert report["explanation_trace_availability_rate_top_5"] == 0.2
    assert report["explanation_fidelity_rate_top_5"] == 0.0


def test_evaluate_rejects_unrelated_match_span_as_faithful_explanation(
    retrieval_benchmark_mod,
):
    queries = [{"id": "n1", "query": "target", "required_groups": []}]
    runs = {
        "n1": {
            "hits": [{
                "path": "a.md",
                "text": "unrelated",
                "explanation": {
                    "kind": "match_spans",
                    "value": [{"start": 0, "end": 1}],
                },
            }]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["explanation_trace_availability_rate_top_5"] == 1.0
    assert report["explanation_fidelity_rate_top_5"] == 0.0


def test_evaluate_rejects_one_character_overlap_as_faithful_explanation(
    retrieval_benchmark_mod,
):
    queries = [{"id": "n1", "query": "target", "required_groups": []}]
    runs = {
        "n1": {
            "hits": [{
                "path": "a.md",
                "text": "unrelated",
                "explanation": {
                    "kind": "match_spans",
                    "value": [{"start": 5, "end": 6}],
                },
            }]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["explanation_trace_availability_rate_top_5"] == 1.0
    assert report["explanation_fidelity_rate_top_5"] == 0.0


def test_evaluate_rejects_single_letter_article_as_faithful_explanation(
    retrieval_benchmark_mod,
):
    queries = [{"id": "n1", "query": "A target", "required_groups": []}]
    runs = {
        "n1": {
            "hits": [{
                "path": "a.md",
                "text": "UNRELATED",
                "explanation": {
                    "kind": "match_spans",
                    "value": [{"start": 5, "end": 6}],
                },
            }]
        }
    }

    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert report["explanation_fidelity_rate_top_5"] == 0.0


def test_verify_evidence_hits_rejects_unjudged_duplicate_occurrence(
    tmp_path, retrieval_benchmark_mod
):
    document = tmp_path / "answer.md"
    document.write_text(
        "# First\n\nRepeated answer.\n\n# Second\n\nRepeated answer.\n",
        encoding="utf-8",
    )
    queries = [
        {
            "id": "q1",
            "required_groups": [[{
                "evidence_id": "first-id",
                "path": "answer.md",
                "text": "Repeated answer.",
                "grade": "direct",
            }]],
        }
    ]
    runs = {"q1": {"hits": [{"path": "answer.md", "text": "Repeated answer."}]}}

    retrieval_benchmark_mod.verify_evidence_hits(queries, runs, tmp_path)
    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert runs["q1"]["hits"][0]["evidence_ids"] == []
    assert report["group_recall_at_5"] == 0.0


def test_verify_evidence_hits_certifies_unique_source_occurrence(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text("Unique answer.\n", encoding="utf-8")
    judgment = {
        "path": "answer.md",
        "text": "Unique answer.",
        "grade": "direct",
    }
    judgment["evidence_id"] = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path, judgment
    )[0]["evidence_id"]
    queries = [
        {
            "id": "q1",
            "required_groups": [[judgment]],
        }
    ]
    runs = {"q1": {"hits": [{"path": "answer.md", "text": "Unique answer."}]}}

    retrieval_benchmark_mod.verify_evidence_hits(queries, runs, tmp_path)
    report = retrieval_benchmark_mod.evaluate(queries, runs)

    assert runs["q1"]["hits"][0]["evidence_ids"] == [judgment["evidence_id"]]
    assert report["group_recall_at_5"] == 1.0


def test_validate_evidence_judgments_rejects_wrong_adr_0013_id(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text("# Answer\n\nUnique answer.\n", encoding="utf-8")
    queries = [{
        "id": "q1",
        "required_groups": [[{
            "evidence_id": "sha256:" + "0" * 64,
            "path": "answer.md",
            "heading": "Answer",
            "text": "Unique answer.",
            "grade": "direct",
        }]],
    }]

    with pytest.raises(ValueError, match="evidence identity"):
        retrieval_benchmark_mod.validate_evidence_judgments(queries, tmp_path)


def test_benchmark_version_changes_with_judgment_correction(retrieval_benchmark_mod):
    original = [{"id": "q1", "required_groups": []}]
    corrected = [{
        "id": "q1",
        "required_groups": [],
        "irrelevant": [{"evidence_id": "sha256:" + "1" * 64}],
    }]

    original_version = retrieval_benchmark_mod.benchmark_version("public", original)
    corrected_version = retrieval_benchmark_mod.benchmark_version("public", corrected)

    assert original_version.startswith("public-v1-")
    assert corrected_version.startswith("public-v1-")
    assert corrected_version != original_version


@pytest.mark.parametrize(
    "change",
    [
        {"query": "Changed query"},
        {"split": "evaluation"},
    ],
)
def test_benchmark_version_changes_with_query_or_split_identity(
    retrieval_benchmark_mod, change
):
    original = [{
        "id": "q1",
        "query": "Original query",
        "split": "development",
        "required_groups": [],
    }]
    changed = [{**original[0], **change}]

    assert retrieval_benchmark_mod.benchmark_version(
        "private", original
    ) != retrieval_benchmark_mod.benchmark_version("private", changed)


def test_backend_settings_lock_changes_with_retrieval_cutoff(retrieval_benchmark_mod):
    settings = {
        "backend": "grooveseek",
        "limit": 10,
        "path_prefix": "wiki",
        "executable": "groove",
        "knowledge_base": "corpus",
    }

    original = retrieval_benchmark_mod.backend_settings_lock(settings)
    changed = retrieval_benchmark_mod.backend_settings_lock({**settings, "limit": 11})

    assert original.startswith("sha256:")
    assert changed != original


def test_verify_evidence_hits_uses_line_locator_for_repeated_passage(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text(
        "# First\n\nRepeated answer.\n\n# Second\n\nRepeated answer.\n",
        encoding="utf-8",
    )
    judgment = {
        "path": "answer.md",
        "heading": "Second",
        "text": "Repeated answer.",
        "grade": "direct",
    }
    records = retrieval_benchmark_mod.derive_evidence_records(tmp_path, judgment)
    judgment["evidence_id"] = records[1]["evidence_id"]
    queries = [{"id": "q1", "required_groups": [[judgment]]}]
    runs = {
        "q1": {
            "hits": [{
                "path": "answer.md",
                "text": "Repeated answer.",
                "backend_locator": {"kind": "heuristic_line", "line": 7},
            }]
        }
    }

    retrieval_benchmark_mod.verify_evidence_hits(queries, runs, tmp_path)

    assert runs["q1"]["hits"][0]["evidence_ids"] == [judgment["evidence_id"]]


def test_derive_evidence_uses_first_line_heading_instead_of_root(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text(
        "# Answer\n\nUnique answer.\n", encoding="utf-8"
    )

    records = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "Unique answer."},
    )

    assert records[0]["heading"] == "Answer"
    assert records[0]["heading_path"] == ["Answer"]


def test_derive_evidence_rejects_passage_crossing_heading_boundary(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text(
        "## First\n\nAnswer one.\n\n## Second\n\nAnswer two.\n",
        encoding="utf-8",
    )

    records = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {
            "path": "answer.md",
            "text": "Answer one.\n\n## Second\n\nAnswer two.",
        },
    )

    assert records == []


def test_derive_evidence_returns_original_utf8_byte_span(
    tmp_path, retrieval_benchmark_mod
):
    source = "# Résultats\r\n\r\nCafe\u0301.\r\n".encode("utf-8")
    (tmp_path / "answer.md").write_bytes(source)
    passage = "Cafe\u0301.\r\n".encode("utf-8")

    records = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "Café."},
    )

    assert records[0]["utf8_byte_start"] == source.index(passage)
    assert records[0]["utf8_byte_end"] == source.index(passage) + len(passage)


def test_derive_evidence_byte_span_covers_reordered_combining_sequence(
    tmp_path, retrieval_benchmark_mod
):
    combining_sequence = "a\u0315\u0300"
    source = f"{combining_sequence}x\n".encode("utf-8")
    (tmp_path / "answer.md").write_bytes(source)

    records = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "à"},
    )

    assert records[0]["utf8_byte_start"] == 0
    assert records[0]["utf8_byte_end"] == len(combining_sequence.encode("utf-8"))


def test_derive_evidence_counts_overlapping_identical_passages(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_bytes(b"# Result\n\naaaa")

    records = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "aaa"},
    )

    assert [record["utf8_byte_start"] for record in records] == [10, 11]
    assert [record["utf8_byte_end"] for record in records] == [13, 14]
    assert len({record["evidence_id"] for record in records}) == 2


@pytest.mark.parametrize("unsafe_path", ["D:wiki/example.md", "./D:/wiki/example.md"])
def test_derive_evidence_rejects_drive_relative_paths(
    tmp_path, retrieval_benchmark_mod, unsafe_path
):
    with pytest.raises(ValueError, match="outside the corpus"):
        retrieval_benchmark_mod.derive_evidence_records(
            tmp_path,
            {"path": unsafe_path, "text": "Evidence"},
        )


def test_derive_evidence_ignores_frontmatter_and_fenced_code_headings(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text(
        "---\n# YAML comment\ntitle: Example\n---\n\n"
        "# Real Heading\n\n```sh\n# shell comment\n```\n\nEvidence.\n",
        encoding="utf-8",
    )

    frontmatter = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "title: Example"},
    )
    body = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "Evidence."},
    )

    assert frontmatter[0]["heading_path"] == []
    assert body[0]["heading_path"] == ["Real Heading"]


def test_derive_evidence_uses_shared_bom_safe_frontmatter_boundary(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_bytes(
        "\ufeff---\n# YAML comment\ntitle: Example\n---\n\n# Real\nEvidence.\n".encode(
            "utf-8"
        )
    )

    frontmatter_record = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "title: Example"},
    )
    body_record = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "Evidence."},
    )

    assert frontmatter_record[0]["heading_path"] == []
    assert body_record[0]["heading_path"] == ["Real"]


def test_derive_evidence_does_not_open_invalid_backtick_fence(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text(
        "```bad`\n# Real\nEvidence.\n",
        encoding="utf-8",
    )

    records = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "Evidence."},
    )

    assert records[0]["heading_path"] == ["Real"]


@pytest.mark.parametrize(
    "document",
    [
        "<!--\n# Fake\n-->\nEvidence.\n",
        "<div>\n# Fake\n</div>\n\nEvidence.\n",
        "<custom-element>\n# Fake\n</custom-element>\n\nEvidence.\n",
    ],
)
def test_derive_evidence_ignores_headings_inside_html_blocks(
    tmp_path, retrieval_benchmark_mod, document
):
    (tmp_path / "answer.md").write_text(document, encoding="utf-8")

    records = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "Evidence."},
    )

    assert records[0]["heading_path"] == []


def test_derive_evidence_normalizes_empty_and_closed_atx_headings(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text(
        "##\nEmpty heading evidence.\n\n## Results ##\nClosed heading evidence.\n",
        encoding="utf-8",
    )

    empty = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "Empty heading evidence."},
    )
    closed = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path,
        {"path": "answer.md", "text": "Closed heading evidence."},
    )

    assert empty[0]["heading_path"] == [""]
    assert closed[0]["heading_path"] == ["Results"]


def test_verify_evidence_rejects_longer_line_with_judged_prefix(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text(
        "# Ratings\n\nRated 12 V\n\nRated 12 V was rejected.\n",
        encoding="utf-8",
    )
    judgment = {
        "path": "answer.md",
        "heading": "Ratings",
        "text": "Rated 12 V",
        "grade": "direct",
    }
    judgment["evidence_id"] = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path, judgment
    )[0]["evidence_id"]
    queries = [{"id": "q1", "required_groups": [[judgment]]}]
    runs = {"q1": {"hits": [{
        "path": "answer.md",
        "text": "Rated 12 V was rejected.",
        "backend_locator": {"kind": "heuristic_line", "line": 5},
    }]}}

    retrieval_benchmark_mod.verify_evidence_hits(queries, runs, tmp_path)

    assert runs["q1"]["hits"][0]["evidence_ids"] == []


def test_verify_evidence_normalizes_decomposed_backend_text(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text(
        "# Result\n\nCafé unit.\n", encoding="utf-8"
    )
    judgment = {
        "path": "answer.md",
        "heading": "Result",
        "text": "Café unit.",
        "grade": "direct",
    }
    judgment["evidence_id"] = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path, judgment
    )[0]["evidence_id"]
    queries = [{"id": "q1", "required_groups": [[judgment]]}]
    runs = {"q1": {"hits": [{
        "path": "answer.md",
        "text": "Cafe\u0301 unit.",
    }]}}

    retrieval_benchmark_mod.verify_evidence_hits(queries, runs, tmp_path)

    assert runs["q1"]["hits"][0]["evidence_ids"] == [judgment["evidence_id"]]


def test_verify_evidence_rejects_claimed_id_at_wrong_repeated_locator(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text(
        "# First\n\nRepeated.\n\n# Second\n\nRepeated.\n", encoding="utf-8"
    )
    judgment = {
        "path": "answer.md",
        "heading": "First",
        "text": "Repeated.",
        "grade": "direct",
    }
    judgment["evidence_id"] = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path, judgment
    )[0]["evidence_id"]
    queries = [{"id": "q1", "required_groups": [[judgment]]}]
    runs = {"q1": {"hits": [{
        "evidence_id": judgment["evidence_id"],
        "path": "answer.md",
        "text": "Repeated.",
        "backend_locator": {"kind": "heuristic_line", "line": 7},
    }]}}

    retrieval_benchmark_mod.verify_evidence_hits(queries, runs, tmp_path)

    assert runs["q1"]["hits"][0]["evidence_ids"] == []


def test_verify_evidence_rejects_ambiguous_same_line_occurrences(
    tmp_path, retrieval_benchmark_mod
):
    (tmp_path / "answer.md").write_text(
        "# Result\n\nRepeated. Repeated.\n", encoding="utf-8"
    )
    judgment = {
        "path": "answer.md",
        "heading": "Result",
        "text": "Repeated.",
        "grade": "direct",
    }
    judgment["evidence_id"] = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path, judgment
    )[0]["evidence_id"]
    queries = [{"id": "q1", "required_groups": [[judgment]]}]
    runs = {"q1": {"hits": [{
        "path": "answer.md",
        "text": "Repeated.",
        "backend_locator": {"kind": "heuristic_line", "line": 3},
    }]}}

    retrieval_benchmark_mod.verify_evidence_hits(queries, runs, tmp_path)

    assert runs["q1"]["hits"][0]["evidence_ids"] == []
