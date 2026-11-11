"""Behavior tests for the retrieval benchmark command interface."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace
import yaml


MEASUREMENT_ARGS = [
    "--setup-time-ms",
    "100",
    "--full-build-time-ms",
    "200",
    "--no-change-update-ms",
    "10",
    "--one-file-update-ms",
    "20",
    "--derived-index-size-bytes",
    "4096",
    "--offline-verified",
]


def _expected_qmd_embedding_fingerprint(model: str) -> str:
    is_qwen = re.search(r"qwen.*embed|embed.*qwen", model, re.IGNORECASE)
    query = "__qmd_embedding_query_probe__"
    title = "__qmd_embedding_title_probe__"
    document = "__qmd_embedding_document_probe__"
    formatted_query = (
        f"Instruct: Retrieve relevant documents for the given query\nQuery: {query}"
        if is_qwen
        else f"task: search result | query: {query}"
    )
    formatted_document = (
        f"{title}\n{document}"
        if is_qwen
        else f"title: {title} | text: {document}"
    )
    significant = "\n".join(
        (
            f"model:{model}",
            f"query:{formatted_query}",
            f"doc:{formatted_document}",
            "chunk_tokens:900",
            "chunk_overlap_tokens:135",
        )
    )
    return hashlib.sha256(significant.encode()).hexdigest()[:6]

PUBLIC_ANSWER_ID = "sha256:49f9bfe7dce9a5f1e1c2060cf8d021f034f319ceac3cd88ddf81b0cff9bf4ebf"
PUBLIC_IRRELEVANT_ID = "sha256:9eef3057700ae1a5c20ebb04e80930ffb1171e72b51a1723dbf2561dd0731725"
PRIVATE_ANSWER_ID = "sha256:ed02295cc9e18510c12565faf6b59374d3fdda301a092ff6d49743eeb1c5f35a"
PRIVATE_IRRELEVANT_ID = "sha256:c9870737134c02427c7619a41c77e35fba8605c48340d2201327515c7a639b52"


def _evidence_id(seed):
    return "sha256:" + hashlib.sha256(seed.encode()).hexdigest()


@pytest.mark.parametrize("backend", ["grooveseek", "qmd"])
def test_backend_settings_identity_changes_when_artifact_bytes_change(
    tmp_path, retrieval_benchmark_cli_mod, retrieval_benchmark_mod, backend
):
    tokenizer = tmp_path / "tokenizer.json"
    executable = tmp_path / "backend.exe"
    script = tmp_path / "qmd.js"
    index = tmp_path / "index.sqlite"
    knowledge_base = tmp_path / "corpus"
    knowledge_base.mkdir()
    groove_index = tmp_path / ".groove.db"
    for path, value in (
        (tokenizer, "tokenizer-v1"),
        (executable, "executable-v1"),
        (script, "script-v1"),
    ):
        path.write_text(value, encoding="utf-8")
    with sqlite3.connect(groove_index) as connection:
        connection.execute("CREATE TABLE chunks (value TEXT)")
        connection.execute("INSERT INTO chunks VALUES ('groove-index-v1')")
    with sqlite3.connect(index) as connection:
        connection.execute("CREATE TABLE evidence (value TEXT)")
        connection.execute("INSERT INTO evidence VALUES ('index-v1')")
    groove_config = tmp_path / "groove.toml"
    qmd_config = tmp_path / "fixture.yml"
    groove_config.write_text("[search]\n", encoding="utf-8")
    qmd_config.write_text("collections: {}\n", encoding="utf-8")
    args = SimpleNamespace(
        backend=backend,
        limit=10,
        path_prefix=None,
        tokenizer=tokenizer,
        groove_executable=str(executable),
        knowledge_base=str(knowledge_base),
        node_executable=str(executable),
        qmd_script=str(script),
        index=str(index),
        collection="fixture",
        corpus_root=knowledge_base,
        retrieval_model_id="fixture-model",
        retrieval_model_artifact=tokenizer,
        backend_config_artifact=[],
        groove_config=groove_config,
        qmd_config=qmd_config,
        qmd_index_db=index,
    )

    original = retrieval_benchmark_cli_mod._backend_settings_payload(args)
    if backend == "grooveseek":
        executable.write_text("replacement-v2", encoding="utf-8")
    else:
        with sqlite3.connect(index) as connection:
            connection.execute("INSERT INTO evidence VALUES ('replacement-v2')")
    changed = retrieval_benchmark_cli_mod._backend_settings_payload(args)

    assert all(
        value.startswith("sha256:")
        for value in original["artifact_hashes"].values()
        if value is not None
    )
    assert retrieval_benchmark_mod.backend_settings_lock(
        original
    ) != retrieval_benchmark_mod.backend_settings_lock(changed)


def test_qmd_settings_identity_ignores_ambient_embedding_model(
    tmp_path,
    monkeypatch,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    artifact = tmp_path / "artifact.bin"
    artifact.write_text("artifact", encoding="utf-8")
    args = SimpleNamespace(
        backend="qmd",
        limit=10,
        path_prefix=None,
        tokenizer=artifact,
        groove_executable=None,
        knowledge_base=None,
        node_executable=str(artifact),
        qmd_script=str(artifact),
        index=str(artifact),
        collection="fixture",
        corpus_root=tmp_path,
        retrieval_model_id="model-id",
        retrieval_model_artifact=artifact,
        backend_config_artifact=[],
        qmd_config=artifact,
        qmd_index_db=None,
    )

    monkeypatch.setenv("QMD_EMBED_MODEL", "model-a")
    first = retrieval_benchmark_cli_mod._backend_settings_payload(args)
    monkeypatch.setenv("QMD_EMBED_MODEL", "model-b")
    second = retrieval_benchmark_cli_mod._backend_settings_payload(args)

    assert retrieval_benchmark_mod.backend_settings_lock(
        first
    ) == retrieval_benchmark_mod.backend_settings_lock(second)


def test_sqlite_snapshot_hash_includes_committed_wal_rows(
    tmp_path, retrieval_benchmark_cli_mod
):
    database = tmp_path / "index.sqlite"
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("CREATE TABLE evidence (value TEXT)")
    connection.commit()
    before = retrieval_benchmark_cli_mod._sqlite_snapshot_sha256(database)

    connection.execute("INSERT INTO evidence VALUES ('new searchable row')")
    connection.commit()
    after = retrieval_benchmark_cli_mod._sqlite_snapshot_sha256(database)
    connection.close()

    assert before != after


@pytest.mark.parametrize("special_name", ["index#1.sqlite", "index%2esqlite"])
def test_sqlite_snapshot_hash_escapes_uri_metacharacters(
    tmp_path, retrieval_benchmark_cli_mod, special_name
):
    ordinary = tmp_path / "index.sqlite"
    special = tmp_path / special_name
    for database, value in ((ordinary, "ordinary"), (special, "special")):
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE evidence (value TEXT)")
            connection.execute("INSERT INTO evidence VALUES (?)", (value,))

    first = retrieval_benchmark_cli_mod._sqlite_snapshot_sha256(special)
    with sqlite3.connect(special) as connection:
        connection.execute("INSERT INTO evidence VALUES ('changed')")

    assert retrieval_benchmark_cli_mod._sqlite_snapshot_sha256(special) != first


def test_groove_index_hash_uses_database_next_to_knowledge_base(
    tmp_path, retrieval_benchmark_cli_mod
):
    knowledge_base = tmp_path / "corpus"
    knowledge_base.mkdir()
    outer = tmp_path / ".groove.db"
    stale_inner = knowledge_base / ".groove.db"
    for database, value in ((outer, "outer"), (stale_inner, "inner")):
        with sqlite3.connect(database) as connection:
            connection.execute("CREATE TABLE chunks (value TEXT)")
            connection.execute("INSERT INTO chunks VALUES (?)", (value,))
    first = retrieval_benchmark_cli_mod._groove_index_sha256(str(knowledge_base))

    with sqlite3.connect(stale_inner) as connection:
        connection.execute("INSERT INTO chunks VALUES ('stale-change')")
    assert retrieval_benchmark_cli_mod._groove_index_sha256(
        str(knowledge_base)
    ) == first

    with sqlite3.connect(outer) as connection:
        connection.execute("INSERT INTO chunks VALUES ('effective-change')")
    assert retrieval_benchmark_cli_mod._groove_index_sha256(
        str(knowledge_base)
    ) != first


def test_qmd_config_must_use_pinned_model_artifact(
    tmp_path, retrieval_benchmark_cli_mod
):
    model = (tmp_path / "model.gguf").resolve()
    model.write_text("GGUF", encoding="utf-8")
    config = tmp_path / "fixture.yml"
    configured_model = model.as_posix()
    args = SimpleNamespace(
        qmd_config=config,
        index="fixture",
        retrieval_model_artifact=model,
        retrieval_model_id=configured_model,
    )

    config.write_text("collections: {}\n", encoding="utf-8")
    assert not retrieval_benchmark_cli_mod._qmd_config_uses_model_artifact(args)

    config.write_text(
        "models:\n  embed: hf:remote/model/file.gguf\n", encoding="utf-8"
    )
    assert not retrieval_benchmark_cli_mod._qmd_config_uses_model_artifact(args)

    config.write_text(
        f"models:\n  embed: {json.dumps(configured_model)}\n"
        "  generate: local-generate.gguf\n"
        "  rerank: local-rerank.gguf\n",
        encoding="utf-8",
    )
    assert retrieval_benchmark_cli_mod._qmd_config_uses_model_artifact(args)


def test_qmd_config_parses_yaml_date_like_scalar_as_text(
    tmp_path, retrieval_benchmark_cli_mod
):
    model = (tmp_path / "model.gguf").resolve()
    model.write_text("model", encoding="utf-8")
    config = tmp_path / "fixture.yml"
    config.write_text(
        f"models:\n  embed: {json.dumps(str(model))}\n"
        "  generate: local-generate.gguf\n"
        "  rerank: local-rerank.gguf\n"
        "metadata:\n  built: 2026-11-10\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(
        qmd_config=config,
        index="fixture",
        retrieval_model_artifact=model,
        retrieval_model_id=str(model),
    )

    payload = retrieval_benchmark_cli_mod._read_qmd_config(args)

    assert payload["metadata"]["built"] == "2026-11-10"
    assert retrieval_benchmark_cli_mod._qmd_config_uses_model_artifact(
        args,
        payload,
    )


def test_qmd_config_uses_yaml_1_2_boolean_rules(
    tmp_path, retrieval_benchmark_cli_mod
):
    model = (tmp_path / "model.gguf").resolve()
    model.write_text("model", encoding="utf-8")
    config = tmp_path / "fixture.yml"
    config.write_text(
        "collections:\n"
        "  on:\n"
        f"    path: {json.dumps(str(tmp_path))}\n"
        "    pattern: '**/*.md'\n"
        "models:\n"
        f"  embed: {json.dumps(str(model))}\n"
        "  generate: local-generate.gguf\n"
        "  rerank: local-rerank.gguf\n"
        "flags:\n"
        "  enabled: true\n"
        "  legacy_word: on\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(qmd_config=config)

    payload = retrieval_benchmark_cli_mod._read_qmd_config(args)

    assert "on" in payload["collections"]
    assert payload["flags"] == {"enabled": True, "legacy_word": "on"}


def test_qmd_config_matches_installed_yaml_and_json_number_semantics(
    tmp_path, retrieval_benchmark_cli_mod
):
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")
    config = tmp_path / "fixture.yml"
    config.write_text(
        "values:\n"
        "  leading_zero_decimal: 0123\n"
        "  exponent: 1e3\n"
        "  infinity: .inf\n"
        "  binary_text: 0b10\n"
        "  hex_text: +0xFF\n"
        "  underscore_text: 1_000\n",
        encoding="utf-8",
    )
    args = SimpleNamespace(qmd_config=config, node_executable=node)

    payload = retrieval_benchmark_cli_mod._read_qmd_config(args)

    assert payload["values"] == {
        "leading_zero_decimal": 123,
        "exponent": 1000.0,
        "infinity": float("inf"),
        "binary_text": "0b10",
        "hex_text": "+0xFF",
        "underscore_text": "1_000",
    }
    assert retrieval_benchmark_cli_mod._qmd_config_json(args, payload) == (
        '{"values":{"leading_zero_decimal":123,"exponent":1000,'
        '"infinity":null,"binary_text":"0b10","hex_text":"+0xFF",'
        '"underscore_text":"1_000"}}'
    )


def test_qmd_index_preflight_requires_synced_config_and_vector_coverage(
    tmp_path, retrieval_benchmark_cli_mod
):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    document = corpus / "answer.md"
    document.write_text("Answer.\n", encoding="utf-8")
    document_hash = hashlib.sha256(document.read_bytes()).hexdigest()
    database = tmp_path / "index.sqlite"
    model = (tmp_path / "model.gguf").resolve()
    model.write_text("model", encoding="utf-8")
    config_payload = {
        "collections": {
            "fixture": {"path": str(corpus), "pattern": "**/*.md"}
        },
        "models": {
            "embed": str(model),
            "generate": "local-generate.gguf",
            "rerank": "local-rerank.gguf",
        },
    }
    config_hash = hashlib.sha256(
        json.dumps(
            config_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE store_config (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                collection TEXT NOT NULL,
                path TEXT NOT NULL,
                hash TEXT NOT NULL,
                active INTEGER NOT NULL
            );
            CREATE TABLE content_vectors (
                hash TEXT NOT NULL,
                seq INTEGER NOT NULL,
                model TEXT NOT NULL,
                embed_fingerprint TEXT NOT NULL,
                total_chunks INTEGER NOT NULL,
                embedded_at TEXT NOT NULL
            );
            CREATE TABLE vectors_vec (hash_seq TEXT PRIMARY KEY);
            CREATE TABLE vectors_vec_rowids (id TEXT NOT NULL);
            """
        )
        connection.execute(
            "INSERT INTO store_config VALUES ('config_hash', ?)",
            (config_hash,),
        )
        connection.execute(
            "INSERT INTO documents VALUES (1, 'fixture', 'answer.md', ?, 1)",
            (document_hash,),
        )
        connection.execute(
            "INSERT INTO content_vectors VALUES (?, 0, ?, ?, 1, ?)",
            (
                document_hash,
                str(model),
                _expected_qmd_embedding_fingerprint(str(model)),
                "2000-01-01T00:00:00.000Z",
            ),
        )
        connection.execute(
            "INSERT INTO vectors_vec_rowids VALUES (?)",
            (document_hash + "_0",),
        )
    args = SimpleNamespace(
        qmd_index_db=database,
        collection="fixture",
        retrieval_model_id=str(model),
        corpus_root=corpus,
        benchmark_corpus_root=corpus,
        path_prefix=None,
    )

    assert retrieval_benchmark_cli_mod._qmd_index_is_ready(args, config_payload)

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE content_vectors SET embed_fingerprint = 'stale1'"
        )
    assert not retrieval_benchmark_cli_mod._qmd_index_is_ready(
        args,
        config_payload,
    )

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE content_vectors SET embed_fingerprint = ?",
            (_expected_qmd_embedding_fingerprint(str(model)),),
        )

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE content_vectors SET seq = 2")
        connection.execute(
            "UPDATE vectors_vec_rowids SET id = ?",
            (document_hash + "_2",),
        )
    assert not retrieval_benchmark_cli_mod._qmd_index_is_ready(
        args,
        config_payload,
    )

    with sqlite3.connect(database) as connection:
        connection.execute("UPDATE content_vectors SET seq = 0")
        connection.execute(
            "UPDATE vectors_vec_rowids SET id = ?",
            (document_hash + "_0",),
        )

    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE vectors_vec_rowids SET id = ?",
            (document_hash + "_99",),
        )

    assert not retrieval_benchmark_cli_mod._qmd_index_is_ready(
        args, config_payload
    )


