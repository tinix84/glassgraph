"""Behavior tests for topic-driven private search sessions."""
from __future__ import annotations

import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest


def test_session_requires_lock_before_holdout_and_stops_tuning_after_lock(
    search_lab_mod,
):
    brief = {
        "topic": "SiC traction inverters",
        "argument": "SiC adoption improves high-voltage traction systems.",
        "questions": [
            {"id": "development-1", "role": "development", "query": "Why SiC?"},
        ],
        "constraints": {"offline": True, "private": True},
    }
    session = search_lab_mod.new_session(brief)

    with pytest.raises(search_lab_mod.SearchLabError, match="lock settings"):
        search_lab_mod.record_holdout(session, {"question_id": "holdout-1"})

    search_lab_mod.record_iteration(
        session,
        {
            "question_id": "development-1",
            "prior_settings": {"backend": "grooveseek", "limit": 5},
            "change": {
                "field": "low_confidence_policy",
                "before": "hide",
                "after": "preserve",
            },
            "rationale": "The raw candidates contain exact reference evidence.",
            "aggregate_delta": {"raw_citation_coverage": 0.2},
        },
    )
    search_lab_mod.lock_settings(session, {"backend": "grooveseek", "limit": 5})
    search_lab_mod.record_holdout(
        session,
        {
            "brief": {
                "topic": "Untouched holdout topic",
                "questions": [
                    {"id": "holdout-1", "role": "holdout", "query": "What changed?"}
                ],
            },
            "runs": {"holdout-1": {"hits": []}},
        },
    )

    with pytest.raises(search_lab_mod.SearchLabError, match="settings are locked"):
        search_lab_mod.record_iteration(
            session,
            {
                "question_id": "development-1",
                "prior_settings": {"backend": "grooveseek", "limit": 5},
                "change": {"field": "limit", "before": 5, "after": 10},
                "rationale": "Test deeper retrieval.",
                "aggregate_delta": {"raw_citation_coverage": 0.0},
            },
        )

    assert session["state"] == "holdout"
    assert len(session["development_iterations"]) == 1
    assert len(session["holdout_runs"]) == 1


def test_tuning_iteration_requires_one_explicit_settings_change(search_lab_mod):
    session = search_lab_mod.new_session(
        {
            "topic": "SiC traction inverters",
            "argument": "SiC changes traction inverter performance.",
            "questions": [
                {"id": "development-1", "role": "development", "query": "Why?"},
            ],
            "constraints": {"offline": True, "private": True},
        }
    )

    with pytest.raises(search_lab_mod.SearchLabError, match="one settings change"):
        search_lab_mod.record_iteration(
            session,
            {
                "question_id": "development-1",
                "prior_settings": {"limit": 5},
                "change": [
                    {"field": "limit", "before": 5, "after": 10},
                    {"field": "threshold", "before": 0.2, "after": 0.1},
                ],
                "rationale": "Change two controls.",
                "aggregate_delta": {"citation_coverage": 0.1},
            },
        )


def test_development_session_does_not_require_or_expose_a_holdout_brief(
    search_lab_mod,
):
    session = search_lab_mod.new_session(
        {
            "topic": "SiC traction inverters",
            "argument": "SiC changes traction inverter performance.",
            "questions": [
                {"id": "development-1", "role": "development", "query": "Why?"}
            ],
            "constraints": {"offline": True, "private": True},
        }
    )

    assert "holdout_brief" not in session
    search_lab_mod.lock_settings(session, {"backend": "grooveseek", "limit": 5})
    search_lab_mod.record_holdout(
        session,
        {
            "brief": {
                "topic": "Untouched topic",
                "questions": [
                    {"id": "holdout-1", "role": "holdout", "query": "What changed?"}
                ],
            },
            "runs": {"holdout-1": {"hits": []}},
        },
    )

    assert session["holdout_runs"][0]["brief"]["topic"] == "Untouched topic"


