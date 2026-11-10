"""Behavior tests for retrieval backend adapters."""
from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path

import pytest


def test_grooveseek_adapter_preserves_raw_hit_and_explicit_abstention(retrieval_backends_mod):
    invoked = {}

    def run_process(_args, _environment):
        invoked["args"] = _args
        invoked["environment"] = _environment
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
        config="benchmark-groove.toml",
        model="bge-small-en-v1.5",
        model_cache="model-cache",
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
    assert invoked["args"][:8] == [
        "groove",
        "search",
        "continuous power",
        "--config",
        "benchmark-groove.toml",
        "--model",
        "bge-small-en-v1.5",
        "--kb-path",
    ]
    assert invoked["environment"]["FASTEMBED_CACHE_DIR"] == str(
        Path("model-cache").resolve()
    )


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


@pytest.mark.parametrize(
    "unsafe_path",
    ["../answer.md", "/answer.md", "C:/answer.md", "./C:/answer.md", "C:answer.md"],
)
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
    invoked = {}

    def run_process(_args, _environment):
        invoked["environment"] = _environment
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
        index_db=tmp_path / "index.sqlite",
        config_dir=tmp_path / "config",
        embed_model=tmp_path / "model.gguf",
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
    assert invoked["environment"] == {
        "INDEX_PATH": str((tmp_path / "index.sqlite").resolve()),
        "QMD_CONFIG_DIR": str((tmp_path / "config").resolve()),
        "QMD_EMBED_MODEL": str((tmp_path / "model.gguf").resolve()),
        "QMD_FORCE_CPU": "1",
        "QMD_EMBED_CONTEXT_SIZE": None,
        "QMD_EMBED_PARALLELISM": None,
        "QMD_EXPAND_CONTEXT_SIZE": None,
        "QMD_LLAMA_GPU": None,
        "QMD_RERANK_CONTEXT_SIZE": None,
        "XDG_CACHE_HOME": None,
        "XDG_CONFIG_HOME": None,
    }


@pytest.mark.parametrize(
    ("adapter_name", "payload"),
    [
        ("grooveseek", {"error": "index unavailable"}),
        ("qmd", {"error": "index unavailable"}),
    ],
)
def test_backend_adapters_reject_error_objects(
    tmp_path, retrieval_backends_mod, adapter_name, payload
):
    runner = lambda *_args: {
        "stdout": json.dumps(payload),
        "elapsed_ms": 1,
        "peak_working_set_bytes": 1,
    }
    if adapter_name == "grooveseek":
        adapter = retrieval_backends_mod.GrooveSeekAdapter(
            executable="groove",
            knowledge_base="corpus",
            process_runner=runner,
            token_counter=lambda _text: 1,
            config="groove.toml",
            model="bge-small-en-v1.5",
            model_cache="model-cache",
        )
    else:
        adapter = retrieval_backends_mod.QmdAdapter(
            node_executable="node",
            qmd_script="qmd",
            index="index",
            collection="collection",
            corpus_root=tmp_path,
            process_runner=runner,
            token_counter=lambda _text: 1,
            index_db=tmp_path / "index.sqlite",
            config_dir=tmp_path / "config",
            embed_model=tmp_path / "model.gguf",
        )

    with pytest.raises(RuntimeError, match="invalid response"):
        adapter.query("query", limit=10)


def test_grooveseek_adapter_rejects_malformed_scoring_fields(
    retrieval_backends_mod,
):
    adapter = retrieval_backends_mod.GrooveSeekAdapter(
        executable="groove",
        knowledge_base="corpus",
        process_runner=lambda *_args: {
            "stdout": json.dumps({
                "results": [{
                    "path": ["wrong type"],
                    "content": {"text": "ignored"},
                    "score": "high",
                    "match_spans": [],
                }],
                "low_confidence": "true",
            }),
            "elapsed_ms": 1,
            "peak_working_set_bytes": 1,
        },
        token_counter=lambda _text: 1,
    )

    with pytest.raises(RuntimeError, match="invalid response"):
        adapter.query("query", limit=10)


def test_qmd_adapter_requires_vector_scores_for_hybrid_run(
    tmp_path, retrieval_backends_mod
):
    adapter = retrieval_backends_mod.QmdAdapter(
        node_executable="node",
        qmd_script="qmd",
        index="index",
        collection="collection",
        corpus_root=tmp_path,
        process_runner=lambda *_args: {
            "stdout": json.dumps([{
                "score": 1.0,
                "file": str(tmp_path / "answer.md"),
                "line": 1,
                "snippet": "lexical-only",
                "explain": {"ftsScores": [1.0], "vectorScores": []},
            }]),
            "elapsed_ms": 1,
            "peak_working_set_bytes": 1,
        },
        token_counter=lambda _text: 1,
    )

    with pytest.raises(RuntimeError, match="vector retrieval"):
        adapter.query("query", limit=10)


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


def test_run_process_can_remove_ambient_backend_variables(
    monkeypatch, retrieval_backends_mod
):
    monkeypatch.setenv("INDEX_PATH", "ambient-private-index")
    measured = retrieval_backends_mod.run_process(
        [
            sys.executable,
            "-c",
            "import os; print(os.environ.get('INDEX_PATH', 'missing'))",
        ],
        {"INDEX_PATH": None},
    )

    assert measured["stdout"].strip() == "missing"


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