def test_qmd_package_hash_covers_imported_package_files(
    tmp_path, retrieval_benchmark_cli_mod
):
    package = tmp_path / "node_modules" / "qmd"
    script = package / "dist" / "cli" / "qmd.js"
    imported = package / "dist" / "store.js"
    script.parent.mkdir(parents=True)
    (package / "package.json").write_text('{"name":"qmd"}', encoding="utf-8")
    script.write_text("import '../store.js'", encoding="utf-8")
    imported.write_text("export const version = 1", encoding="utf-8")
    before = retrieval_benchmark_cli_mod._qmd_package_sha256(str(script))

    imported.write_text("export const version = 2", encoding="utf-8")

    assert retrieval_benchmark_cli_mod._qmd_package_sha256(str(script)) != before


def test_qmd_package_hash_covers_sibling_native_dependencies(
    tmp_path, retrieval_benchmark_cli_mod
):
    install = tmp_path / "qmd-install"
    package = install / "node_modules" / "@tobilu" / "qmd"
    script = package / "bin" / "qmd"
    sibling = install / "node_modules" / "sqlite-vec" / "sqlite-vec.dll"
    script.parent.mkdir(parents=True)
    sibling.parent.mkdir(parents=True)
    (install / "package.json").write_text('{"private":true}', encoding="utf-8")
    (install / "package-lock.json").write_text('{"lockfileVersion":3}', encoding="utf-8")
    (package / "package.json").write_text('{"name":"@tobilu/qmd"}', encoding="utf-8")
    script.write_text("#!/usr/bin/env node", encoding="utf-8")
    sibling.write_text("native-v1", encoding="utf-8")
    before = retrieval_benchmark_cli_mod._qmd_package_sha256(str(script))

    sibling.write_text("native-v2", encoding="utf-8")

    assert retrieval_benchmark_cli_mod._qmd_package_sha256(str(script)) != before


def test_directory_hash_rejects_file_disappearance(
    tmp_path, monkeypatch, retrieval_benchmark_cli_mod
):
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "model.bin").write_text("model", encoding="utf-8")
    monkeypatch.setattr(retrieval_benchmark_cli_mod, "_file_sha256", lambda _path: None)

    with pytest.raises(OSError, match="changed while it was fingerprinted"):
        retrieval_benchmark_cli_mod._directory_sha256(artifact)


@pytest.mark.parametrize(
    "record",
    [
        {
            "id": "q1",
            "query": "question",
            "required_groups": [[{
                "evidence_id": [],
                "path": "answer.md",
                "text": "answer",
                "grade": "direct",
            }]],
            "irrelevant": [],
        },
        {
            "id": "q1",
            "query": "question",
            "required_groups": [],
            "irrelevant": None,
        },
        {
            "id": "q1",
            "query": "question",
            "required_groups": [[{
                "evidence_id": "sha256:" + "a" * 64,
                "path": "answer.md",
                "text": "answer",
                "grade": [],
            }]],
            "irrelevant": [],
        },
    ],
)
def test_validate_records_rejects_malformed_judgments_without_type_error(
    record, retrieval_benchmark_cli_mod
):
    with pytest.raises(ValueError, match="Benchmark records are invalid"):
        retrieval_benchmark_cli_mod.validate_records([record])


@pytest.mark.parametrize("field", ["split", "kind"])
def test_private_workbook_rejects_unhashable_distribution_fields(
    retrieval_benchmark_cli_mod, field
):
    record = {
        "split": "development",
        "kind": "positive",
        "owner_authored": True,
        "owner_adjudicated": True,
    }
    record[field] = []

    with pytest.raises(ValueError, match="distribution"):
        retrieval_benchmark_cli_mod.validate_private_workbook({"records": [record]})


def test_cli_redacts_artifact_fingerprint_failure(
    tmp_path,
    capsys,
    monkeypatch,
    retrieval_benchmark_cli_mod,
):
    secret_path = tmp_path / "private" / "model.bin"

    def fail_fingerprint(_path):
        raise PermissionError(str(secret_path))

    monkeypatch.setattr(retrieval_benchmark_cli_mod, "_file_sha256", fail_fingerprint)

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(tmp_path / "unused.json"),
                "--backend",
                "grooveseek",
                "--groove-executable",
                "groove",
                "--knowledge-base",
                "corpus",
                "--privacy",
                "public",
                "--benchmark-corpus-root",
                str(tmp_path),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 0,
        )

    stderr = capsys.readouterr().err
    assert error.value.code == 2
    assert str(secret_path) not in stderr
    assert "Benchmark artifacts could not be fingerprinted" in stderr


def _manifest(records, retrieval_benchmark_mod, split_membership, corpus_root):
    return {
        "schema_version": 1,
        "corpus_snapshot_hash": retrieval_benchmark_mod.corpus_snapshot_hash(corpus_root),
        "query_set_hash": retrieval_benchmark_mod.query_set_hash(records),
        "judgment_set_hash": retrieval_benchmark_mod.judgment_set_hash(records),
        "split_membership": split_membership,
        "adjudication_date": "2026-11-10",
    }