def test_research_brief_accepts_a_topic_without_an_argument(search_lab_mod):
    session = search_lab_mod.new_session(
        {
            "topic": "SiC traction inverters",
            "questions": [
                {"id": "development-1", "role": "development", "query": "Why?"}
            ],
            "constraints": {"offline": True, "private": True},
        }
    )

    assert session["brief"]["topic"] == "SiC traction inverters"


def test_comparison_exposes_useful_raw_evidence_hidden_by_abstention(
    tmp_path, search_lab_mod
):
    (tmp_path / "evidence.md").write_text(
        "# Result\n\nThe 800 V architecture reduces current for the same power.\n",
        encoding="utf-8",
    )
    trial = {
        "id": "development-1",
        "role": "development",
        "query": "Why use an 800 V architecture?",
        "reference_citations": [
            {
                "path": "evidence.md",
                "heading": "Result",
                "text": "The 800 V architecture reduces current for the same power.",
                "grade": "direct",
            }
        ],
    }
    backend_run = {
        "hits": [],
        "raw_hits": [
            {
                "path": "evidence.md",
                "text": "The 800 V architecture reduces current for the same power.",
                "backend_score": {
                    "adapter": "grooveseek",
                    "kind": "rrf",
                    "raw": 0.0327,
                },
            }
        ],
        "abstained": True,
        "latency_ms": 12.5,
    }

    comparison = search_lab_mod.compare_trial(trial, backend_run, tmp_path)

    assert comparison["citation_coverage"] == {"accepted": 0.0, "raw": 1.0}
    assert comparison["missing_citations"] == {"accepted": [0], "raw": []}
    assert comparison["abstention_disagreement"] is True
    assert comparison["low_confidence"] is False
    assert comparison["raw_hits"][0]["backend_score"]["raw"] == 0.0327
    assert comparison["reference_citations"][0]["evidence_id"].startswith("sha256:")


def test_unverified_no_answer_trial_remains_unscored(tmp_path, search_lab_mod):
    trial = {
        "id": "development-negative",
        "role": "development",
        "kind": "no_answer",
        "query": "Which source proves an unsupported claim?",
        "reference_citations": [],
    }
    backend_run = {
        "hits": [],
        "raw_hits": [],
        "abstained": True,
        "latency_ms": 2.0,
    }

    comparison = search_lab_mod.compare_trial(trial, backend_run, tmp_path)

    assert comparison["scoring"] == {
        "eligible": False,
        "reason": "no-answer claim lacks owner acceptance or an exhaustive search",
    }
    assert comparison["citation_coverage"] == {"accepted": None, "raw": None}


def test_verified_no_answer_trial_flags_returned_hits_as_unsupported(
    tmp_path, search_lab_mod
):
    trial = {
        "id": "development-negative-verified",
        "role": "development",
        "kind": "no_answer",
        "query": "Which source proves an unsupported claim?",
        "reference_citations": [],
        "owner_accepted": True,
    }
    hit = {"path": "noise.md", "text": "Unrelated result."}

    comparison = search_lab_mod.compare_trial(
        trial,
        {"hits": [hit], "raw_hits": [hit], "abstained": False},
        tmp_path,
    )

    assert comparison["unsupported_answer_disagreement"] is True


def test_answerable_trial_requires_at_least_one_reference_citation(
    tmp_path, search_lab_mod
):
    trial = {
        "id": "development-empty-positive",
        "role": "development",
        "query": "What supports this claim?",
        "reference_citations": [],
    }

    with pytest.raises(search_lab_mod.SearchLabError, match="reference citation"):
        search_lab_mod.compare_trial(
            trial,
            {"hits": [], "raw_hits": [], "abstained": True},
            tmp_path,
        )


