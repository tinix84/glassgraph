"""State and comparison rules for a topic-driven private search lab."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import retrieval_benchmark


class SearchLabError(ValueError):
    """Report an invalid search-lab action or artifact."""


def new_session(brief: dict) -> dict:
    """Create a development session from a research brief."""
    if not isinstance(brief, dict):
        raise SearchLabError("The research brief must be an object")
    if not any(
        isinstance(brief.get(field), str) and brief[field].strip()
        for field in ("topic", "argument")
    ):
        raise SearchLabError("The research brief needs a topic or an argument")
    questions = brief.get("questions")
    if not isinstance(questions, list) or not questions:
        raise SearchLabError("The research brief needs questions")
    roles = {question.get("role") for question in questions if isinstance(question, dict)}
    if roles != {"development"}:
        raise SearchLabError("The development brief can contain only development questions")
    constraints = brief.get("constraints")
    if not isinstance(constraints, dict) or constraints.get("offline") is not True:
        raise SearchLabError("The research brief must require offline operation")
    if constraints.get("private") is not True:
        raise SearchLabError("The research brief must require private operation")
    return {
        "brief": deepcopy(brief),
        "state": "development",
        "development_iterations": [],
        "settings_lock": None,
        "holdout_runs": [],
    }


def record_iteration(session: dict, iteration: dict) -> dict:
    """Record one development change before the settings lock."""
    if session.get("settings_lock") is not None:
        raise SearchLabError("The settings are locked. Tuning is not permitted")
    change = iteration.get("change") if isinstance(iteration, dict) else None
    if not isinstance(change, dict) or not {
        "field",
        "before",
        "after",
    }.issubset(change):
        raise SearchLabError("A tuning iteration must contain one settings change")
    if not isinstance(iteration.get("prior_settings"), dict):
        raise SearchLabError("A tuning iteration needs the prior settings")
    if not isinstance(iteration.get("rationale"), str) or not iteration["rationale"].strip():
        raise SearchLabError("A tuning iteration needs a rationale")
    if not isinstance(iteration.get("aggregate_delta"), dict):
        raise SearchLabError("A tuning iteration needs an aggregate delta")
    session["development_iterations"].append(deepcopy(iteration))
    return session


def lock_settings(session: dict, settings_lock: dict) -> dict:
    """Freeze the retrieval settings before a holdout run."""
    if session.get("settings_lock") is not None:
        raise SearchLabError("The settings are already locked")
    session["settings_lock"] = deepcopy(settings_lock)
    session["state"] = "locked"
    return session


def record_holdout(session: dict, run: dict) -> dict:
    """Record one holdout run after the settings lock."""
    if session.get("settings_lock") is None:
        raise SearchLabError("You must lock settings before a holdout run")
    brief = run.get("brief") if isinstance(run, dict) else None
    questions = brief.get("questions") if isinstance(brief, dict) else None
    if not isinstance(questions, list) or not questions or any(
        not isinstance(question, dict) or question.get("role") != "holdout"
        for question in questions
    ):
        raise SearchLabError("A holdout run needs a separate holdout brief")
    session["holdout_runs"].append(deepcopy(run))
    session["state"] = "holdout"
    return session


def _citation_is_in_hit(citation: dict, hit: dict) -> bool:
    hit_text = str(hit.get("text") or "")
    if hit.get("path") != citation["path"] or citation["text"] not in hit_text:
        return False
    if isinstance(hit.get("heading"), str) and (
        hit["heading"] != citation.get("heading")
    ):
        return False
    locator = hit.get("backend_locator")
    if isinstance(locator, dict) and locator.get("kind") == "heuristic_line":
        passage_offset = hit_text.index(citation["text"])
        passage_line = locator.get("line", 0) + hit_text.count("\n", 0, passage_offset)
        return citation["line_start"] <= passage_line <= citation["line_end"]
    return citation.get("document_occurrences") == 1


def _citation_document_is_in_hit(citation: dict, hit: dict) -> bool:
    return hit.get("path") == citation["path"]


def compare_trial(trial: dict, backend_run: dict, corpus_root) -> dict:
    """Compare exact reference citations with accepted and raw backend hits."""
    no_answer = trial.get("kind") == "no_answer"
    exhaustive_search = trial.get("exhaustive_search")
    no_answer_verified = trial.get("owner_accepted") is True or (
        isinstance(exhaustive_search, dict)
        and exhaustive_search.get("completed") is True
        and bool(exhaustive_search.get("method"))
        and bool(exhaustive_search.get("scope"))
    )
    reference_citations = trial.get("reference_citations")
    if not no_answer and (
        not isinstance(reference_citations, list) or not reference_citations
    ):
        raise SearchLabError("An answerable trial needs a reference citation")
    scoring_eligible = not no_answer or no_answer_verified
    scoring_reason = (
        "exact reference citations verified"
        if not no_answer
        else (
            "no-answer claim verified"
            if no_answer_verified
            else "no-answer claim lacks owner acceptance or an exhaustive search"
        )
    )
    citations = []
    for citation in reference_citations or []:
        derived = retrieval_benchmark.derive_evidence_records(corpus_root, citation)
        matching = [
            record
            for record in derived
            if record["evidence_id"]
            == citation.get("evidence_id", record["evidence_id"])
            and record["heading"] == citation.get("heading", record["heading"])
            and record["heading_path"]
            == citation.get("heading_path", record["heading_path"])
        ]
        if len(matching) != 1:
            raise SearchLabError("A reference citation must resolve exactly once")
        normalized = deepcopy(citation)
        normalized["evidence_id"] = matching[0]["evidence_id"]
        normalized["heading_path"] = matching[0]["heading_path"]
        normalized["line_start"] = matching[0]["line_start"]
        normalized["line_end"] = matching[0]["line_end"]
        normalized["document_occurrences"] = len(derived)
        citations.append(normalized)

    accepted_hits = deepcopy(backend_run.get("hits") or [])
    raw_hits = deepcopy(backend_run.get("raw_hits") or accepted_hits)

    def missing(hit_list: list[dict]) -> list[int]:
        return [
            index
            for index, citation in enumerate(citations)
            if not any(_citation_is_in_hit(citation, hit) for hit in hit_list)
        ]

    accepted_missing = missing(accepted_hits)
    raw_missing = missing(raw_hits)
    total = len(citations)
    cited_documents = {citation["path"] for citation in citations}

    def citation_rank(citation: dict, hit_list: list[dict]) -> int | None:
        for rank, hit in enumerate(hit_list, start=1):
            if _citation_is_in_hit(citation, hit):
                return rank
        return None

    citation_ranks = [
        {
            "citation": index,
            "accepted": citation_rank(citation, accepted_hits),
            "raw": citation_rank(citation, raw_hits),
        }
        for index, citation in enumerate(citations)
    ]

    def noisy_hit_ranks(hit_list: list[dict]) -> list[int]:
        return [
            rank
            for rank, hit in enumerate(hit_list, start=1)
            if not any(
                _citation_document_is_in_hit(citation, hit) for citation in citations
            )
        ]

    accepted_ranks = [item["accepted"] for item in citation_ranks]
    ranking_disagreement = any(rank is None for rank in accepted_ranks) or (
        accepted_ranks != sorted(accepted_ranks)
    )

    def coverage(missing_citations: list[int]) -> float | None:
        if no_answer and not scoring_eligible:
            return None
        return (total - len(missing_citations)) / total if total else 1.0

    def document_coverage(hit_list: list[dict]) -> float | None:
        if no_answer and not scoring_eligible:
            return None
        found = cited_documents.intersection(hit.get("path") for hit in hit_list)
        return len(found) / len(cited_documents) if cited_documents else 1.0

    return {
        "trial_id": trial.get("id"),
        "role": trial.get("role"),
        "query": trial.get("query"),
        "reference_citations": citations,
        "scoring": {"eligible": scoring_eligible, "reason": scoring_reason},
        "hits": accepted_hits,
        "raw_hits": raw_hits,
        "citation_coverage": {
            "accepted": coverage(accepted_missing),
            "raw": coverage(raw_missing),
        },
        "document_coverage": {
            "accepted": document_coverage(accepted_hits),
            "raw": document_coverage(raw_hits),
        },
        "missing_citations": {
            "accepted": accepted_missing,
            "raw": raw_missing,
        },
        "citation_ranks": citation_ranks,
        "ranking_disagreement": ranking_disagreement,
        "noisy_hit_ranks": {
            "accepted": noisy_hit_ranks(accepted_hits),
            "raw": noisy_hit_ranks(raw_hits),
        },
        "context_tokens": {
            "accepted": sum(int(hit.get("context_tokens") or 0) for hit in accepted_hits),
            "raw": sum(int(hit.get("context_tokens") or 0) for hit in raw_hits),
        },
        "abstained": backend_run.get("abstained") is True,
        "abstention_disagreement": (
            scoring_eligible
            and not no_answer
            and backend_run.get("abstained") is True
            and coverage(accepted_missing) < 1.0
        ),
        "unsupported_answer_disagreement": (
            no_answer and no_answer_verified and bool(accepted_hits)
        ),
        "latency_ms": backend_run.get("latency_ms"),
        "peak_working_set_bytes": backend_run.get("peak_working_set_bytes"),
    }


def run_trials(session: dict, brief: dict, adapters: dict, *, limit: int) -> dict:
    """Run the same ordered research questions through each adapter."""
    roles = {
        trial.get("role")
        for trial in brief.get("questions", [])
        if isinstance(trial, dict)
    }
    if "holdout" in roles and session.get("settings_lock") is None:
        raise SearchLabError("You must lock settings before holdout adapter execution")
    if "development" in roles and session.get("settings_lock") is not None:
        raise SearchLabError("The settings are locked. Development execution is not permitted")
    if "holdout" in roles:
        locked_backends = session["settings_lock"].get("backends")
        if not isinstance(locked_backends, dict) or any(
            backend not in locked_backends
            or locked_backends[backend] != _adapter_settings(adapter, limit)
            for backend, adapter in adapters.items()
        ):
            raise SearchLabError("Holdout execution does not match the locked settings")
    runs = {}
    for backend, adapter in adapters.items():
        backend_runs = {}
        for trial in brief.get("questions", []):
            backend_runs[trial["id"]] = {
                "query": trial["query"],
                "role": trial["role"],
                "run": adapter.query(trial["query"], limit=limit),
            }
        runs[backend] = {
            "settings": _adapter_settings(adapter, limit),
            "trials": backend_runs,
        }
    return runs


def _adapter_settings(adapter, limit: int) -> dict:
    settings = {"limit": limit}
    for name in (
        "config",
        "model",
        "low_confidence_policy",
        "path_prefix",
        "index",
        "collection",
        "embed_model",
        "index_db",
        "config_dir",
        "node_executable",
        "qmd_script",
        "executable",
    ):
        value = getattr(adapter, name, None)
        if value is not None:
            settings[name] = value
    corpus_root = getattr(adapter, "corpus_root", None)
    if corpus_root is None:
        knowledge_base = getattr(adapter, "knowledge_base", None)
        corpus_root = knowledge_base if knowledge_base and Path(knowledge_base).is_dir() else None
    if corpus_root is not None:
        settings["corpus_snapshot_hash"] = retrieval_benchmark.corpus_snapshot_hash(
            corpus_root
        )
    return settings