def _public_queries():
    positives = [
        {
            "id": f"p{index}",
            "query": f"PRIVATE QUERY TEXT {index}",
            "required_groups": [[{
                "evidence_id": PUBLIC_ANSWER_ID,
                "path": "answer.md",
                "text": "Exact answer passage.",
                "grade": "direct",
            }]],
            "irrelevant": [{
                "evidence_id": PUBLIC_IRRELEVANT_ID,
                "path": "answer.md",
                "text": "Exact answer.",
                "grade": "irrelevant",
            }],
        }
        for index in range(1, 6)
    ]
    negatives = [
        {
            "id": f"n{index}",
            "query": f"No answer {index}",
            "required_groups": [],
        }
        for index in range(1, 6)
    ]
    return positives + negatives


def _private_records():
    records = []
    for split, short, positive_count, negative_count in (
        ("development", "dev", 30, 10),
        ("evaluation", "eval", 15, 5),
    ):
        for index in range(1, positive_count + 1):
            records.append(
                {
                    "id": f"private-v1-{short}-p{index:02d}",
                    "split": split,
                    "kind": "positive",
                    "type": "exact",
                    "query": f"{split} private positive {index}",
                    "required_groups": [[{
                        "evidence_id": PRIVATE_ANSWER_ID,
                        "path": "wiki/answer.md",
                        "text": "Exact answer.",
                        "grade": "direct",
                    }]],
                    "irrelevant": [{
                        "evidence_id": PRIVATE_IRRELEVANT_ID,
                        "path": "wiki/answer.md",
                        "text": "Exact answer passage.",
                        "grade": "irrelevant",
                    }],
                    "adjudication_note": "",
                    "owner_authored": True,
                    "owner_adjudicated": True,
                    "adjudicated_by": "Riccardo Tinivella",
                    "adjudicated_date": "2026-11-10",
                }
            )
        for index in range(1, negative_count + 1):
            records.append(
                {
                    "id": f"private-v1-{short}-n{index:02d}",
                    "split": split,
                    "kind": "negative",
                    "type": "negative",
                    "query": f"{split} private negative {index}",
                    "required_groups": [],
                    "adjudication_note": "Owner checked alternate wording.",
                    "owner_authored": True,
                    "owner_adjudicated": True,
                    "adjudicated_by": "Riccardo Tinivella",
                    "adjudicated_date": "2026-11-10",
                }
            )
    return records


def _private_payload(retrieval_benchmark_mod, corpus_root):
    records = _private_records()
    return _add_manifest(
        {"schema_version": 1, "benchmark_version": "private-v1", "records": records},
        records,
        retrieval_benchmark_mod,
        {
            split: [record["id"] for record in records if record["split"] == split]
            for split in ("development", "evaluation")
        },
        corpus_root,
    )


def _add_manifest(
    payload,
    records,
    retrieval_benchmark_mod,
    split_membership,
    corpus_root,
):
    privacy = "private" if "records" in payload else "public"
    payload["manifest"] = _manifest(
        records,
        retrieval_benchmark_mod,
        split_membership,
        corpus_root,
    )
    payload["benchmark_version"] = retrieval_benchmark_mod.benchmark_version(
        privacy,
        records,
        payload["manifest"]["corpus_snapshot_hash"],
    )
    return payload


@pytest.mark.parametrize(
    ("payload_schema", "manifest_schema"),
    [(None, None), (2, 2), (1, 2)],
)
def test_cli_requires_schema_version_one(
    tmp_path,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
    payload_schema,
    manifest_schema,
):
    corpus_root = _write_corpus(tmp_path)
    queries = _public_queries()
    payload = _add_manifest(
        {"schema_version": 1, "queries": queries},
        queries,
        retrieval_benchmark_mod,
        {"public": [query["id"] for query in queries]},
        corpus_root,
    )
    if payload_schema is None:
        payload.pop("schema_version")
    else:
        payload["schema_version"] = payload_schema
    if manifest_schema is None:
        payload["manifest"].pop("schema_version")
    else:
        payload["manifest"]["schema_version"] = manifest_schema
    queries_path = tmp_path / "schema.json"
    queries_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries", str(queries_path),
                "--backend", "grooveseek",
                "--groove-executable", "groove",
                "--knowledge-base", "corpus",
                "--privacy", "public",
                "--benchmark-corpus-root", str(corpus_root),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2


def test_validate_records_requires_explicit_irrelevant_judgment_for_positive(
    retrieval_benchmark_cli_mod,
):
    record = _public_queries()[0]
    record.pop("irrelevant")

    with pytest.raises(ValueError, match="invalid"):
        retrieval_benchmark_cli_mod.validate_records([record])


def test_validate_records_rejects_relevant_judgment_on_negative_query(
    retrieval_benchmark_cli_mod,
):
    record = _public_queries()[-1]
    record["irrelevant"] = [{
        "evidence_id": PUBLIC_ANSWER_ID,
        "path": "answer.md",
        "text": "Exact answer passage.",
        "grade": "direct",
    }]

    with pytest.raises(ValueError, match="invalid"):
        retrieval_benchmark_cli_mod.validate_records([record])


def test_validate_records_rejects_contradictory_evidence_grades(
    retrieval_benchmark_cli_mod,
):
    record = _public_queries()[0]
    record["irrelevant"][0]["evidence_id"] = PUBLIC_ANSWER_ID

    with pytest.raises(ValueError, match="invalid"):
        retrieval_benchmark_cli_mod.validate_records([record])


def test_validate_records_rejects_malformed_judgment_container(
    retrieval_benchmark_cli_mod,
):
    record = {"id": "q1", "query": "Question", "required_groups": 5}

    with pytest.raises(ValueError, match="invalid"):
        retrieval_benchmark_cli_mod.validate_records([record])


@pytest.mark.parametrize("records", [[5], {"q1": {}}])
def test_validate_records_rejects_nonobject_record_roots(
    retrieval_benchmark_cli_mod, records
):
    with pytest.raises(ValueError, match="records are invalid"):
        retrieval_benchmark_cli_mod.validate_records(records)


def test_cli_rejects_nonobject_json_root(
    tmp_path, capsys, retrieval_benchmark_cli_mod
):
    queries_path = tmp_path / "queries.json"
    queries_path.write_text("[]", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(queries_path),
                "--backend",
                "grooveseek",
                "--groove-executable",
                "groove",
                "--knowledge-base",
                "corpus",
                "--privacy",
                "public",
                "--benchmark-corpus-root",
                str(tmp_path),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 0,
        )

    assert error.value.code == 2
    assert "Benchmark input is invalid" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("backend", "message"),
    [
        ("grooveseek", "GrooveSeek requires"),
        ("qmd", "QMD requires"),
    ],
)
def test_cli_requires_complete_backend_configuration(
    tmp_path,
    capsys,
    retrieval_benchmark_cli_mod,
    backend,
    message,
):
    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(tmp_path / "unused.json"),
                "--backend",
                backend,
                "--privacy",
                "public",
                "--benchmark-corpus-root",
                str(tmp_path),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 0,
        )

    assert error.value.code == 2
    assert message in capsys.readouterr().err


def test_private_cli_requires_retrieval_model_identity(
    tmp_path, capsys, retrieval_benchmark_cli_mod
):
    workspace = _private_workspace(tmp_path)
    knowledge_base = workspace / "groove-backend" / "wiki"
    knowledge_base.mkdir(parents=True)
    groove_config = workspace / "groove.toml"
    groove_config.write_text("[search]\n", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(workspace / "unused.json"),
                "--backend",
                "grooveseek",
                "--groove-executable",
                "groove",
                "--knowledge-base",
                    str(knowledge_base),
                    "--groove-config",
                    str(groove_config),
                "--privacy",
                "private",
                "--split",
                "development",
                "--output",
                str(workspace / "report.json"),
                "--benchmark-corpus-root",
                str(tmp_path),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 0,
        )

    assert error.value.code == 2
    assert "require --retrieval-model-id" in capsys.readouterr().err


def test_cli_rejects_empty_qmd_configuration_values(
    tmp_path, capsys, retrieval_benchmark_cli_mod
):
    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(tmp_path / "unused.json"),
                "--backend",
                "qmd",
                "--node-executable",
                "",
                "--qmd-script",
                "",
                "--index",
                "",
                "--collection",
                "",
                "--corpus-root",
                str(tmp_path),
                "--privacy",
                "public",
                "--benchmark-corpus-root",
                str(tmp_path),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 0,
        )

    assert error.value.code == 2
    assert "QMD requires" in capsys.readouterr().err


def test_cli_redacts_tokenizer_load_failure(
    tmp_path, capsys, retrieval_benchmark_cli_mod
):
    tokenizer_path = tmp_path / "secret-tokenizer.json"

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(tmp_path / "unused.json"),
                "--backend",
                "grooveseek",
                "--groove-executable",
                "groove",
                "--knowledge-base",
                "corpus",
                "--privacy",
                "public",
                "--benchmark-corpus-root",
                str(tmp_path),
                "--tokenizer",
                str(tokenizer_path),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
        )

    stderr = capsys.readouterr().err
    assert error.value.code == 2
    assert str(tokenizer_path) not in stderr
    assert "Tokenizer could not be loaded" in stderr


@pytest.mark.parametrize("failure_kind", ["os-error", "malformed-json"])
def test_cli_redacts_expected_backend_failures(
    tmp_path,
    capsys,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
    failure_kind,
):
    queries = _public_queries()
    corpus_root = _write_corpus(tmp_path)
    queries_path = tmp_path / "queries.json"
    queries_path.write_text(
        json.dumps(
            _add_manifest(
                {"schema_version": 1, "queries": queries},
                queries,
                retrieval_benchmark_mod,
                {"public": [record["id"] for record in queries]},
                corpus_root,
            )
        ),
        encoding="utf-8",
    )

    def run_process(_args, _environment):
        if failure_kind == "os-error":
            raise OSError(str(tmp_path / "secret-executable.exe"))
        return {
            "stdout": "not-json",
            "elapsed_ms": 1.0,
            "peak_working_set_bytes": 1000,
        }

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(queries_path),
                "--backend",
                "grooveseek",
                *_public_groove_args(tmp_path, corpus_root),
                "--privacy",
                "public",
                "--benchmark-corpus-root",
                str(corpus_root),
                *MEASUREMENT_ARGS,
            ],
            process_runner=run_process,
            token_counter=lambda _text: 0,
        )

    stderr = capsys.readouterr().err
    assert error.value.code == 2
    assert str(tmp_path) not in stderr
    assert "Retrieval backend execution failed" in stderr