def test_comparison_reports_noise_rank_and_context_disagreements(
    tmp_path, search_lab_mod
):
    (tmp_path / "evidence.md").write_text(
        "# Result\n\nFirst citation.\n\nSecond citation.\n",
        encoding="utf-8",
    )
    trial = {
        "id": "development-ranking",
        "role": "development",
        "query": "Compare the evidence.",
        "reference_citations": [
            {
                "path": "evidence.md",
                "heading": "Result",
                "text": "First citation.",
                "grade": "direct",
            },
            {
                "path": "evidence.md",
                "heading": "Result",
                "text": "Second citation.",
                "grade": "supporting",
            },
        ],
    }
    hits = [
        {"path": "noise.md", "text": "Unrelated result.", "context_tokens": 4},
        {"path": "evidence.md", "text": "Second citation.", "context_tokens": 5},
        {"path": "evidence.md", "text": "First citation.", "context_tokens": 6},
    ]

    comparison = search_lab_mod.compare_trial(
        trial,
        {"hits": hits, "raw_hits": hits, "abstained": False, "latency_ms": 3.0},
        tmp_path,
    )

    assert comparison["citation_ranks"] == [
        {"citation": 0, "accepted": 3, "raw": 3},
        {"citation": 1, "accepted": 2, "raw": 2},
    ]
    assert comparison["ranking_disagreement"] is True
    assert comparison["noisy_hit_ranks"] == {"accepted": [1], "raw": [1]}
    assert comparison["context_tokens"] == {"accepted": 15, "raw": 15}


def test_document_coverage_does_not_require_the_exact_passage_chunk(
    tmp_path, search_lab_mod
):
    (tmp_path / "evidence.md").write_text(
        "# Result\n\nExact passage.\n\nRelated paragraph from the same page.\n",
        encoding="utf-8",
    )
    trial = {
        "id": "development-document",
        "role": "development",
        "query": "Find the related evidence.",
        "reference_citations": [
            {
                "path": "evidence.md",
                "heading": "Result",
                "text": "Exact passage.",
                "grade": "direct",
            }
        ],
    }
    hit = {
        "path": "evidence.md",
        "text": "Related paragraph from the same page.",
        "context_tokens": 6,
    }

    comparison = search_lab_mod.compare_trial(
        trial,
        {"hits": [hit], "raw_hits": [hit], "abstained": False},
        tmp_path,
    )

    assert comparison["citation_coverage"] == {"accepted": 0.0, "raw": 0.0}
    assert comparison["document_coverage"] == {"accepted": 1.0, "raw": 1.0}
    assert comparison["noisy_hit_ranks"] == {"accepted": [], "raw": []}


def test_document_coverage_counts_unique_cited_documents(tmp_path, search_lab_mod):
    (tmp_path / "a.md").write_text("# A\n\nFirst.\n\nSecond.\n", encoding="utf-8")
    (tmp_path / "b.md").write_text("# B\n\nThird.\n", encoding="utf-8")
    trial = {
        "id": "development-documents",
        "role": "development",
        "query": "Find documents.",
        "reference_citations": [
            {"path": "a.md", "heading": "A", "text": "First.", "grade": "direct"},
            {"path": "a.md", "heading": "A", "text": "Second.", "grade": "direct"},
            {"path": "b.md", "heading": "B", "text": "Third.", "grade": "direct"},
        ],
    }
    hit = {"path": "a.md", "text": "First. Second."}

    comparison = search_lab_mod.compare_trial(
        trial, {"hits": [hit], "raw_hits": [hit], "abstained": False}, tmp_path
    )

    assert comparison["document_coverage"] == {"accepted": 0.5, "raw": 0.5}


def test_reference_citation_must_match_its_declared_heading(tmp_path, search_lab_mod):
    (tmp_path / "evidence.md").write_text(
        "# Actual\n\nExact passage.\n",
        encoding="utf-8",
    )
    trial = {
        "id": "development-heading",
        "role": "development",
        "query": "Find it.",
        "reference_citations": [
            {
                "path": "evidence.md",
                "heading": "Missing",
                "text": "Exact passage.",
                "grade": "direct",
            }
        ],
    }

    with pytest.raises(search_lab_mod.SearchLabError, match="resolve exactly once"):
        search_lab_mod.compare_trial(
            trial,
            {"hits": [], "raw_hits": [], "abstained": True},
            tmp_path,
        )


