"""Behavior tests for retrieval backend adapters."""
from __future__ import annotations

import json
import sys


def test_grooveseek_adapter_preserves_raw_hit_and_explicit_abstention(retrieval_backends_mod):
    def run_process(_args, _environment):
        return {
            "stdout": json.dumps(
                {
                    "results": [
                        {
                            "score": 0.032786883,
                            "path": "auriga-drive.md",
                            "content": "Auriga Drive is rated for 320 kW.",
                            "match_spans": [{"start": 0, "end": 12}],
                        }
                    ],
                    "low_confidence": True,
                }
            ),
            "elapsed_ms": 12.5,
            "peak_working_set_bytes": 123_456,
        }

    adapter = retrieval_backends_mod.GrooveSeekAdapter(
        executable="groove",
        knowledge_base="corpus",
        process_runner=run_process,
        token_counter=lambda _text: 9,
    )

    run = adapter.query("continuous power", limit=5)

    assert run["abstained"] is True
    assert run["hits"] == []
    assert run["raw_hits"] == [
        {
            "path": "auriga-drive.md",
            "text": "Auriga Drive is rated for 320 kW.",
            "backend_score": {
                "adapter": "grooveseek",
                "kind": "rrf",
                "raw": 0.032786883,
            },
            "context_tokens": 9,
            "explanation": {
                "kind": "match_spans",
                "value": [{"start": 0, "end": 12}],
            },
            "backend_locator": {
                "kind": "utf8_match_spans",
                "value": [{"start": 0, "end": 12}],
            },
        }
    ]
    assert run["latency_ms"] == 12.5
    assert run["peak_working_set_bytes"] == 123_456


def test_qmd_adapter_normalizes_full_path_and_preserves_score_trace(
    tmp_path, retrieval_backends_mod
):
    document = tmp_path / "auriga-drive.md"

    def run_process(_args, _environment):
        return {
            "stdout": json.dumps(
                [
                    {
                        "score": 1.0,
                        "file": str(document),
                        "line": 11,
                        "snippet": "@@ -10,4 @@\nAuriga Drive is rated for 320 kW.",
                        "explain": {"ftsScores": [0.9], "vectorScores": [0.7]},
                    }
                ]
            ),
            "elapsed_ms": 25.0,
            "peak_working_set_bytes": 654_321,
        }

    adapter = retrieval_backends_mod.QmdAdapter(
        node_executable="node",
        qmd_script="qmd",
        index="glassgraph-m1-public",
        collection="glassgraph-m1-public",
        corpus_root=tmp_path,
        process_runner=run_process,
        token_counter=lambda _text: 17,
    )

    run = adapter.query("continuous power", limit=5)

    assert run["abstained"] is False
    assert run["hits"] == run["raw_hits"]
    assert run["hits"][0] == {
        "path": "auriga-drive.md",
        "text": "@@ -10,4 @@\nAuriga Drive is rated for 320 kW.",
        "backend_score": {"adapter": "qmd", "kind": "hybrid", "raw": 1.0},
        "context_tokens": 17,
        "explanation": {
            "kind": "qmd_explain",
            "value": {"ftsScores": [0.9], "vectorScores": [0.7]},
        },
        "backend_locator": {"kind": "heuristic_line", "line": 11},
    }
    assert run["latency_ms"] == 25.0
    assert run["peak_working_set_bytes"] == 654_321


def test_run_process_captures_output_latency_and_working_set(retrieval_backends_mod):
    measured = retrieval_backends_mod.run_process(
        [sys.executable, "-c", "print('ready')"],
        {},
    )

    assert measured["stdout"].splitlines() == ["ready"]
    assert measured["elapsed_ms"] >= 0
    assert measured["peak_working_set_bytes"] > 0