def test_cli_rejects_stale_benchmark_version(
    tmp_path, retrieval_benchmark_cli_mod, retrieval_benchmark_mod
):
    corpus_root = _write_corpus(tmp_path)
    queries = _public_queries()
    payload = _add_manifest(
        {"schema_version": 1, "queries": queries},
        queries,
        retrieval_benchmark_mod,
        {"public": [query["id"] for query in queries]},
        corpus_root,
    )
    payload["benchmark_version"] = "public-v1-stale"
    queries_path = tmp_path / "stale-version.json"
    queries_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries", str(queries_path),
                "--backend", "grooveseek",
                "--groove-executable", "groove",
                "--knowledge-base", "corpus",
                "--privacy", "public",
                "--benchmark-corpus-root", str(corpus_root),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2


def test_cli_rejects_result_limit_below_reported_cutoffs(
    tmp_path, capsys, retrieval_benchmark_cli_mod
):
    corpus_root = _write_corpus(tmp_path)
    queries_path = tmp_path / "unused.json"
    queries_path.write_text("{}", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries", str(queries_path),
                "--backend", "grooveseek",
                "--groove-executable", "groove",
                "--knowledge-base", "corpus",
                "--privacy", "public",
                "--benchmark-corpus-root", str(corpus_root),
                "--limit", "9",
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert "at least 10" in capsys.readouterr().err


def _write_groove_index(corpus_root):
    database = corpus_root.parent / ".groove.db"
    with sqlite3.connect(database) as connection:
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS documents (
                id INTEGER PRIMARY KEY,
                path TEXT UNIQUE NOT NULL,
                content_hash TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS chunks (
                id INTEGER PRIMARY KEY,
                document_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS vec_chunks_rowids (
                rowid INTEGER PRIMARY KEY,
                id TEXT
            );
            """
        )
        for index, document in enumerate(
            sorted(path for path in corpus_root.rglob("*") if path.suffix == ".md"),
            start=1,
        ):
            relative = document.relative_to(corpus_root).as_posix()
            content_hash = hashlib.sha256(document.read_bytes()).hexdigest()
            connection.execute(
                "INSERT OR REPLACE INTO documents VALUES (?, ?, ?)",
                (index, relative, content_hash),
            )
            connection.execute(
                "INSERT OR REPLACE INTO chunks VALUES (?, ?)",
                (index, index),
            )
            connection.execute(
                "INSERT OR REPLACE INTO vec_chunks_rowids(rowid, id) VALUES (?, NULL)",
                (index,),
            )


def test_groove_index_preflight_rejects_stale_document_roster(
    tmp_path, retrieval_benchmark_cli_mod
):
    corpus = _write_corpus(tmp_path)
    _write_groove_index(corpus)
    args = SimpleNamespace(
        knowledge_base=str(corpus),
        benchmark_corpus_root=corpus,
        path_prefix=None,
    )

    assert retrieval_benchmark_cli_mod._groove_index_is_ready(args)

    (corpus / "hard-distractor.md").write_text(
        "Hard distractor.\n",
        encoding="utf-8",
    )

    assert not retrieval_benchmark_cli_mod._groove_index_is_ready(args)


def _private_workspace(tmp_path):
    workspace = tmp_path / ".glassgraph" / "benchmarks" / "private" / "v1"
    workspace.mkdir(parents=True, exist_ok=True)
    return workspace


def _private_args(workbook_path, output_path, corpus_root):
    workspace = workbook_path.parent
    artifact_root = workspace / "groove-artifacts"
    artifact_root.mkdir(exist_ok=True)
    executable = artifact_root / "groove.exe"
    tokenizer = artifact_root / "tokenizer.json"
    model = artifact_root / "fastembed-cache"
    model.mkdir(exist_ok=True)
    model_file = model / "embedding-model.bin"
    groove_config = artifact_root / "groove.toml"
    for path, content in (
        (executable, "groove-test-binary"),
        (tokenizer, "tokenizer-test-data"),
        (model_file, "model-test-data"),
        (groove_config, "[search]\n"),
    ):
        path.write_text(content, encoding="utf-8")
    backend_root = workspace / "groove-backend"
    knowledge_base = backend_root / "wiki"
    if not knowledge_base.exists():
        shutil.copytree(corpus_root / "wiki", knowledge_base)
    _write_groove_index(knowledge_base)
    return [
        "--queries",
        str(workbook_path),
        "--backend",
        "grooveseek",
        "--groove-executable",
        str(executable),
        "--knowledge-base",
        str(knowledge_base),
        "--groove-config",
        str(groove_config),
        "--tokenizer",
        str(tokenizer),
        "--retrieval-model-id",
        "fixture-embedding-model-v1",
        "--retrieval-model-artifact",
        str(model),
        "--path-prefix",
        "wiki",
        "--privacy",
        "private",
        "--split",
        "development",
        "--output",
        str(output_path),
        "--benchmark-corpus-root",
        str(corpus_root),
        *MEASUREMENT_ARGS,
    ]


def _public_groove_args(tmp_path, corpus_root):
    artifact_root = tmp_path / "public-groove-artifacts"
    model_cache = artifact_root / "fastembed-cache"
    model_cache.mkdir(parents=True)
    executable = artifact_root / "groove.exe"
    config = artifact_root / "groove.toml"
    tokenizer = artifact_root / "tokenizer.json"
    for path, content in (
        (model_cache / "model.bin", "model"),
        (executable, "executable"),
        (config, "[search]\n"),
        (tokenizer, "tokenizer"),
    ):
        path.write_text(content, encoding="utf-8")
    _write_groove_index(corpus_root)
    return [
        "--groove-executable", str(executable),
        "--groove-config", str(config),
        "--knowledge-base", str(corpus_root),
        "--tokenizer", str(tokenizer),
        "--retrieval-model-id", "bge-small-en-v1.5",
        "--retrieval-model-artifact", str(model_cache),
    ]


def _public_qmd_args(
    tmp_path,
    corpus_root,
    retrieval_benchmark_cli_mod,
    qmd_benchmark_build_mod,
    command_log=None,
):
    artifact_root = tmp_path / "public-qmd-artifacts"
    package = artifact_root / "qmd-package"
    script = package / "dist" / "cli" / "qmd.js"
    script.parent.mkdir(parents=True)
    (package / "package.json").write_text('{"name":"qmd"}', encoding="utf-8")
    script.write_text("// fixture", encoding="utf-8")
    node_executable = shutil.which("node")
    if node_executable is None:
        pytest.skip("Node.js is not installed")
    node = Path(node_executable)
    tokenizer = artifact_root / "tokenizer.json"
    model = artifact_root / "model.gguf"
    config = artifact_root / "fixture.yml"
    index_db = artifact_root / "index.sqlite"
    build_receipt = artifact_root / "qmd-build-receipt.json"
    config_payload = {
        "collections": {"fixture": {"path": str(corpus_root), "pattern": "**/*.md"}},
        "models": {
            "embed": str(model.resolve()),
            "generate": str(model.resolve()),
            "rerank": str(model.resolve()),
        },
    }
    for path, content in (
        (tokenizer, "tokenizer"),
        (model, "GGUF fixture"),
        (config, yaml.safe_dump(config_payload, sort_keys=False)),
    ):
        path.write_text(content, encoding="utf-8")
    config_hash = hashlib.sha256(
        json.dumps(
            config_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()
    with sqlite3.connect(index_db) as connection:
        connection.executescript(
            """
            CREATE TABLE store_config (key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE documents (
                id INTEGER PRIMARY KEY,
                collection TEXT NOT NULL,
                path TEXT NOT NULL,
                hash TEXT NOT NULL,
                active INTEGER NOT NULL
            );
            CREATE TABLE content_vectors (
                hash TEXT NOT NULL,
                seq INTEGER NOT NULL,
                model TEXT NOT NULL,
                embed_fingerprint TEXT NOT NULL,
                total_chunks INTEGER NOT NULL,
                embedded_at TEXT NOT NULL
            );
            CREATE TABLE vectors_vec (hash_seq TEXT PRIMARY KEY);
            CREATE TABLE vectors_vec_rowids (id TEXT NOT NULL);
            """
        )
        connection.execute(
            "INSERT INTO store_config VALUES ('config_hash', ?)",
            (config_hash,),
        )
        for index, document in enumerate(
            sorted(path for path in corpus_root.rglob("*") if path.suffix == ".md"),
            start=1,
        ):
            document_hash = hashlib.sha256(document.read_bytes()).hexdigest()
            relative = document.relative_to(corpus_root).as_posix()
            connection.execute(
                "INSERT INTO documents VALUES (?, 'fixture', ?, ?, 1)",
                (index, relative, document_hash),
            )
            connection.execute(
                "INSERT INTO content_vectors VALUES (?, 0, ?, ?, 1, ?)",
                (
                    document_hash,
                    str(model.resolve()),
                    _expected_qmd_embedding_fingerprint(str(model.resolve())),
                    "2000-01-01T00:00:00.000Z",
                ),
            )
            connection.execute(
                "INSERT INTO vectors_vec_rowids VALUES (?)",
                (document_hash + "_0",),
            )
    def run_build(command, environment):
        if command_log is not None:
            command_log.append((command, environment))
        if "embed" in command:
            with sqlite3.connect(index_db) as connection:
                connection.execute(
                    "UPDATE content_vectors SET embedded_at = "
                    "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
                )
        return {
            "stdout": "",
            "stderr": "",
            "elapsed_ms": 1.0,
            "peak_working_set_bytes": 1,
        }

    assert qmd_benchmark_build_mod.main(
        [
            "--node-executable", str(node),
            "--privacy", "public",
            "--qmd-script", str(script),
            "--qmd-config", str(config),
            "--qmd-index-db", str(index_db),
            "--index", "fixture",
            "--collection", "fixture",
            "--corpus-root", str(corpus_root),
            "--benchmark-corpus-root", str(corpus_root),
            "--retrieval-model-id", str(model.resolve()),
            "--retrieval-model-artifact", str(model),
            "--output", str(build_receipt),
        ],
        process_runner=run_build,
    ) == 0
    return [
        "--node-executable", str(node),
        "--qmd-script", str(script),
        "--qmd-config", str(config),
        "--qmd-index-db", str(index_db),
        "--qmd-build-receipt", str(build_receipt),
        "--index", "fixture",
        "--collection", "fixture",
        "--corpus-root", str(corpus_root),
        "--tokenizer", str(tokenizer),
        "--retrieval-model-id", str(model.resolve()),
        "--retrieval-model-artifact", str(model),
    ]


def _write_corpus(tmp_path, *, private=False):
    corpus_root = tmp_path / "corpus"
    document = corpus_root / "wiki" / "answer.md" if private else corpus_root / "answer.md"
    document.parent.mkdir(parents=True)
    document.write_text("Exact answer passage. Exact answer.\n", encoding="utf-8")
    return corpus_root


def test_qmd_build_receipt_detects_model_replacement(
    tmp_path, retrieval_benchmark_cli_mod, qmd_benchmark_build_mod
):
    corpus_root = _write_corpus(tmp_path)
    commands = []
    backend_args = _public_qmd_args(
        tmp_path,
        corpus_root,
        retrieval_benchmark_cli_mod,
        qmd_benchmark_build_mod,
        commands,
    )

    assert [command[0][4] for command in commands] == ["update", "embed"]
    assert "-f" in commands[1][0]
    assert commands[1][1]["QMD_EMBED_MODEL"] == backend_args[
        backend_args.index("--retrieval-model-id") + 1
    ]

    def value(flag):
        return backend_args[backend_args.index(flag) + 1]

    args = SimpleNamespace(
        qmd_script=value("--qmd-script"),
        qmd_config=Path(value("--qmd-config")),
        qmd_index_db=Path(value("--qmd-index-db")),
        qmd_build_receipt=Path(value("--qmd-build-receipt")),
        collection=value("--collection"),
        retrieval_model_id=value("--retrieval-model-id"),
        retrieval_model_artifact=Path(value("--retrieval-model-artifact")),
        corpus_root=Path(value("--corpus-root")),
    )
    receipt = json.loads(args.qmd_build_receipt.read_text(encoding="utf-8"))
    assert receipt["build_proof"]["active_chunk_count"] == 1
    assert (
        receipt["build_proof"]["pre_index_sha256"]
        != receipt["build_proof"]["post_index_sha256"]
    )
    assert retrieval_benchmark_cli_mod._qmd_build_receipt_is_valid(args)

    no_op_receipt = tmp_path / "no-op-build-receipt.json"
    with pytest.raises(SystemExit) as no_op_error:
        qmd_benchmark_build_mod.main(
            [
                "--privacy", "public",
                "--node-executable", value("--node-executable"),
                "--qmd-script", value("--qmd-script"),
                "--qmd-config", value("--qmd-config"),
                "--qmd-index-db", value("--qmd-index-db"),
                "--index", value("--index"),
                "--collection", value("--collection"),
                "--corpus-root", value("--corpus-root"),
                "--benchmark-corpus-root", str(corpus_root),
                "--retrieval-model-id", value("--retrieval-model-id"),
                "--retrieval-model-artifact", value("--retrieval-model-artifact"),
                "--output", str(no_op_receipt),
            ],
            process_runner=lambda *_args: {
                "stdout": "",
                "stderr": "",
                "elapsed_ms": 1.0,
                "peak_working_set_bytes": 1,
            },
        )
    assert no_op_error.value.code == 2
    assert not no_op_receipt.exists()

    race_receipt = tmp_path / "raced-build-receipt.json"

    def race_build(command, _environment):
        if "embed" in command:
            args.retrieval_model_artifact.write_text(
                "replaced weights",
                encoding="utf-8",
            )
            with sqlite3.connect(args.qmd_index_db) as connection:
                connection.execute(
                    "UPDATE content_vectors SET embedded_at = "
                    "strftime('%Y-%m-%dT%H:%M:%fZ', 'now')"
                )
        return {
            "stdout": "",
            "stderr": "",
            "elapsed_ms": 1.0,
            "peak_working_set_bytes": 1,
        }

    with pytest.raises(SystemExit) as race_error:
        qmd_benchmark_build_mod.main(
            [
                "--privacy", "public",
                "--node-executable", value("--node-executable"),
                "--qmd-script", value("--qmd-script"),
                "--qmd-config", value("--qmd-config"),
                "--qmd-index-db", value("--qmd-index-db"),
                "--index", value("--index"),
                "--collection", value("--collection"),
                "--corpus-root", value("--corpus-root"),
                "--benchmark-corpus-root", str(corpus_root),
                "--retrieval-model-id", value("--retrieval-model-id"),
                "--retrieval-model-artifact", value("--retrieval-model-artifact"),
                "--output", str(race_receipt),
            ],
            process_runner=race_build,
        )
    assert race_error.value.code == 2
    assert not race_receipt.exists()

    assert not retrieval_benchmark_cli_mod._qmd_build_receipt_is_valid(args)


def test_qmd_benchmark_build_rejects_update_hooks(
    retrieval_benchmark_cli_mod,
):
    payload = {
        "collections": {
            "private": {
                "path": "D:/vault/wiki",
                "pattern": "**/*.md",
                "update": "curl https://example.invalid/private",
            }
        }
    }

    assert retrieval_benchmark_cli_mod._qmd_config_has_update_hooks(payload)


def test_private_qmd_builder_rejects_public_checkout_before_execution(
    tmp_path,
    qmd_benchmark_build_mod,
):
    workspace = _private_workspace(tmp_path)
    workbook = workspace / "workbook.json"
    workbook.write_text("{}", encoding="utf-8")
    benchmark_corpus = tmp_path / "wiki"
    benchmark_corpus.mkdir()
    public_checkout = tmp_path / ".tools" / "entity_linker"
    (public_checkout / ".git").mkdir(parents=True)
    qmd_root = public_checkout / "private-qmd"
    qmd_root.mkdir()
    receipt = qmd_root / "receipt.json"

    with pytest.raises(SystemExit) as error:
        qmd_benchmark_build_mod.main(
            [
                "--privacy", "private",
                "--queries", str(workbook),
                "--node-executable", "node",
                "--qmd-script", "qmd",
                "--qmd-config", str(qmd_root / "config.yml"),
                "--qmd-index-db", str(qmd_root / "index.sqlite"),
                "--index", "private",
                "--collection", "private",
                "--corpus-root", str(qmd_root / "corpus"),
                "--benchmark-corpus-root", str(benchmark_corpus),
                "--retrieval-model-id", "D:/models/embed.gguf",
                "--retrieval-model-artifact", "D:/models/embed.gguf",
                "--output", str(receipt),
            ],
            process_runner=lambda *_args: pytest.fail("QMD must not run"),
        )

    assert error.value.code == 2
    assert not receipt.exists()


def test_public_cli_prints_aggregate_only(
    tmp_path, capsys, retrieval_benchmark_cli_mod, retrieval_benchmark_mod
):
    queries = _public_queries()
    corpus_root = _write_corpus(tmp_path)
    queries_path = tmp_path / "queries.json"
    queries_path.write_text(
        json.dumps(
            _add_manifest({
                "schema_version": 1,
                "benchmark_version": "public-v1",
                "queries": queries,
            }, queries, retrieval_benchmark_mod, {"public": [item["id"] for item in queries]}, corpus_root)
        ),
        encoding="utf-8",
    )

    def run_process(_args, _environment):
        return {
            "stdout": json.dumps(
                {
                    "results": [
                        {
                            "score": 1.0,
                            "path": "answer.md",
                            "content": "Exact answer passage.",
                            "match_spans": [{"start": 0, "end": 21}],
                        }
                    ],
                    "low_confidence": False,
                }
            ),
            "elapsed_ms": 5.0,
            "peak_working_set_bytes": 1000,
        }

    exit_code = retrieval_benchmark_cli_mod.main(
        [
            "--queries",
            str(queries_path),
            "--backend",
            "grooveseek",
            *_public_groove_args(tmp_path, corpus_root),
            "--privacy",
            "public",
            "--benchmark-corpus-root",
            str(corpus_root),
            *MEASUREMENT_ARGS,
        ],
        process_runner=run_process,
        token_counter=lambda _text: 4,
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["schema_version"] == 1
    assert payload["backend"] == "grooveseek"
    assert payload["benchmark"]["corpus_snapshot_hash"] == (
        retrieval_benchmark_mod.corpus_snapshot_hash(corpus_root)
    )
    assert payload["summary"]["group_recall_at_5"] == 1.0
    assert payload["measurements"]["full_build_time_ms"] == 200
    assert payload["measurements"]["derived_index_size_bytes"] == 4096
    assert payload["measurements"]["offline_verified"] is True
    assert "PRIVATE QUERY TEXT" not in output
    assert "answer.md" not in output


def test_cli_rejects_artifacts_changed_during_execution(
    tmp_path,
    capsys,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    queries = _public_queries()
    corpus_root = _write_corpus(tmp_path)
    queries_path = tmp_path / "queries.json"
    queries_path.write_text(
        json.dumps(
            _add_manifest(
                {"schema_version": 1, "queries": queries},
                queries,
                retrieval_benchmark_mod,
                {"public": [query["id"] for query in queries]},
                corpus_root,
            )
        ),
        encoding="utf-8",
    )
    backend_args = _public_groove_args(tmp_path, corpus_root)
    config = Path(backend_args[backend_args.index("--groove-config") + 1])
    changed = False

    def run_process(_args, _environment):
        nonlocal changed
        if not changed:
            config.write_text("[search]\nmmr = true\n", encoding="utf-8")
            changed = True
        return {
            "stdout": json.dumps({"results": [], "low_confidence": False}),
            "elapsed_ms": 1,
            "peak_working_set_bytes": 1,
        }

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries", str(queries_path),
                "--backend", "grooveseek",
                *backend_args,
                "--privacy", "public",
                "--benchmark-corpus-root", str(corpus_root),
                *MEASUREMENT_ARGS,
            ],
            process_runner=run_process,
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert "artifacts changed during execution" in capsys.readouterr().err


def test_cli_rejects_corpus_changed_during_execution(
    tmp_path,
    capsys,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    queries = _public_queries()
    corpus_root = _write_corpus(tmp_path)
    queries_path = tmp_path / "queries.json"
    queries_path.write_text(
        json.dumps(
            _add_manifest(
                {"schema_version": 1, "queries": queries},
                queries,
                retrieval_benchmark_mod,
                {"public": [query["id"] for query in queries]},
                corpus_root,
            )
        ),
        encoding="utf-8",
    )
    changed = False

    def run_process(_args, _environment):
        nonlocal changed
        if not changed:
            (corpus_root / "new-distractor.md").write_text(
                "New distractor.\n", encoding="utf-8"
            )
            changed = True
        return {
            "stdout": json.dumps({"results": [], "low_confidence": False}),
            "elapsed_ms": 1,
            "peak_working_set_bytes": 1,
        }

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries", str(queries_path),
                "--backend", "grooveseek",
                *_public_groove_args(tmp_path, corpus_root),
                "--privacy", "public",
                "--benchmark-corpus-root", str(corpus_root),
                *MEASUREMENT_ARGS,
            ],
            process_runner=run_process,
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert "corpus changed during execution" in capsys.readouterr().err


def test_public_cli_executes_queries_in_canonical_id_order(
    tmp_path, retrieval_benchmark_cli_mod, retrieval_benchmark_mod
):
    queries = list(reversed(_public_queries()))
    corpus_root = _write_corpus(tmp_path)
    queries_path = tmp_path / "queries.json"
    queries_path.write_text(
        json.dumps(
            _add_manifest(
                {"schema_version": 1, "queries": queries},
                queries,
                retrieval_benchmark_mod,
                {"public": [item["id"] for item in queries]},
                corpus_root,
            )
        ),
        encoding="utf-8",
    )
    executed_queries = []

    def run_process(args, _environment):
        executed_queries.append(args[2])
        return {
            "stdout": json.dumps({"results": [], "low_confidence": False}),
            "elapsed_ms": 1.0,
            "peak_working_set_bytes": 1000,
        }

    retrieval_benchmark_cli_mod.main(
        [
            "--queries",
            str(queries_path),
            "--backend",
            "grooveseek",
            *_public_groove_args(tmp_path, corpus_root),
            "--privacy",
            "public",
            "--benchmark-corpus-root",
            str(corpus_root),
            *MEASUREMENT_ARGS,
        ],
        process_runner=run_process,
        token_counter=lambda _text: 0,
    )

    assert executed_queries == [
        record["query"] for record in sorted(queries, key=lambda item: item["id"])
    ]


def test_private_cli_filters_split_and_writes_report_without_stdout(
    tmp_path, capsys, retrieval_benchmark_cli_mod, retrieval_benchmark_mod
):
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "authoring-workbook.json"
    output_path = workspace / "private-report.json"
    corpus_root = _write_corpus(tmp_path, private=True)
    payload = _private_payload(retrieval_benchmark_mod, corpus_root)
    workbook_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    def run_process(_args, _environment):
        return {
            "stdout": json.dumps(
                {
                    "results": [
                        {
                            "score": 1.0,
                            "path": "answer.md",
                            "content": "Exact answer.",
                            "match_spans": [],
                        }
                    ],
                    "low_confidence": False,
                }
            ),
            "elapsed_ms": 5.0,
            "peak_working_set_bytes": 1000,
        }

    exit_code = retrieval_benchmark_cli_mod.main(
        _private_args(workbook_path, output_path, corpus_root),
        process_runner=run_process,
        token_counter=lambda _text: 4,
    )

    captured = capsys.readouterr()
    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert captured.out == ""
    assert report["privacy"] == "private"
    assert report["split"] == "development"
    assert report["query_count"] == 40
    assert report["summary"]["group_recall_at_5"] == 1.0
    assert "evaluation private positive" not in output_path.read_text(encoding="utf-8")


def test_private_cli_rejects_report_outside_vault_workspace(
    tmp_path, capsys, retrieval_benchmark_cli_mod, retrieval_benchmark_mod
):
    corpus_root = _write_corpus(tmp_path, private=True)
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "authoring-workbook.json"
    workbook_path.write_text(
        json.dumps(_private_payload(retrieval_benchmark_mod, corpus_root)),
        encoding="utf-8",
    )
    output_path = tmp_path / "public-report.json"

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            _private_args(workbook_path, output_path, corpus_root),
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert "vault-side private workspace" in capsys.readouterr().err
    assert not output_path.exists()


def _init_git_repository(path):
    subprocess.run(
        ["git", "init", "-q", str(path)],
        check=True,
        capture_output=True,
        text=True,
    )


def _private_boundary_args(workspace, corpus_root, output=None):
    backend_root = workspace / "groove-backend"
    knowledge_base = backend_root / "wiki"
    knowledge_base.mkdir(parents=True, exist_ok=True)
    config = workspace / "groove.toml"
    config.write_text("[search]\n", encoding="utf-8")
    return SimpleNamespace(
        backend="grooveseek",
        queries=workspace / "workbook.json",
        output=output or workspace / "report.json",
        benchmark_corpus_root=corpus_root,
        knowledge_base=str(knowledge_base),
        groove_config=config,
    )


def test_private_workspace_allows_ignored_vault_git_root(
    tmp_path, monkeypatch, retrieval_benchmark_cli_mod
):
    workspace = _private_workspace(tmp_path)
    _init_git_repository(tmp_path)
    (tmp_path / ".gitignore").write_text(
        "/.glassgraph/benchmarks/private/\n",
        encoding="utf-8",
    )
    corpus_root = tmp_path / "wiki"
    corpus_root.mkdir()
    args = _private_boundary_args(workspace, corpus_root)
    original_git_command = retrieval_benchmark_cli_mod._git_command
    commands = []

    def counting_git_command(root, arguments, **kwargs):
        commands.append(arguments)
        return original_git_command(root, arguments, **kwargs)

    monkeypatch.setattr(
        retrieval_benchmark_cli_mod,
        "_git_command",
        counting_git_command,
    )

    assert retrieval_benchmark_cli_mod._private_paths_are_vault_local(args)
    assert len(commands) == 3


def test_private_workspace_rejects_nested_git_checkout(
    tmp_path, retrieval_benchmark_cli_mod
):
    workspace = _private_workspace(tmp_path)
    report_directory = workspace / "reports"
    (report_directory / ".git").mkdir(parents=True)
    corpus_root = tmp_path / "wiki"
    corpus_root.mkdir()
    args = _private_boundary_args(
        workspace,
        corpus_root,
        output=report_directory / "report.json",
    )

    assert not retrieval_benchmark_cli_mod._private_paths_are_vault_local(args)


def test_private_workspace_rejects_backend_artifacts_in_public_checkout(
    tmp_path, retrieval_benchmark_cli_mod
):
    workspace = _private_workspace(tmp_path)
    corpus_root = tmp_path / "wiki"
    corpus_root.mkdir()
    public_checkout = tmp_path / ".tools" / "entity_linker"
    (public_checkout / ".git").mkdir(parents=True)
    knowledge_base = public_checkout / "private-corpus" / "wiki"
    knowledge_base.mkdir(parents=True)
    config = public_checkout / "private-groove.toml"
    config.write_text("[search]\n", encoding="utf-8")
    args = SimpleNamespace(
        backend="grooveseek",
        queries=workspace / "workbook.json",
        output=workspace / "report.json",
        benchmark_corpus_root=corpus_root,
        knowledge_base=str(knowledge_base),
        groove_config=config,
    )

    assert not retrieval_benchmark_cli_mod._private_paths_are_vault_local(args)


def test_private_workspace_rejects_qmd_artifacts_in_public_checkout(
    tmp_path, retrieval_benchmark_cli_mod
):
    workspace = _private_workspace(tmp_path)
    benchmark_corpus = tmp_path / "wiki"
    benchmark_corpus.mkdir()
    public_checkout = tmp_path / ".tools" / "entity_linker"
    (public_checkout / ".git").mkdir(parents=True)
    qmd_root = public_checkout / "private-qmd"
    qmd_root.mkdir()
    args = SimpleNamespace(
        backend="qmd",
        queries=workspace / "workbook.json",
        output=workspace / "report.json",
        benchmark_corpus_root=benchmark_corpus,
        corpus_root=qmd_root / "corpus",
        qmd_config=qmd_root / "config.yml",
        qmd_index_db=qmd_root / "index.sqlite",
        qmd_build_receipt=qmd_root / "receipt.json",
    )

    assert not retrieval_benchmark_cli_mod._private_paths_are_vault_local(args)


def test_private_workspace_rejects_effective_gitignore_negation(
    tmp_path, retrieval_benchmark_cli_mod
):
    workspace = _private_workspace(tmp_path)
    _init_git_repository(tmp_path)
    (tmp_path / ".gitignore").write_text(
        "/.glassgraph/benchmarks/private/**\n"
        "!/.glassgraph/benchmarks/private/v1/\n"
        "!/.glassgraph/benchmarks/private/v1/report.json\n",
        encoding="utf-8",
    )
    corpus_root = tmp_path / "wiki"
    corpus_root.mkdir()
    args = _private_boundary_args(workspace, corpus_root)

    assert not retrieval_benchmark_cli_mod._private_paths_are_vault_local(args)


def test_private_workspace_rejects_tracked_private_file(
    tmp_path, retrieval_benchmark_cli_mod
):
    workspace = _private_workspace(tmp_path)
    _init_git_repository(tmp_path)
    (tmp_path / ".gitignore").write_text(
        "/.glassgraph/benchmarks/private/\n",
        encoding="utf-8",
    )
    workbook = workspace / "workbook.json"
    workbook.write_text("{}", encoding="utf-8")
    subprocess.run(
        ["git", "-C", str(tmp_path), "add", "-f", str(workbook)],
        check=True,
        capture_output=True,
        text=True,
    )
    corpus_root = tmp_path / "wiki"
    corpus_root.mkdir()
    args = _private_boundary_args(workspace, corpus_root)

    assert not retrieval_benchmark_cli_mod._private_paths_are_vault_local(args)


@pytest.mark.parametrize(
    "invalid_case",
    ["missing", "mismatch", "changed-settings", "malformed-lock-map"],
)
def test_private_evaluation_requires_manifest_settings_lock(
    tmp_path,
    capsys,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
    invalid_case,
):
    corpus_root = _write_corpus(tmp_path, private=True)
    payload = _private_payload(retrieval_benchmark_mod, corpus_root)
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "workbook.json"
    output_path = workspace / "report.json"
    args = _private_args(workbook_path, output_path, corpus_root)
    parsed_args = retrieval_benchmark_cli_mod._parser().parse_args(args)
    expected_lock = retrieval_benchmark_mod.backend_settings_lock(
        retrieval_benchmark_cli_mod._backend_settings_payload(parsed_args)
    )
    args_lock = []
    if invalid_case in {"mismatch", "changed-settings"}:
        payload["manifest"]["locked_backend_settings"] = {
            "grooveseek": expected_lock
        }
        args_lock = [
            "--settings-lock",
            _evidence_id("other-settings")
            if invalid_case == "mismatch"
            else expected_lock,
        ]
    elif invalid_case == "malformed-lock-map":
        payload["manifest"]["locked_backend_settings"] = None
        args_lock = ["--settings-lock", expected_lock]
    workbook_path.write_text(json.dumps(payload), encoding="utf-8")
    args[args.index("development")] = "evaluation"
    args.extend(args_lock)
    if invalid_case == "changed-settings":
        args.extend(["--limit", "11"])

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            args,
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert "locked backend settings" in capsys.readouterr().err


def test_private_evaluation_records_matching_settings_lock(
    tmp_path, retrieval_benchmark_cli_mod, retrieval_benchmark_mod
):
    corpus_root = _write_corpus(tmp_path, private=True)
    payload = _private_payload(retrieval_benchmark_mod, corpus_root)
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "workbook.json"
    output_path = workspace / "report.json"
    args = _private_args(workbook_path, output_path, corpus_root)
    parsed_args = retrieval_benchmark_cli_mod._parser().parse_args(args)
    settings_identity = retrieval_benchmark_cli_mod._backend_settings_payload(
        parsed_args
    )
    settings_lock = retrieval_benchmark_mod.backend_settings_lock(
        settings_identity
    )
    payload["manifest"]["locked_backend_settings"] = {
        "grooveseek": settings_lock
    }
    workbook_path.write_text(json.dumps(payload), encoding="utf-8")
    args[args.index("development")] = "evaluation"
    args.extend(["--settings-lock", settings_lock])

    retrieval_benchmark_cli_mod.main(
        args,
        process_runner=lambda *_args: {
            "stdout": json.dumps({"results": [], "low_confidence": False}),
            "elapsed_ms": 1,
            "peak_working_set_bytes": 1,
        },
        token_counter=lambda _text: 1,
    )

    report = json.loads(output_path.read_text(encoding="utf-8"))
    assert report["split"] == "evaluation"
    assert report["benchmark"]["settings_lock"] == settings_lock
    assert report["benchmark"]["artifact_hashes"] == settings_identity[
        "artifact_hashes"
    ]
    assert all(report["benchmark"]["artifact_hashes"].values())


def test_public_cli_runs_qmd_adapter(
    tmp_path,
    capsys,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
    qmd_benchmark_build_mod,
):
    queries = _public_queries()
    queries_path = tmp_path / "queries.json"
    corpus_root = _write_corpus(tmp_path)
    document = corpus_root / "answer.md"
    queries_path.write_text(
        json.dumps(
            _add_manifest({
                "schema_version": 1,
                "benchmark_version": "public-v1",
                "queries": queries,
            }, queries, retrieval_benchmark_mod, {"public": [item["id"] for item in queries]}, corpus_root)
        ),
        encoding="utf-8",
    )

    def run_process(_args, _environment):
        return {
            "stdout": json.dumps(
                [
                    {
                        "score": 1.0,
                        "file": str(document),
                        "line": 1,
                        "snippet": "@@ -1,1 @@\nExact answer passage.",
                        "explain": {
                            "blendedScore": 1.0,
                            "vectorScores": [0.9],
                        },
                    }
                ]
            ),
            "elapsed_ms": 7.0,
            "peak_working_set_bytes": 2000,
        }

    exit_code = retrieval_benchmark_cli_mod.main(
        [
            "--queries",
            str(queries_path),
            "--backend",
            "qmd",
            *_public_qmd_args(
                tmp_path,
                corpus_root,
                retrieval_benchmark_cli_mod,
                qmd_benchmark_build_mod,
            ),
            "--privacy",
            "public",
            "--benchmark-corpus-root",
            str(corpus_root),
            *MEASUREMENT_ARGS,
        ],
        process_runner=run_process,
        token_counter=lambda _text: 5,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["backend"] == "qmd"
    assert payload["summary"]["group_recall_at_5"] == 1.0


def test_cli_redacts_qmd_out_of_corpus_path(
    tmp_path,
    capsys,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
    qmd_benchmark_build_mod,
):
    corpus_root = _write_corpus(tmp_path)
    queries = _public_queries()
    payload = _add_manifest(
        {"schema_version": 1, "queries": queries},
        queries,
        retrieval_benchmark_mod,
        {"public": [query["id"] for query in queries]},
        corpus_root,
    )
    queries_path = tmp_path / "queries.json"
    queries_path.write_text(json.dumps(payload), encoding="utf-8")
    private_path = tmp_path.parent / "private-vault" / "secret.md"

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries", str(queries_path),
                "--backend", "qmd",
                *_public_qmd_args(
                    tmp_path,
                    corpus_root,
                    retrieval_benchmark_cli_mod,
                    qmd_benchmark_build_mod,
                ),
                "--privacy", "public",
                "--benchmark-corpus-root", str(corpus_root),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: {
                "stdout": json.dumps([{
                    "score": 1.0,
                    "file": str(private_path),
                    "line": 1,
                    "snippet": "private",
                    "explain": {
                        "blendedScore": 1.0,
                        "vectorScores": [0.9],
                    },
                }]),
                "elapsed_ms": 1,
                "peak_working_set_bytes": 1,
            },
            token_counter=lambda _text: 1,
        )

    stderr = capsys.readouterr().err
    assert error.value.code == 2
    assert str(private_path) not in stderr
    assert "Retrieval backend execution failed" in stderr


def test_load_token_counter_uses_pinned_tokenizer_file(
    tmp_path, retrieval_benchmark_cli_mod
):
    tokenizer_path = tmp_path / "tokenizer.json"
    tokenizer = Tokenizer(
        WordLevel(
            vocab={"[UNK]": 0, "Auriga": 1, "Drive": 2},
            unk_token="[UNK]",
        )
    )
    tokenizer.pre_tokenizer = Whitespace()
    tokenizer.save(str(tokenizer_path))

    count_tokens = retrieval_benchmark_cli_mod.load_token_counter(tokenizer_path)

    assert count_tokens("Auriga Drive") == 2


def test_private_cli_rejects_incomplete_owner_benchmark(
    tmp_path, retrieval_benchmark_cli_mod
):
    corpus_root = _write_corpus(tmp_path, private=True)
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "incomplete.json"
    output_path = workspace / "report.json"
    workbook_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark_version": "private-v1",
                "records": [],
            }
        ),
        encoding="utf-8",
    )

    def must_not_run(_args, _environment):
        raise AssertionError("backend must not run for an incomplete private benchmark")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(workbook_path),
                "--backend",
                "grooveseek",
                "--groove-executable",
                "groove",
                "--knowledge-base",
                "corpus",
                "--privacy",
                "private",
                "--split",
                "development",
                "--output",
                str(output_path),
                "--benchmark-corpus-root",
                str(corpus_root),
                *MEASUREMENT_ARGS,
            ],
            process_runner=must_not_run,
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert not output_path.exists()


def test_private_cli_rejects_unadjudicated_record(
    tmp_path, retrieval_benchmark_cli_mod, retrieval_benchmark_mod
):
    corpus_root = _write_corpus(tmp_path, private=True)
    payload = _private_payload(retrieval_benchmark_mod, corpus_root)
    payload["records"][0]["owner_adjudicated"] = False
    records = payload["records"]
    payload["manifest"] = _manifest(
        records,
        retrieval_benchmark_mod,
        payload["manifest"]["split_membership"],
        corpus_root,
    )
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "unadjudicated.json"
    output_path = workspace / "report.json"
    workbook_path.write_text(
        json.dumps(payload),
        encoding="utf-8",
    )

    def must_not_run(_args, _environment):
        raise AssertionError("backend must not run for unadjudicated records")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(workbook_path),
                "--backend",
                "grooveseek",
                "--groove-executable",
                "groove",
                "--knowledge-base",
                "corpus",
                "--privacy",
                "private",
                "--split",
                "development",
                "--output",
                str(output_path),
                "--benchmark-corpus-root",
                str(corpus_root),
                *MEASUREMENT_ARGS,
            ],
            process_runner=must_not_run,
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert not output_path.exists()


@pytest.mark.parametrize(
    "invalid_case",
    ["duplicate-id", "empty-positive", "bad-evidence-id"],
)
def test_private_cli_rejects_invalid_record_identity_or_judgment(
    tmp_path,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
    invalid_case,
):
    corpus_root = _write_corpus(tmp_path, private=True)
    payload = _private_payload(retrieval_benchmark_mod, corpus_root)
    if invalid_case == "duplicate-id":
        payload["records"][1]["id"] = payload["records"][0]["id"]
    elif invalid_case == "empty-positive":
        payload["records"][0]["required_groups"] = []
    else:
        payload["records"][0]["required_groups"][0][0]["evidence_id"] = "not-a-hash"
    records = payload["records"]
    payload["manifest"] = _manifest(
        records,
        retrieval_benchmark_mod,
        {
            split: [record["id"] for record in records if record["split"] == split]
            for split in ("development", "evaluation")
        },
        corpus_root,
    )
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / f"{invalid_case}.json"
    output_path = workspace / "report.json"
    workbook_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            _private_args(workbook_path, output_path, corpus_root),
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert not output_path.exists()


def test_private_cli_rejects_output_collision_before_backend_execution(
    tmp_path,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    corpus_root = _write_corpus(tmp_path, private=True)
    workbook_path = _private_workspace(tmp_path) / "workbook.json"
    original = json.dumps(_private_payload(retrieval_benchmark_mod, corpus_root))
    workbook_path.write_text(original, encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            _private_args(workbook_path, workbook_path, corpus_root),
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert workbook_path.read_text(encoding="utf-8") == original


def test_private_cli_refuses_to_replace_existing_report(
    tmp_path,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    corpus_root = _write_corpus(tmp_path, private=True)
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "workbook.json"
    output_path = workspace / "report.json"
    workbook_path.write_text(
        json.dumps(_private_payload(retrieval_benchmark_mod, corpus_root)),
        encoding="utf-8",
    )
    output_path.write_text("keep me", encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            _private_args(workbook_path, output_path, corpus_root),
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert output_path.read_text(encoding="utf-8") == "keep me"


def test_public_cli_rejects_categories_with_fewer_than_five_queries(
    tmp_path,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    corpus_root = _write_corpus(tmp_path)
    queries = _public_queries()
    queries.pop(0)
    payload = _add_manifest(
        {"schema_version": 1, "benchmark_version": "public-v1", "queries": queries},
        queries,
        retrieval_benchmark_mod,
        {"public": [query["id"] for query in queries]},
        corpus_root,
    )
    queries_path = tmp_path / "small.json"
    queries_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(queries_path),
                "--backend",
                "grooveseek",
                "--groove-executable",
                "groove",
                "--knowledge-base",
                "corpus",
                "--privacy",
                "public",
                "--benchmark-corpus-root",
                str(corpus_root),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2


def test_cli_rejects_manifest_hash_mismatch_before_backend_execution(
    tmp_path,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    corpus_root = _write_corpus(tmp_path)
    queries = _public_queries()
    payload = _add_manifest(
        {"schema_version": 1, "benchmark_version": "public-v1", "queries": queries},
        queries,
        retrieval_benchmark_mod,
        {"public": [query["id"] for query in queries]},
        corpus_root,
    )
    payload["queries"][0]["query"] = "Changed without a new manifest"
    queries_path = tmp_path / "changed.json"
    queries_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(queries_path),
                "--backend",
                "grooveseek",
                "--groove-executable",
                "groove",
                "--knowledge-base",
                "corpus",
                "--privacy",
                "public",
                "--benchmark-corpus-root",
                str(corpus_root),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2


def test_public_report_does_not_copy_manifest_details(
    tmp_path,
    capsys,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    corpus_root = _write_corpus(tmp_path)
    queries = _public_queries()
    payload = _add_manifest(
        {"schema_version": 1, "benchmark_version": "public-v1", "queries": queries},
        queries,
        retrieval_benchmark_mod,
        {"public": [query["id"] for query in queries]},
        corpus_root,
    )
    payload["manifest"]["unexpected_private_field"] = "PRIVATE QUERY TEXT"
    queries_path = tmp_path / "queries.json"
    queries_path.write_text(json.dumps(payload), encoding="utf-8")

    retrieval_benchmark_cli_mod.main(
        [
            "--queries",
            str(queries_path),
            "--backend",
            "grooveseek",
            *_public_groove_args(tmp_path, corpus_root),
            "--privacy",
            "public",
            "--benchmark-corpus-root",
            str(corpus_root),
            *MEASUREMENT_ARGS,
        ],
        process_runner=lambda *_args: {
            "stdout": json.dumps({"results": [], "low_confidence": False}),
            "elapsed_ms": 1,
            "peak_working_set_bytes": 1,
        },
        token_counter=lambda _text: 1,
    )

    output = capsys.readouterr().out
    report = json.loads(output)
    assert "PRIVATE QUERY TEXT" not in output
    assert "p1" not in output
    assert "split_membership" not in report["benchmark"]


def test_cli_rejects_corpus_snapshot_mismatch_before_backend_execution(
    tmp_path,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    frozen_root = _write_corpus(tmp_path)
    different_root = tmp_path / "different-corpus"
    different_root.mkdir()
    (different_root / "answer.md").write_text("Different bytes.\n", encoding="utf-8")
    queries = _public_queries()
    payload = _add_manifest(
        {"schema_version": 1, "benchmark_version": "public-v1", "queries": queries},
        queries,
        retrieval_benchmark_mod,
        {"public": [query["id"] for query in queries]},
        frozen_root,
    )
    queries_path = tmp_path / "queries.json"
    queries_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            [
                "--queries",
                str(queries_path),
                "--backend",
                "grooveseek",
                "--groove-executable",
                "groove",
                "--knowledge-base",
                "corpus",
                "--privacy",
                "public",
                "--benchmark-corpus-root",
                str(different_root),
                *MEASUREMENT_ARGS,
            ],
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2


@pytest.mark.parametrize("invalid_case", ["missing-source", "wrong-evidence-id"])
def test_cli_redacts_private_evidence_validation_failures(
    tmp_path,
    capsys,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
    invalid_case,
):
    corpus_root = _write_corpus(tmp_path, private=True)
    payload = _private_payload(retrieval_benchmark_mod, corpus_root)
    private_id = payload["records"][0]["id"]
    secret_path = "wiki/secret-private-file.md"
    if invalid_case == "missing-source":
        payload["records"][0]["required_groups"][0][0]["path"] = secret_path
    else:
        payload["records"][0]["required_groups"][0][0]["evidence_id"] = (
            "sha256:" + "0" * 64
        )
    records = payload["records"]
    payload["benchmark_version"] = retrieval_benchmark_mod.benchmark_version(
        "private", records, payload["manifest"]["corpus_snapshot_hash"]
    )
    payload["manifest"] = _manifest(
        records,
        retrieval_benchmark_mod,
        payload["manifest"]["split_membership"],
        corpus_root,
    )
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "private-workbook.json"
    output_path = workspace / "private-report.json"
    workbook_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            _private_args(workbook_path, output_path, corpus_root),
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    stderr = capsys.readouterr().err
    assert error.value.code == 2
    assert private_id not in stderr
    assert secret_path not in stderr
    assert str(corpus_root) not in stderr
    assert "Benchmark evidence verification failed" in stderr


def test_cli_redacts_missing_private_workbook_path(
    tmp_path, capsys, retrieval_benchmark_cli_mod
):
    corpus_root = _write_corpus(tmp_path, private=True)
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "secret-private-workbook.json"
    output_path = workspace / "report.json"

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            _private_args(workbook_path, output_path, corpus_root),
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    stderr = capsys.readouterr().err
    assert error.value.code == 2
    assert str(workbook_path) not in stderr
    assert "Benchmark input could not be read" in stderr


def test_cli_redacts_private_report_write_failure(
    tmp_path,
    capsys,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    corpus_root = _write_corpus(tmp_path, private=True)
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "authoring-workbook.json"
    output_path = workspace / "secret-missing-parent" / "private-report.json"
    workbook_path.write_text(
        json.dumps(_private_payload(retrieval_benchmark_mod, corpus_root)),
        encoding="utf-8",
    )

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            _private_args(workbook_path, output_path, corpus_root),
            process_runner=lambda *_args: {
                "stdout": json.dumps({"results": [], "low_confidence": False}),
                "elapsed_ms": 1.0,
                "peak_working_set_bytes": 1000,
            },
            token_counter=lambda _text: 0,
        )

    stderr = capsys.readouterr().err
    assert error.value.code == 2
    assert str(output_path) not in stderr
    assert "Private benchmark report could not be written" in stderr


def test_cli_redacts_final_private_corpus_scan_failure(
    tmp_path,
    monkeypatch,
    capsys,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    corpus_root = _write_corpus(tmp_path, private=True)
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "authoring-workbook.json"
    output_path = workspace / "private-report.json"
    workbook_path.write_text(
        json.dumps(_private_payload(retrieval_benchmark_mod, corpus_root)),
        encoding="utf-8",
    )
    original_snapshot_hash = retrieval_benchmark_mod.corpus_snapshot_hash
    calls = 0

    def fail_final_scan(root):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise ValueError(f"private path escaped: {corpus_root}")
        return original_snapshot_hash(root)

    monkeypatch.setattr(
        retrieval_benchmark_mod,
        "corpus_snapshot_hash",
        fail_final_scan,
    )

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            _private_args(workbook_path, output_path, corpus_root),
            process_runner=lambda *_args: {
                "stdout": json.dumps({"results": [], "low_confidence": False}),
                "elapsed_ms": 1.0,
                "peak_working_set_bytes": 1000,
            },
            token_counter=lambda _text: 0,
        )

    stderr = capsys.readouterr().err
    assert error.value.code == 2
    assert str(corpus_root) not in stderr
    assert "Benchmark corpus could not be fingerprinted" in stderr
    assert not output_path.exists()


def test_private_cli_rejects_unexpected_distribution_bucket(
    tmp_path,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
):
    corpus_root = _write_corpus(tmp_path, private=True)
    payload = _private_payload(retrieval_benchmark_mod, corpus_root)
    payload["records"].append(
        {
            "id": "private-v1-extra",
            "split": "evaluation",
            "kind": "unexpected",
            "type": "negative",
            "query": "Extra query",
            "required_groups": [],
            "adjudication_note": "Checked",
            "owner_authored": True,
            "owner_adjudicated": True,
            "adjudicated_by": "Riccardo Tinivella",
            "adjudicated_date": "2026-11-10",
        }
    )
    records = payload["records"]
    payload["manifest"] = _manifest(
        records,
        retrieval_benchmark_mod,
        {
            split: [record["id"] for record in records if record["split"] == split]
            for split in ("development", "evaluation")
        },
        corpus_root,
    )
    workspace = _private_workspace(tmp_path)
    workbook_path = workspace / "extra.json"
    output_path = workspace / "report.json"
    workbook_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            _private_args(workbook_path, output_path, corpus_root),
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2


@pytest.mark.parametrize("invalid_value", ["nan", "inf"])
def test_cli_rejects_nonfinite_measurements(
    tmp_path,
    retrieval_benchmark_cli_mod,
    retrieval_benchmark_mod,
    invalid_value,
):
    corpus_root = _write_corpus(tmp_path)
    queries = _public_queries()
    payload = _add_manifest(
        {"schema_version": 1, "benchmark_version": "public-v1", "queries": queries},
        queries,
        retrieval_benchmark_mod,
        {"public": [query["id"] for query in queries]},
        corpus_root,
    )
    queries_path = tmp_path / "queries.json"
    queries_path.write_text(json.dumps(payload), encoding="utf-8")
    args = [
        "--queries",
        str(queries_path),
        "--backend",
        "grooveseek",
        "--groove-executable",
        "groove",
        "--knowledge-base",
        "corpus",
        "--privacy",
        "public",
        "--benchmark-corpus-root",
        str(corpus_root),
        *MEASUREMENT_ARGS,
    ]
    args[args.index("--full-build-time-ms") + 1] = invalid_value

    with pytest.raises(SystemExit) as error:
        retrieval_benchmark_cli_mod.main(
            args,
            process_runner=lambda *_args: pytest.fail("backend must not run"),
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