def test_reference_without_heading_uses_resolved_heading_for_hit_matching(
    tmp_path, search_lab_mod
):
    (tmp_path / "evidence.md").write_text(
        "# Actual\n\nExact passage.\n",
        encoding="utf-8",
    )
    trial = {
        "id": "development-resolved-heading",
        "role": "development",
        "query": "Find it.",
        "reference_citations": [
            {"path": "evidence.md", "text": "Exact passage.", "grade": "direct"}
        ],
    }
    hit = {"path": "evidence.md", "heading": "Actual", "text": "Exact passage."}

    comparison = search_lab_mod.compare_trial(
        trial, {"hits": [hit], "raw_hits": [hit], "abstained": False}, tmp_path
    )

    assert comparison["citation_coverage"]["accepted"] == 1.0


def test_adapter_settings_hash_qmd_index_content(tmp_path, search_lab_mod):
    index = tmp_path / "index.sqlite"
    with sqlite3.connect(index) as connection:
        connection.execute("CREATE TABLE records (value TEXT)")
        connection.execute("INSERT INTO records VALUES ('first')")

    class Adapter:
        index_db = str(index)

    first = search_lab_mod._adapter_settings(Adapter(), 5)
    with sqlite3.connect(index) as connection:
        connection.execute("INSERT INTO records VALUES ('second')")
    second = search_lab_mod._adapter_settings(Adapter(), 5)

    assert first["index_db_sha256"] != second["index_db_sha256"]


def test_adapter_settings_hash_path_resolved_executable(monkeypatch, search_lab_mod):
    executable = Path(sys.executable)
    monkeypatch.setenv("PATH", str(executable.parent))

    class Adapter:
        pass

    Adapter.executable = executable.name

    settings = search_lab_mod._adapter_settings(Adapter(), 5)

    assert settings["executable_sha256"].startswith("sha256:")


def test_adapter_settings_hash_qmd_package_content(tmp_path, search_lab_mod):
    package = tmp_path / "qmd"
    package.mkdir()
    (package / "package.json").write_text('{"name":"qmd"}', encoding="utf-8")
    script = package / "cli.js"
    script.write_text("first", encoding="utf-8")

    class Adapter:
        qmd_script = str(script)

    first = search_lab_mod._adapter_settings(Adapter(), 5)
    script.write_text("second", encoding="utf-8")
    second = search_lab_mod._adapter_settings(Adapter(), 5)

    assert first["qmd_script_sha256"] != second["qmd_script_sha256"]


def test_adapter_settings_refuse_unfingerprinted_executable(search_lab_mod):
    class Adapter:
        executable = "glassgraph-missing-executable"

    with pytest.raises(search_lab_mod.SearchLabError, match="fingerprint executable"):
        search_lab_mod._adapter_settings(Adapter(), 5)


def test_same_trials_run_through_each_retrieval_adapter(search_lab_mod):
    calls = []

    class Adapter:
        def __init__(self, name):
            self.name = name

        def query(self, query, *, limit):
            calls.append((self.name, query, limit))
            return {"hits": [], "raw_hits": [], "abstained": True}

    brief = {
        "topic": "Adapter comparison",
        "argument": "Both adapters must receive the same questions.",
        "questions": [
            {"id": "development-1", "role": "development", "query": "First question?"},
            {"id": "development-2", "role": "development", "query": "Second question?"},
        ],
        "constraints": {"offline": True, "private": True},
    }
    session = search_lab_mod.new_session(brief)

    runs = search_lab_mod.run_trials(
        session,
        brief,
        {"grooveseek": Adapter("grooveseek"), "qmd": Adapter("qmd")},
        limit=5,
    )

    assert calls == [
        ("grooveseek", "First question?", 5),
        ("grooveseek", "Second question?", 5),
        ("qmd", "First question?", 5),
        ("qmd", "Second question?", 5),
    ]
    assert set(runs) == {"grooveseek", "qmd"}
    assert runs["grooveseek"]["settings"] == {"limit": 5}
    assert set(runs["grooveseek"]["trials"]) == {
        "development-1",
        "development-2",
    }
    first = runs["grooveseek"]["trials"]["development-1"]
    assert first["request"]["schema_version"] == "glassgraph.query.v1"
    assert first["request"]["operation"] == "search"
    assert first["response"]["schema_version"] == "glassgraph.query-result.v1"
    assert first["response"]["request_hash"].startswith("sha256:")
    assert first["response"]["execution"]["adapter"]["name"] == "grooveseek"
    assert "run" not in first


