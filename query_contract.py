"""Versioned query envelopes for backend-neutral Glassgraph search."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json


REQUEST_SCHEMA_VERSION = "glassgraph.query.v1"
RESULT_SCHEMA_VERSION = "glassgraph.query-result.v1"


class QueryContractError(ValueError):
    """Report an invalid query request or adapter response."""


def search_request(text: str, *, limit: int) -> dict:
    """Create one versioned search request."""
    if not isinstance(text, str) or not text.strip():
        raise QueryContractError("A search request needs text")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise QueryContractError("A search request needs a positive limit")
    return {
        "schema_version": REQUEST_SCHEMA_VERSION,
        "operation": "search",
        "limit": limit,
        "filters": {
            "page_types": [],
            "paths": [],
            "tags_any": [],
            "updated_from": None,
        },
        "input": {"text": text},
    }


def validate_search_request(request: dict) -> None:
    """Reject a request that the production search adapter cannot enforce."""
    if (
        not isinstance(request, dict)
        or request.get("schema_version") != REQUEST_SCHEMA_VERSION
        or request.get("operation") != "search"
        or not isinstance(request.get("input"), dict)
    ):
        raise QueryContractError("The query request does not match the search contract")
    text = request["input"].get("text")
    limit = request.get("limit")
    if not isinstance(text, str) or not text.strip():
        raise QueryContractError("A search request needs text")
    if not isinstance(limit, int) or isinstance(limit, bool) or limit <= 0:
        raise QueryContractError("A search request needs a positive limit")
    if request.get("filters") != {
        "page_types": [],
        "paths": [],
        "tags_any": [],
        "updated_from": None,
    }:
        raise QueryContractError("Search filters are not supported by this adapter")


def _canonical_hash(domain: str, value: object) -> str:
    payload = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return "sha256:" + hashlib.sha256(
        f"{domain}\0{payload}".encode("utf-8")
    ).hexdigest()


def request_hash(request: dict) -> str:
    """Bind a result to one exact query request."""
    return _canonical_hash("glassgraph:query-request:v1", request)


def backend_snapshot_hash(settings: dict) -> str:
    """Identify one exact retrieval backend configuration."""
    return _canonical_hash("glassgraph:backend-snapshot:v1", settings)


def _candidate(hit: dict, rank: int) -> dict:
    trace = {
        "path": hit.get("path"),
        "passage": hit.get("text"),
        "locator": deepcopy(hit.get("backend_locator")),
        "explanation": deepcopy(hit.get("explanation")),
        "context_tokens": hit.get("context_tokens"),
        "raw_preserved": True,
    }
    if isinstance(hit.get("heading"), str):
        trace["heading"] = hit["heading"]
    return {
        "result_id": f"result:{rank}",
        "kind": "passage_candidate",
        "rank": rank,
        "score": {
            "normalized": None,
            "backend": deepcopy(hit.get("backend_score")),
        },
        "backend_trace": trace,
        "evidence": {
            "status": "unverified",
            "evidence_id": None,
            "locator": None,
            "verification_error": None,
        },
    }


def _hit(candidate: dict) -> dict:
    if candidate.get("kind") != "passage_candidate":
        raise QueryContractError("A search result must be a passage candidate")
    trace = candidate.get("backend_trace")
    score = candidate.get("score")
    if not isinstance(trace, dict) or not isinstance(score, dict):
        raise QueryContractError("A passage candidate needs a score and trace")
    hit = {
        "path": trace.get("path"),
        "text": trace.get("passage"),
        "backend_score": deepcopy(score.get("backend")),
        "context_tokens": trace.get("context_tokens"),
        "explanation": deepcopy(trace.get("explanation")),
        "backend_locator": deepcopy(trace.get("locator")),
    }
    if isinstance(trace.get("heading"), str):
        hit["heading"] = trace["heading"]
    return hit


def execute_search(
    backend: str, adapter, request: dict, *, settings: dict
) -> dict:
    """Execute a search request and preserve the normalized adapter trace."""
    validate_search_request(request)
    text = request["input"].get("text")
    limit = request.get("limit")

    run = adapter.query(text, limit=limit)
    if (
        not isinstance(run, dict)
        or not isinstance(run.get("hits"), list)
        or not isinstance(run.get("raw_hits"), list)
        or any(not isinstance(hit, dict) for hit in run["hits"] + run["raw_hits"])
    ):
        raise QueryContractError("The retrieval adapter returned an invalid response")

    corpus_hash = settings.get("corpus_snapshot_hash")
    indexed_corpus_hash = settings.get("indexed_corpus_snapshot_hash")
    index_state = (
        "fresh"
        if isinstance(corpus_hash, str) and indexed_corpus_hash == corpus_hash
        else "stale"
        if isinstance(corpus_hash, str) and isinstance(indexed_corpus_hash, str)
        else "unbound"
    )
    response = {
        "schema_version": RESULT_SCHEMA_VERSION,
        "operation": "search",
        "request_hash": request_hash(request),
        "status": "abstained" if run.get("abstained") is True else "ok",
        "execution": {
            "mode": "local-model",
            "adapter": {
                "name": backend,
                "version": getattr(adapter, "version", None),
            },
            "backend_snapshot_hash": backend_snapshot_hash(settings),
            "fallback": {"active": False, "reason": None},
        },
        "index": {
            "state": index_state,
            "corpus_snapshot_hash": corpus_hash,
            "indexed_corpus_snapshot_hash": indexed_corpus_hash,
            "stale_reasons": (
                ["indexed_corpus_hash_mismatch"] if index_state == "stale" else []
            ),
        },
        "results": [_candidate(hit, rank) for rank, hit in enumerate(run["hits"], 1)],
        "raw_results": [
            _candidate(hit, rank) for rank, hit in enumerate(run["raw_hits"], 1)
        ],
        "warnings": [],
        "low_confidence": run.get("low_confidence") is True,
        "metrics": {
            "latency_ms": run.get("latency_ms"),
            "peak_working_set_bytes": run.get("peak_working_set_bytes"),
        },
    }
    if response["low_confidence"]:
        response["warnings"].append(
            {
                "code": "low_confidence",
                "message": "The retrieval backend marked these candidates as low confidence.",
            }
        )
    return response


def backend_run(request: dict, response: dict) -> dict:
    """Recover the benchmark run from a versioned search response."""
    validate_search_request(request)
    if (
        not isinstance(request, dict)
        or request.get("schema_version") != REQUEST_SCHEMA_VERSION
        or request.get("operation") != "search"
        or not isinstance(response, dict)
        or response.get("schema_version") != RESULT_SCHEMA_VERSION
        or response.get("operation") != "search"
        or response.get("request_hash") != request_hash(request)
        or response.get("status") not in {"ok", "abstained"}
        or not isinstance(response.get("index"), dict)
        or response["index"].get("state") != "fresh"
        or not isinstance(response["index"].get("corpus_snapshot_hash"), str)
        or response["index"].get("indexed_corpus_snapshot_hash")
        != response["index"].get("corpus_snapshot_hash")
        or not isinstance(response.get("results"), list)
        or not isinstance(response.get("raw_results"), list)
    ):
        raise QueryContractError("The stored query exchange is invalid")
    metrics = response.get("metrics")
    if not isinstance(metrics, dict):
        raise QueryContractError("The stored query exchange has no metrics")
    return {
        "hits": [_hit(candidate) for candidate in response["results"]],
        "raw_hits": [_hit(candidate) for candidate in response["raw_results"]],
        "abstained": response.get("status") == "abstained",
        "low_confidence": response.get("low_confidence") is True,
        "latency_ms": metrics.get("latency_ms"),
        "peak_working_set_bytes": metrics.get("peak_working_set_bytes"),
    }
