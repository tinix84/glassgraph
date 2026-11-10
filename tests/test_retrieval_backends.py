"""Behavior tests for retrieval backend adapters."""
from __future__ import annotations

import json
import sys
import traceback

import pytest


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


def test_grooveseek_adapter_preserves_leading_dot_in_filename(retrieval_backends_mod):
    adapter = retrieval_backends_mod.GrooveSeekAdapter(
        executable="groove",
        knowledge_base="corpus",
        process_runner=lambda *_args: {
            "stdout": json.dumps({
                "results": [{"score": 1, "path": ".notes.md", "content": "Hidden note"}],
                "low_confidence": False,
            }),
            "elapsed_ms": 1,
            "peak_working_set_bytes": 1,
        },
        token_counter=lambda _text: 2,
    )

    run = adapter.query("note", limit=10)

    assert run["hits"][0]["path"] == ".notes.md"


@pytest.mark.parametrize("unsafe_path", ["../answer.md", "/answer.md", "C:/answer.md"])
def test_grooveseek_adapter_rejects_nonrelative_result_paths(
    retrieval_backends_mod, unsafe_path
):
    adapter = retrieval_backends_mod.GrooveSeekAdapter(
        executable="groove",
        knowledge_base="corpus",
        process_runner=lambda *_args: {
            "stdout": json.dumps({
                "results": [{"score": 1, "path": unsafe_path, "content": "Answer"}],
                "low_confidence": False,
            }),
            "elapsed_ms": 1,
            "peak_working_set_bytes": 1,
        },
        token_counter=lambda _text: 1,
    )

    with pytest.raises(RuntimeError, match="unsafe result path"):
        adapter.query("answer", limit=10)


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


def test_run_process_does_not_expose_backend_stderr(retrieval_backends_mod):
    private_text = "PRIVATE QUERY AND PATH wiki/private.md"

    with pytest.raises(RuntimeError) as error:
        retrieval_backends_mod.run_process(
            [
                sys.executable,
                "-c",
                f"import sys; print({private_text!r}, file=sys.stderr); raise SystemExit(7)",
            ],
            {},
        )

    assert str(error.value) == "backend command failed with exit code 7"
    assert private_text not in str(error.value)


def test_qmd_adapter_redacts_result_paths_outside_corpus(
    tmp_path, retrieval_backends_mod
):
    private_path = tmp_path.parent / "private" / "secret.md"

    def run_process(_args, _environment):
        return {
            "stdout": json.dumps([{"file": str(private_path), "snippet": "secret"}]),
            "elapsed_ms": 1.0,
            "peak_working_set_bytes": 1,
        }

    adapter = retrieval_backends_mod.QmdAdapter(
        node_executable="node",
        qmd_script="qmd",
        index="index",
        collection="collection",
        corpus_root=tmp_path,
        process_runner=run_process,
        token_counter=lambda _text: 1,
    )

    with pytest.raises(RuntimeError) as error:
        adapter.query("private query", limit=5)

    assert str(error.value) == "QMD returned a result outside the benchmark corpus"
    assert str(private_path) not in str(error.value)
    formatted = "".join(
        traceback.format_exception(type(error.value), error.value, error.value.__traceback__)
    )
    assert str(private_path) not in formatted