def test_query_contract_preserves_raw_low_confidence_trace(search_lab_mod):
    hit = {
        "path": "wiki/example.md",
        "heading": "Example",
        "text": "Exact passage.",
        "backend_score": {"adapter": "grooveseek", "kind": "rrf", "raw": 0.2},
        "context_tokens": 3,
        "explanation": {"kind": "match_spans", "value": [{"start": 0, "end": 5}]},
        "backend_locator": {"kind": "utf8_match_spans", "value": []},
    }

    class Adapter:
        def query(self, query, *, limit):
            return {
                "hits": [],
                "raw_hits": [hit],
                "abstained": True,
                "low_confidence": True,
                "latency_ms": 4.5,
                "peak_working_set_bytes": 1024,
            }

    brief = {
        "topic": "Trace preservation",
        "questions": [
            {"id": "development-1", "role": "development", "query": "Why?"}
        ],
        "constraints": {"offline": True, "private": True},
    }
    runs = search_lab_mod.run_trials(
        search_lab_mod.new_session(brief),
        brief,
        {"grooveseek": Adapter()},
        limit=5,
    )

    exchange = runs["grooveseek"]["trials"]["development-1"]
    response = exchange["response"]
    assert response["status"] == "abstained"
    assert response["index"]["state"] == "unbound"
    assert response["results"] == []
    assert response["raw_results"][0]["score"]["backend"]["raw"] == 0.2
    assert response["raw_results"][0]["backend_trace"]["locator"] == hit[
        "backend_locator"
    ]

    changed_request = dict(exchange["request"], limit=10)
    with pytest.raises(ValueError, match="stored query exchange"):
        search_lab_mod.query_contract.backend_run(changed_request, response)


def test_query_contract_rejects_filters_the_adapter_cannot_enforce(search_lab_mod):
    class Adapter:
        def query(self, query, *, limit):
            raise AssertionError("The adapter must not run")

    request = search_lab_mod.query_contract.search_request("Why?", limit=5)
    request["filters"]["paths"] = ["allowed/**"]

    with pytest.raises(ValueError, match="filters are not supported"):
        search_lab_mod.query_contract.execute_search(
            "grooveseek", Adapter(), request, settings={"limit": 5}
        )


def test_stored_query_exchange_must_match_locked_backend_and_corpus(
    search_lab_mod, search_lab_cli_mod
):
    settings = {
        "limit": 5,
        "corpus_snapshot_hash": "sha256:corpus",
    }
    request = search_lab_mod.query_contract.search_request("Why?", limit=5)

    class Adapter:
        def query(self, query, *, limit):
            return {"hits": [], "raw_hits": [], "abstained": False}

    response = search_lab_mod.query_contract.execute_search(
        "grooveseek", Adapter(), request, settings=settings
    )
    payload = {
        "trials": {
            "holdout-1": {
                "role": "holdout",
                "request": request,
                "response": response,
            }
        }
    }
    trial = {"id": "holdout-1", "role": "holdout", "query": "Why?"}

    run = search_lab_cli_mod._trial_run(
        payload,
        trial,
        backend="grooveseek",
        locked_settings=settings,
    )
    assert run["hits"] == []

    response["execution"]["adapter"]["name"] = "qmd"
    with pytest.raises(ValueError, match="locked backend"):
        search_lab_cli_mod._trial_run(
            payload,
            trial,
            backend="grooveseek",
            locked_settings=settings,
        )

    response["execution"]["adapter"]["name"] = "grooveseek"
    response["index"]["corpus_snapshot_hash"] = "sha256:other"
    with pytest.raises(ValueError, match="locked backend"):
        search_lab_cli_mod._trial_run(
            payload,
            trial,
            backend="grooveseek",
            locked_settings=settings,
        )

    response["index"]["corpus_snapshot_hash"] = "sha256:corpus"
    response["execution"]["backend_snapshot_hash"] = "sha256:other"
    with pytest.raises(ValueError, match="locked backend"):
        search_lab_cli_mod._trial_run(
            payload,
            trial,
            backend="grooveseek",
            locked_settings=settings,
        )

    response["execution"]["backend_snapshot_hash"] = (
        search_lab_mod.query_contract.backend_snapshot_hash(settings)
    )
    request["limit"] = 2
    with pytest.raises(ValueError, match="locked backend"):
        search_lab_cli_mod._trial_run(
            payload,
            trial,
            backend="grooveseek",
            locked_settings=settings,
        )


def test_stored_query_exchange_rejects_error_and_legacy_results(
    search_lab_mod, search_lab_cli_mod
):
    settings = {"limit": 5, "corpus_snapshot_hash": "sha256:corpus"}
    request = search_lab_mod.query_contract.search_request("Why?", limit=5)

    class Adapter:
        def query(self, query, *, limit):
            return {"hits": [], "raw_hits": [], "abstained": False}

    response = search_lab_mod.query_contract.execute_search(
        "grooveseek", Adapter(), request, settings=settings
    )
    response["status"] = "error"
    trial = {"id": "holdout-1", "role": "holdout", "query": "Why?"}
    payload = {
        "trials": {
            "holdout-1": {
                "role": "holdout",
                "request": request,
                "response": response,
            }
        }
    }

    with pytest.raises(ValueError, match="stored query exchange"):
        search_lab_cli_mod._trial_run(
            payload,
            trial,
            backend="grooveseek",
            locked_settings=settings,
        )

    payload["trials"]["holdout-1"] = {
        "role": "holdout",
        "query": "Why?",
        "run": {"hits": [], "raw_hits": []},
    }
    with pytest.raises(ValueError, match="versioned query exchange"):
        search_lab_cli_mod._trial_run(
            payload,
            trial,
            backend="grooveseek",
            locked_settings=settings,
        )


def test_holdout_adapter_execution_refuses_to_run_before_settings_lock(search_lab_mod):
    development = {
        "topic": "Development",
        "argument": "Tune only on development questions.",
        "questions": [
            {"id": "development-1", "role": "development", "query": "Why?"}
        ],
        "constraints": {"offline": True, "private": True},
    }
    holdout = {
        "questions": [
            {"id": "holdout-1", "role": "holdout", "query": "Untouched?"}
        ]
    }

    with pytest.raises(search_lab_mod.SearchLabError, match="lock settings"):
        search_lab_mod.run_trials(
            search_lab_mod.new_session(development),
            holdout,
            {"grooveseek": object()},
            limit=5,
        )


def test_holdout_adapter_execution_must_match_locked_backend_and_limit(search_lab_mod):
    development = {
        "topic": "Development",
        "questions": [
            {"id": "development-1", "role": "development", "query": "Why?"}
        ],
        "constraints": {"offline": True, "private": True},
    }
    session = search_lab_mod.new_session(development)
    search_lab_mod.lock_settings(
        session, {"backends": {"grooveseek": {"limit": 5}}}
    )
    holdout = {
        "questions": [
            {"id": "holdout-1", "role": "holdout", "query": "Untouched?"}
        ]
    }

    with pytest.raises(search_lab_mod.SearchLabError, match="locked settings"):
        search_lab_mod.run_trials(
            session,
            holdout,
            {"grooveseek": object()},
            limit=10,
        )


def test_private_cli_writes_locked_offline_search_report(tmp_path, search_lab_cli_mod):
    workspace = tmp_path / ".glassgraph" / "benchmarks" / "private" / "v1"
    workspace.mkdir(parents=True)
    corpus = tmp_path / "wiki"
    corpus.mkdir()
    (corpus / "evidence.md").write_text(
        "# Result\n\nExact local evidence.\n",
        encoding="utf-8",
    )
    (tmp_path / ".gitignore").write_text(
        "/.glassgraph/benchmarks/private/\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    citation = {
        "path": "evidence.md",
        "heading": "Result",
        "text": "Exact local evidence.",
        "grade": "direct",
    }
    brief = {
        "topic": "Local evidence",
        "argument": "The local corpus contains the evidence.",
        "questions": [
            {
                "id": "development-1",
                "role": "development",
                "query": "What evidence exists?",
                "reference_citations": [citation],
            },
        ],
        "constraints": {"offline": True, "private": True},
    }
    holdout_brief = {
        "topic": "Untouched local evidence",
        "argument": "The holdout corpus contains the evidence.",
        "questions": [
            {
                "id": "holdout-1",
                "role": "holdout",
                "query": "Which local source supports it?",
                "reference_citations": [citation],
            }
        ],
        "constraints": {"offline": True, "private": True},
    }
    run = {
        "hits": [{"path": "evidence.md", "text": "Exact local evidence."}],
        "raw_hits": [{"path": "evidence.md", "text": "Exact local evidence."}],
        "abstained": False,
        "latency_ms": 1.0,
    }
    brief_path = workspace / "brief.json"
    holdout_brief_path = workspace / "holdout-brief.json"
    runs_path = workspace / "runs.json"
    tuning_path = workspace / "tuning.json"
    lock_path = workspace / "settings-lock.json"
    output_path = workspace / "report.json"
    brief_path.write_text(json.dumps(brief), encoding="utf-8")
    holdout_brief_path.write_text(json.dumps(holdout_brief), encoding="utf-8")
    corpus_hash = search_lab_cli_mod.retrieval_benchmark.corpus_snapshot_hash(corpus)
    settings = {"limit": 5, "corpus_snapshot_hash": corpus_hash}

    class Adapter:
        def query(self, query, *, limit):
            return run

    def backend_runs(backend):
        trials = {}
        for trial in brief["questions"] + holdout_brief["questions"]:
            request = search_lab_cli_mod.query_contract.search_request(
                trial["query"], limit=5
            )
            trials[trial["id"]] = {
                "role": trial["role"],
                "request": request,
                "response": search_lab_cli_mod.query_contract.execute_search(
                    backend, Adapter(), request, settings=settings
                ),
            }
        return {"settings": settings, "trials": trials}

    runs_path.write_text(
        json.dumps(
            {
                "grooveseek": backend_runs("grooveseek"),
                "qmd": backend_runs("qmd"),
            }
        ),
        encoding="utf-8",
    )
    tuning_path.write_text(
        json.dumps(
            {
                "iterations": [
                    {
                        "question_id": "development-1",
                        "prior_settings": {"limit": 4},
                        "change": {"field": "limit", "before": 4, "after": 5},
                        "rationale": "Improve document coverage.",
                        "aggregate_delta": {"document_coverage": 0.1},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    lock_path.write_text(
        json.dumps(
            {
                "backends": {
                    "grooveseek": {"limit": 5, "corpus_snapshot_hash": corpus_hash},
                    "qmd": {"limit": 5, "corpus_snapshot_hash": corpus_hash},
                },
                "corpus_snapshot_hash": corpus_hash,
            }
        ),
        encoding="utf-8",
    )

    result = search_lab_cli_mod.main(
        [
            "--brief",
            str(brief_path),
            "--holdout-brief",
            str(holdout_brief_path),
            "--runs",
            str(runs_path),
            "--tuning",
            str(tuning_path),
            "--corpus-root",
            str(corpus),
            "--settings-lock",
            str(lock_path),
            "--output",
            str(output_path),
            "--offline-verified",
        ]
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert result == 0
    assert report["privacy"] == "private"
    assert report["offline_verified"] is True
    assert report["session"]["state"] == "holdout"
    assert report["session"]["settings_lock"]["backends"]["grooveseek"]["limit"] == 5
    assert len(report["session"]["development_iterations"]) == 1
    assert {(item["backend"], item["role"]) for item in report["comparisons"]} == {
        ("grooveseek", "development"),
        ("grooveseek", "holdout"),
        ("qmd", "development"),
        ("qmd", "holdout"),
    }
