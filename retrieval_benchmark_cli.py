"""Local command interface for evidence-level retrieval benchmarks."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import sqlite3
import subprocess
import unicodedata
from collections import Counter
from datetime import date, datetime
from pathlib import Path

from tokenizers import Tokenizer
import yaml

import retrieval_backends
import retrieval_benchmark


SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class _QmdYamlLoader(yaml.SafeLoader):
    pass


_QmdYamlLoader.yaml_implicit_resolvers = {
    key: [
        (tag, pattern)
        for tag, pattern in resolvers
        if tag
        not in (
            "tag:yaml.org,2002:timestamp",
            "tag:yaml.org,2002:bool",
            "tag:yaml.org,2002:int",
            "tag:yaml.org,2002:float",
        )
    ]
    for key, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}
_QmdYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:bool",
    re.compile(r"^(?:true|false)$", re.IGNORECASE),
    list("tTfF"),
)


def _construct_yaml12_int(loader, node):
    return int(loader.construct_scalar(node), 10)


def _construct_yaml12_float(loader, node):
    value = loader.construct_scalar(node)
    lowered = value.lower()
    if lowered in (".inf", "+.inf"):
        return math.inf
    if lowered == "-.inf":
        return -math.inf
    if lowered in (".nan", "+.nan", "-.nan"):
        return math.nan
    return float(value)


_QmdYamlLoader.add_constructor("tag:yaml.org,2002:int", _construct_yaml12_int)
_QmdYamlLoader.add_constructor("tag:yaml.org,2002:float", _construct_yaml12_float)
_QmdYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:int",
    re.compile(r"^[-+]?[0-9]+$"),
    list("-+0123456789"),
)
_QmdYamlLoader.add_implicit_resolver(
    "tag:yaml.org,2002:float",
    re.compile(
        r"^(?:[-+]?(?:[0-9]+\.[0-9]*|\.[0-9]+)"
        r"(?:[eE][-+]?[0-9]+)?|"
        r"[-+]?[0-9]+(?:[eE][-+]?[0-9]+)|"
        r"[-+]?\.(?:inf|Inf|INF)|[-+]?\.(?:nan|NaN|NAN))$"
    ),
    list("-+0123456789."),
)


def _valid_judgment(passage: object, grades: set[str]) -> bool:
    return (
        isinstance(passage, dict)
        and bool(SHA256_PATTERN.fullmatch(str(passage.get("evidence_id") or "")))
        and isinstance(passage.get("path"), str)
        and bool(passage["path"])
        and isinstance(passage.get("text"), str)
        and bool(passage["text"])
        and isinstance(passage.get("grade"), str)
        and passage["grade"] in grades
    )


def _valid_required_groups(groups: object) -> bool:
    return (
        isinstance(groups, list)
        and bool(groups)
        and all(isinstance(group, list) and bool(group) for group in groups)
        and all(
            _valid_judgment(passage, {"direct", "supporting"})
            for group in groups
            for passage in group
        )
    )


def _valid_irrelevant_judgments(judgments: object) -> bool:
    return (
        isinstance(judgments, list)
        and bool(judgments)
        and all(_valid_judgment(passage, {"irrelevant"}) for passage in judgments)
    )


def load_token_counter(path: Path):
    """Load one pinned tokenizer and return a text-to-token-count function."""
    tokenizer = Tokenizer.from_file(str(path))

    def count_tokens(text: str) -> int:
        return len(tokenizer.encode(text).ids)

    return count_tokens


def _file_sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def _directory_sha256(path: Path | None) -> str | None:
    if path is None or not path.is_dir():
        return None
    files = sorted(
        (item for item in path.rglob("*") if item.is_file()),
        key=lambda item: item.relative_to(path).as_posix(),
    )
    if not files:
        return None
    digest = hashlib.sha256()
    for item in files:
        relative = item.relative_to(path).as_posix().encode("utf-8")
        file_hash = _file_sha256(item)
        if file_hash is None:
            raise OSError("Artifact changed while it was fingerprinted")
        digest.update(relative)
        digest.update(b"\0")
        digest.update(file_hash.encode("ascii"))
        digest.update(b"\0")
    return "sha256:" + digest.hexdigest()


def _executable_sha256(value: str | None) -> str | None:
    if not value:
        return None
    candidate = Path(value)
    if not candidate.is_file():
        resolved = shutil.which(value)
        candidate = Path(resolved) if resolved else candidate
    return _file_sha256(candidate)


def _sqlite_snapshot_sha256(path: Path | None) -> str | None:
    if path is None or not path.is_file():
        return None
    uri = path.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        snapshot = connection.serialize()
    return "sha256:" + hashlib.sha256(snapshot).hexdigest()


def _groove_index_sha256(value: str | None) -> str | None:
    if not value:
        return None
    root = Path(value)
    return _sqlite_snapshot_sha256(root.resolve().parent / ".groove.db")


def _qmd_package_sha256(value: str | None) -> str | None:
    if not value:
        return None
    script = Path(value).resolve()
    for install_root in script.parents:
        if (
            (install_root / "package-lock.json").is_file()
            and (install_root / "node_modules").is_dir()
        ):
            return _directory_sha256(install_root)
    for package_root in script.parents:
        if (package_root / "package.json").is_file():
            return _directory_sha256(package_root)
    return _file_sha256(script)


def _qmd_index_sha256(value: Path | None) -> str | None:
    return _sqlite_snapshot_sha256(value)


def _path_sha256(path: Path | None) -> str | None:
    if path is None:
        return None
    if path.is_dir():
        return _directory_sha256(path)
    return _file_sha256(path)


def _backend_settings_payload(args) -> dict:
    config_artifacts = getattr(args, "backend_config_artifact", []) or []
    model_artifact = getattr(args, "retrieval_model_artifact", None)
    common = {
        "backend": args.backend,
        "limit": args.limit,
        "path_prefix": args.path_prefix,
        "tokenizer": str(args.tokenizer) if args.tokenizer else None,
        "retrieval_model_id": getattr(args, "retrieval_model_id", None),
        "artifact_hashes": {
            "tokenizer": _file_sha256(args.tokenizer),
            "retrieval_model": _path_sha256(model_artifact),
            **{
                f"backend_config_{index}": _path_sha256(path)
                for index, path in enumerate(config_artifacts)
            },
        },
    }
    if args.backend == "grooveseek":
        groove_config = getattr(args, "groove_config", None)
        return {
            **common,
            "executable": args.groove_executable,
            "knowledge_base": args.knowledge_base,
            "groove_config": str(groove_config) if groove_config else None,
            "artifact_hashes": {
                **common["artifact_hashes"],
                "executable": _executable_sha256(args.groove_executable),
                "groove_config": _file_sha256(groove_config),
                "index": _groove_index_sha256(args.knowledge_base),
            },
        }
    qmd_config = getattr(args, "qmd_config", None)
    qmd_index_db = getattr(args, "qmd_index_db", None)
    qmd_build_receipt = getattr(args, "qmd_build_receipt", None)
    try:
        qmd_model_hashes = _qmd_model_artifact_hashes(
            _read_qmd_config_exact(args)
        )
    except (
        AttributeError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ):
        qmd_model_hashes = {
            f"qmd_model_{name}": None
            for name in ("embed", "generate", "rerank")
        }
    return {
        **common,
        "node_executable": args.node_executable,
        "qmd_script": args.qmd_script,
        "index": args.index,
        "collection": args.collection,
        "corpus_root": str(args.corpus_root) if args.corpus_root else None,
        "qmd_config": str(qmd_config) if qmd_config else None,
        "qmd_index_db": str(qmd_index_db) if qmd_index_db else None,
        "artifact_hashes": {
            **common["artifact_hashes"],
            "node_executable": _executable_sha256(args.node_executable),
            "qmd_package": _qmd_package_sha256(args.qmd_script),
            "qmd_config": _file_sha256(qmd_config),
            "index": _qmd_index_sha256(qmd_index_db),
            "build_receipt": _file_sha256(qmd_build_receipt),
            **qmd_model_hashes,
        },
    }


def _read_qmd_config(args) -> dict:
    try:
        payload = yaml.load(
            args.qmd_config.read_text(encoding="utf-8"),
            Loader=_QmdYamlLoader,
        )
    except yaml.YAMLError as error:
        raise ValueError("QMD configuration is invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("QMD configuration must be a mapping")
    return payload


def _qmd_config_json(args, _payload: dict) -> str:
    node_executable = getattr(args, "node_executable", None) or shutil.which("node")
    if not node_executable:
        raise OSError("Node.js is required for QMD configuration hashing")
    qmd_script = getattr(args, "qmd_script", None)
    if not qmd_script:
        raise ValueError("The QMD script is required for configuration hashing")
    source = args.qmd_config.read_bytes()
    completed = subprocess.run(
        [
            str(node_executable),
            "-e",
            "const fs=require('fs');const path=require('path');"
            "const {createRequire}=require('module');"
            "const req=createRequire(path.resolve(process.argv[1]));"
            "const YAML=req('yaml');const value=YAML.parse("
            "fs.readFileSync(0,'utf8'));process.stdout.write(JSON.stringify(value));",
            str(qmd_script),
        ],
        input=source,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )
    if completed.returncode != 0:
        raise ValueError("QMD configuration could not be canonicalized")
    return completed.stdout.decode("utf-8")


def _read_qmd_config_exact(args) -> dict:
    try:
        payload = json.loads(_qmd_config_json(args, {}))
    except json.JSONDecodeError as error:
        raise ValueError("QMD configuration is invalid") from error
    if not isinstance(payload, dict):
        raise ValueError("QMD configuration must be a mapping")
    return payload


def _qmd_config_has_update_hooks(payload: dict) -> bool:
    collections = payload.get("collections")
    return isinstance(collections, dict) and any(
        isinstance(collection, dict) and collection.get("update") is not None
        for collection in collections.values()
    )


def _qmd_config_uses_local_models(payload: dict) -> bool:
    models = payload.get("models")
    return isinstance(models, dict) and all(
        isinstance(models.get(name), str)
        and Path(models[name]).expanduser().is_absolute()
        and Path(models[name]).expanduser().is_file()
        for name in ("embed", "generate", "rerank")
    )


def _qmd_model_artifact_hashes(payload: dict) -> dict[str, str | None]:
    models = payload.get("models")
    if not isinstance(models, dict):
        return {
            f"qmd_model_{name}": None
            for name in ("embed", "generate", "rerank")
        }
    return {
        f"qmd_model_{name}": _path_sha256(Path(models[name]).expanduser())
        if isinstance(models.get(name), str) and models[name]
        else None
        for name in ("embed", "generate", "rerank")
    }


def _qmd_config_uses_model_artifact(args, payload: dict) -> bool:
    if args.qmd_config.name != f"{args.index}.yml":
        return False
    models = payload.get("models")
    if not isinstance(models, dict):
        return False
    if any(
        not isinstance(models.get(name), str) or not models[name]
        for name in ("embed", "generate", "rerank")
    ):
        return False
    configured = models.get("embed")
    configured_path = Path(configured).expanduser()
    return (
        configured_path.is_absolute()
        and configured_path.resolve() == args.retrieval_model_artifact.resolve()
        and args.retrieval_model_id == configured
    )


def _qmd_embedding_fingerprint(model: str) -> str:
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


def _corpus_documents(root: Path, path_prefix: str | None = None) -> dict:
    documents = {}
    for canonical_path, path in retrieval_benchmark._corpus_markdown_paths(root):
        mapped_path = (
            retrieval_benchmark._canonical_document_path(
                f"{path_prefix}/{canonical_path}"
            )
            if path_prefix
            else canonical_path
        )
        source_bytes = path.read_bytes()
        normalized = unicodedata.normalize(
            "NFC",
            source_bytes.decode("utf-8").replace("\r\n", "\n").replace("\r", "\n"),
        ).encode()
        documents[mapped_path] = {
            "raw_hash": hashlib.sha256(source_bytes).hexdigest(),
            "normalized_hash": hashlib.sha256(normalized).hexdigest(),
        }
    return documents


def _backend_source_matches_benchmark(args, backend_root: Path) -> bool:
    backend_documents = _corpus_documents(backend_root, args.path_prefix)
    benchmark_documents = _corpus_documents(args.benchmark_corpus_root)
    return {
        path: item["normalized_hash"] for path, item in backend_documents.items()
    } == {
        path: item["normalized_hash"] for path, item in benchmark_documents.items()
    }


def _qmd_build_receipt_payload(args) -> dict:
    config_payload = _read_qmd_config_exact(args)
    return {
        "schema_version": "glassgraph.qmd-build-receipt.v1",
        "qmd_package_sha256": _qmd_package_sha256(args.qmd_script),
        "qmd_config_sha256": _file_sha256(args.qmd_config),
        "qmd_index_sha256": _qmd_index_sha256(args.qmd_index_db),
        "retrieval_model_id": args.retrieval_model_id,
        "retrieval_model_artifact_sha256": _path_sha256(
            args.retrieval_model_artifact
        ),
        "qmd_model_artifact_hashes": _qmd_model_artifact_hashes(config_payload),
        "corpus_documents": {
            path: item["raw_hash"]
            for path, item in _corpus_documents(args.corpus_root).items()
        },
    }


def _qmd_active_embedding_state(args) -> dict[str, datetime]:
    fingerprint = _qmd_embedding_fingerprint(args.retrieval_model_id)
    uri = args.qmd_index_db.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        values = [
            row
            for row in connection.execute(
                "SELECT cv.hash, cv.seq, cv.embedded_at "
                "FROM content_vectors AS cv "
                "JOIN documents AS d ON d.hash = cv.hash "
                "WHERE d.collection = ? AND d.active = 1 "
                "AND cv.model = ? AND cv.embed_fingerprint = ?",
                (
                    args.collection,
                    args.retrieval_model_id,
                    fingerprint,
                ),
            )
        ]
    if any(
        not isinstance(document_hash, str)
        or not isinstance(sequence, int)
        or not isinstance(value, str)
        for document_hash, sequence, value in values
    ):
        raise ValueError("QMD embedding timestamps are invalid")
    state = {
        f"{document_hash}_{sequence}": datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )
        for document_hash, sequence, value in values
    }
    if len(state) != len(values):
        raise ValueError("QMD embedding identities are not unique")
    return state


def _qmd_active_embedding_times(args) -> list[datetime]:
    return list(_qmd_active_embedding_state(args).values())


def _qmd_embedding_state_sha256(state: dict[str, datetime]) -> str:
    serialized = json.dumps(
        {
            key: value.isoformat()
            for key, value in sorted(state.items())
        },
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(serialized).hexdigest()


def _qmd_build_proof_is_valid(args, proof: object) -> bool:
    if not isinstance(proof, dict):
        return False
    try:
        state = _qmd_active_embedding_state(args)
    except (KeyError, OSError, sqlite3.Error, TypeError, ValueError):
        return False
    current_index_hash = _qmd_index_sha256(args.qmd_index_db)
    return (
        proof.get("schema_version") == "glassgraph.qmd-build-proof.v1"
        and isinstance(proof.get("active_chunk_count"), int)
        and proof["active_chunk_count"] == len(state)
        and proof.get("refreshed_chunk_count") == len(state)
        and bool(state)
        and proof.get("post_index_sha256") == current_index_hash
        and proof.get("pre_index_sha256") != current_index_hash
        and proof.get("post_embedding_state_sha256")
        == _qmd_embedding_state_sha256(state)
        and proof.get("pre_embedding_state_sha256")
        != proof.get("post_embedding_state_sha256")
    )


def _write_qmd_build_receipt(
    path: Path,
    args,
    build_proof: dict,
    *,
    payload: dict | None = None,
) -> None:
    """Record the exact QMD runtime, model, corpus, and index built together."""
    payload = dict(payload or _qmd_build_receipt_payload(args))
    payload["build_proof"] = build_proof
    with path.open("x", encoding="utf-8", newline="\n") as target:
        json.dump(payload, target, ensure_ascii=False, indent=2, sort_keys=True)
        target.write("\n")


def _qmd_build_receipt_is_valid(args) -> bool:
    try:
        payload = json.loads(args.qmd_build_receipt.read_text(encoding="utf-8"))
        proof = payload.pop("build_proof", None)
        return payload == _qmd_build_receipt_payload(
            args
        ) and _qmd_build_proof_is_valid(args, proof)
    except (
        AttributeError,
        json.JSONDecodeError,
        OSError,
        sqlite3.Error,
        subprocess.SubprocessError,
        TypeError,
        UnicodeError,
        ValueError,
    ):
        return False


def _groove_index_is_ready(args) -> bool:
    source_root = Path(args.knowledge_base).resolve()
    try:
        if not _backend_source_matches_benchmark(args, source_root):
            return False
        expected = {
            path: item["raw_hash"]
            for path, item in _corpus_documents(source_root).items()
        }
        database = source_root.parent / ".groove.db"
        uri = database.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type = 'table'"
                )
            }
            if not {"documents", "chunks", "vec_chunks_rowids"}.issubset(tables):
                return False
            indexed = {
                retrieval_benchmark._canonical_document_path(path): content_hash
                for path, content_hash in connection.execute(
                    "SELECT path, content_hash FROM documents"
                )
            }
            unchunked = connection.execute(
                "SELECT COUNT(*) FROM documents AS d "
                "WHERE NOT EXISTS ("
                "SELECT 1 FROM chunks AS c WHERE c.document_id = d.id"
                ")"
            ).fetchone()[0]
            missing_vectors = connection.execute(
                "SELECT COUNT(*) FROM chunks AS c "
                "LEFT JOIN vec_chunks_rowids AS vr ON vr.rowid = c.id "
                "WHERE vr.rowid IS NULL"
            ).fetchone()[0]
    except (OSError, UnicodeError, ValueError, sqlite3.Error):
        return False
    return bool(expected) and indexed == expected and unchunked == 0 and missing_vectors == 0


def _qmd_index_is_ready(args, config_payload: dict) -> bool:
    required_tables = {
        "store_config",
        "documents",
        "content_vectors",
        "vectors_vec",
        "vectors_vec_rowids",
    }
    try:
        config_hash = hashlib.sha256(
            _qmd_config_json(args, config_payload).encode("utf-8")
        ).hexdigest()
        source_root = Path(args.corpus_root).resolve()
        if not _backend_source_matches_benchmark(args, source_root):
            return False
        expected_documents = {
            path: item["raw_hash"]
            for path, item in _corpus_documents(source_root).items()
        }
        expected_fingerprint = _qmd_embedding_fingerprint(
            args.retrieval_model_id
        )
        uri = args.qmd_index_db.resolve().as_uri() + "?mode=ro"
        with sqlite3.connect(uri, uri=True) as connection:
            tables = {
                row[0]
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
                )
            }
            if not required_tables.issubset(tables):
                return False
            stored_hash = connection.execute(
                "SELECT value FROM store_config WHERE key = 'config_hash'"
            ).fetchone()
            if stored_hash is None or stored_hash[0] != config_hash:
                return False
            indexed_documents = {
                retrieval_benchmark._canonical_document_path(path): content_hash
                for path, content_hash in connection.execute(
                    "SELECT path, hash FROM documents "
                    "WHERE collection = ? AND active = 1",
                    (args.collection,),
                )
            }
            if indexed_documents != expected_documents:
                return False
            vector_columns = {
                row[1]
                for row in connection.execute("PRAGMA table_info(content_vectors)")
            }
            if not {"seq", "embed_fingerprint", "embedded_at"}.issubset(
                vector_columns
            ):
                return False
            covered_documents = connection.execute(
                "SELECT COUNT(*) FROM documents AS d "
                "WHERE d.collection = ? AND d.active = 1 "
                "AND EXISTS ("
                "SELECT 1 FROM content_vectors AS cv "
                "WHERE cv.hash = d.hash AND cv.model = ? "
                "AND cv.embed_fingerprint = ? "
                "GROUP BY cv.hash, cv.model, cv.embed_fingerprint "
                "HAVING MIN(cv.total_chunks) = MAX(cv.total_chunks) "
                "AND COUNT(*) = MAX(cv.total_chunks) "
                "AND COUNT(DISTINCT cv.seq) = MAX(cv.total_chunks) "
                "AND MIN(cv.seq) = 0 "
                "AND MAX(cv.seq) = MAX(cv.total_chunks) - 1 "
                "AND MAX(cv.total_chunks) > 0"
                ")",
                (
                    args.collection,
                    args.retrieval_model_id,
                    expected_fingerprint,
                ),
            ).fetchone()[0]
            unexpected_vectors = connection.execute(
                "SELECT COUNT(*) FROM content_vectors AS cv "
                "JOIN documents AS d ON d.hash = cv.hash "
                "WHERE d.collection = ? AND d.active = 1 "
                "AND (cv.model <> ? OR cv.embed_fingerprint <> ?)",
                (
                    args.collection,
                    args.retrieval_model_id,
                    expected_fingerprint,
                ),
            ).fetchone()[0]
            missing_vectors = connection.execute(
                "SELECT COUNT(*) FROM content_vectors AS cv "
                "JOIN documents AS d ON d.hash = cv.hash "
                "LEFT JOIN vectors_vec_rowids AS vr "
                "ON vr.id = cv.hash || '_' || cv.seq "
                "WHERE d.collection = ? AND d.active = 1 AND cv.model = ? "
                "AND cv.embed_fingerprint = ? "
                "AND vr.id IS NULL",
                (
                    args.collection,
                    args.retrieval_model_id,
                    expected_fingerprint,
                ),
            ).fetchone()[0]
    except (
        OSError,
        sqlite3.Error,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ):
        return False
    return (
        bool(expected_documents)
        and covered_documents == len(expected_documents)
        and unexpected_vectors == 0
        and missing_vectors == 0
    )


def validate_private_workbook(payload: dict) -> None:
    expected = {
        ("development", "positive"): 30,
        ("development", "negative"): 10,
        ("evaluation", "positive"): 15,
        ("evaluation", "negative"): 5,
    }
    records = payload.get("records", [])
    if not isinstance(records, list) or any(
        not isinstance(record, dict)
        or not isinstance(record.get("split"), str)
        or not isinstance(record.get("kind"), str)
        for record in records
    ):
        raise ValueError("Private benchmark distribution contains unexpected records")
    counts = Counter((record["split"], record["kind"]) for record in records)
    if len(records) != 60 or set(counts) != set(expected):
        raise ValueError("Private benchmark distribution contains unexpected records")
    missing = [
        f"{split} {kind} {counts[(split, kind)]}/{count}"
        for (split, kind), count in expected.items()
        if counts[(split, kind)] != count
    ]
    if missing:
        raise ValueError("Private benchmark distribution is incomplete: " + ", ".join(missing))
    unapproved_count = sum(
        record.get("owner_authored") is not True
        or record.get("owner_adjudicated") is not True
        for record in records
    )
    if unapproved_count:
        raise ValueError(
            "Private benchmark records need owner authorship and adjudication: "
            f"{unapproved_count} invalid record(s)"
        )
    invalid_judgments = 0
    for record in records:
        groups = record.get("required_groups")
        irrelevant = record.get("irrelevant")
        if record.get("kind") == "positive":
            valid = _valid_required_groups(groups) and _valid_irrelevant_judgments(
                irrelevant
            )
        else:
            valid = groups == [] and bool(record.get("adjudication_note"))
        invalid_judgments += not valid
    if invalid_judgments:
        raise ValueError(
            "Private benchmark judgments are invalid: "
            f"{invalid_judgments} invalid record(s)"
        )


def _path_chain_has_nested_git(path: Path, vault_root: Path) -> bool:
    current = path
    while current != vault_root:
        if (current / ".git").exists():
            return True
        if current.parent == current:
            return True
        current = current.parent
    return False


def _private_backend_paths(args) -> list[Path]:
    extra_artifacts = [
        path.resolve()
        for path in (getattr(args, "backend_config_artifact", []) or [])
    ]
    if args.backend == "grooveseek":
        knowledge_base = Path(args.knowledge_base).resolve()
        return [
            knowledge_base,
            knowledge_base.parent / ".groove.db",
            args.groove_config.resolve(),
            *extra_artifacts,
        ]
    return [
        args.corpus_root.resolve(),
        args.qmd_config.resolve(),
        args.qmd_index_db.resolve(),
        args.qmd_build_receipt.resolve(),
        *extra_artifacts,
    ]


def _git_command(
    vault_root: Path,
    arguments: list[str],
    *,
    input_data: bytes | None = None,
):
    return subprocess.run(
        ["git", "-C", str(vault_root), *arguments],
        check=False,
        input=input_data,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5,
    )


def _private_git_paths_are_unpublished(
    vault_root: Path,
    workspace: Path,
    paths: list[Path],
) -> bool:
    git_markers = [
        path / ".git"
        for path in (vault_root, *vault_root.parents)
        if (path / ".git").exists()
    ]
    if not git_markers:
        return True
    try:
        repository = _git_command(vault_root, ["rev-parse", "--show-toplevel"])
    except (OSError, subprocess.SubprocessError):
        return False
    if repository.returncode != 0:
        return not (vault_root / ".git").exists()
    try:
        repository_root = Path(
            repository.stdout.decode("utf-8").strip()
        ).resolve()
    except (OSError, UnicodeError, ValueError):
        return False
    if repository_root != vault_root:
        return False

    workspace_relative = workspace.relative_to(repository_root).as_posix()
    tracked = _git_command(
        repository_root,
        ["ls-files", "-z", "--", workspace_relative],
    )
    if tracked.returncode != 0 or tracked.stdout:
        return False

    candidates = set(paths)
    for path in paths:
        if path.is_dir():
            candidates.update(item.resolve() for item in path.rglob("*") if item.is_file())
    relative_paths = []
    for path in candidates:
        try:
            relative_paths.append(path.relative_to(repository_root).as_posix())
        except ValueError:
            return False
    check_input = b"\0".join(
        relative.encode("utf-8") for relative in relative_paths
    ) + b"\0"
    ignored = _git_command(
        repository_root,
        ["check-ignore", "--no-index", "-z", "--stdin"],
        input_data=check_input,
    )
    if ignored.returncode not in (0, 1):
        return False
    ignored_paths = {
        value.decode("utf-8")
        for value in ignored.stdout.split(b"\0")
        if value
    }
    return ignored_paths == set(relative_paths)


def _private_paths_are_vault_local(args) -> bool:
    try:
        workspace = args.queries.resolve().parent
        if tuple(part.casefold() for part in workspace.parts[-4:]) != (
            ".glassgraph",
            "benchmarks",
            "private",
            "v1",
        ):
            return False
        if str(workspace.anchor).startswith("\\\\"):
            return False
        vault_root = workspace.parents[3]
        corpus_root = args.benchmark_corpus_root.resolve()
        output_parent = args.output.resolve().parent
        backend_paths = _private_backend_paths(args)
        private_paths = [
            args.queries.resolve(),
            args.output.resolve(),
            *backend_paths,
        ]
        corpus_root.relative_to(vault_root)
        args.output.resolve().relative_to(workspace)
        for path in backend_paths:
            path.relative_to(workspace)
        if any(
            _path_chain_has_nested_git(path, vault_root)
            for path in (workspace, output_parent, corpus_root, *backend_paths)
        ):
            return False
        if not _private_git_paths_are_unpublished(
            vault_root,
            workspace,
            private_paths,
        ):
            return False
    except (
        AttributeError,
        IndexError,
        OSError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
    ):
        return False
    return True


def validate_records(records: list[dict]) -> None:
    if not isinstance(records, list) or any(
        not isinstance(record, dict) for record in records
    ):
        raise ValueError("Benchmark records are invalid")
    record_ids = [record.get("id") for record in records]
    if any(not isinstance(record_id, str) or not record_id for record_id in record_ids):
        raise ValueError("Every benchmark record needs a nonempty ID")
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("Benchmark record IDs must be unique")
    invalid_records = 0
    for record in records:
        groups = record.get("required_groups")
        irrelevant = record.get("irrelevant")
        if not isinstance(groups, list) or (
            irrelevant is not None and not isinstance(irrelevant, list)
        ):
            invalid_records += 1
            continue
        relevant_ids = {
            str(judgment.get("evidence_id"))
            for group in groups
            if isinstance(group, list)
            for judgment in group
            if isinstance(judgment, dict)
        }
        irrelevant_ids = {
            str(judgment.get("evidence_id"))
            for judgment in irrelevant or []
            if isinstance(judgment, dict)
        }
        valid = (
            isinstance(record.get("query"), str)
            and bool(record["query"].strip())
            and isinstance(groups, list)
            and not ("irrelevant" in record and irrelevant is None)
            and relevant_ids.isdisjoint(irrelevant_ids)
            and (
                (
                    not groups
                    and (
                        irrelevant in (None, [])
                        or _valid_irrelevant_judgments(irrelevant)
                    )
                )
                or (
                    _valid_required_groups(groups)
                    and _valid_irrelevant_judgments(irrelevant)
                )
            )
        )
        invalid_records += not valid
    if invalid_records:
        raise ValueError(
            f"Benchmark records are invalid: {invalid_records} invalid record(s)"
        )


def validate_manifest(
    payload: dict,
    records: list[dict],
    privacy: str,
    corpus_root: Path,
) -> None:
    manifest = payload.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("The benchmark manifest is missing")
    if payload.get("schema_version") != 1 or manifest.get("schema_version") != 1:
        raise ValueError("The benchmark schema version must be 1")
    if not SHA256_PATTERN.fullmatch(str(manifest.get("corpus_snapshot_hash") or "")):
        raise ValueError("The benchmark corpus snapshot hash is invalid")
    try:
        current_corpus_hash = retrieval_benchmark.corpus_snapshot_hash(corpus_root)
    except (OSError, UnicodeError) as error:
        raise ValueError("The benchmark corpus cannot be verified") from error
    if manifest["corpus_snapshot_hash"] != current_corpus_hash:
        raise ValueError("The benchmark corpus snapshot hash does not match")
    expected_version = retrieval_benchmark.benchmark_version(
        privacy,
        records,
        current_corpus_hash,
    )
    if payload.get("benchmark_version") != expected_version:
        raise ValueError("The benchmark version is invalid")
    if manifest.get("query_set_hash") != retrieval_benchmark.query_set_hash(records):
        raise ValueError("The benchmark query-set hash does not match")
    if manifest.get("judgment_set_hash") != retrieval_benchmark.judgment_set_hash(records):
        raise ValueError("The benchmark judgment-set hash does not match")
    membership = manifest.get("split_membership")
    expected_membership = (
        {
            split: [record["id"] for record in records if record.get("split") == split]
            for split in ("development", "evaluation")
        }
        if privacy == "private"
        else {"public": [record["id"] for record in records]}
    )
    if membership != expected_membership:
        raise ValueError("The benchmark split membership does not match")
    try:
        date.fromisoformat(str(manifest.get("adjudication_date") or ""))
    except ValueError as error:
        raise ValueError("The benchmark adjudication date is invalid")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--queries", type=Path, required=True)
    parser.add_argument("--backend", choices=["grooveseek", "qmd"], required=True)
    parser.add_argument("--privacy", choices=["public", "private"], required=True)
    parser.add_argument("--split", choices=["development", "evaluation"])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--limit", type=int, default=10)
    parser.add_argument("--groove-executable")
    parser.add_argument("--groove-config", type=Path)
    parser.add_argument("--knowledge-base")
    parser.add_argument("--node-executable")
    parser.add_argument("--qmd-script")
    parser.add_argument("--qmd-config", type=Path)
    parser.add_argument("--qmd-index-db", type=Path)
    parser.add_argument("--qmd-build-receipt", type=Path)
    parser.add_argument("--index")
    parser.add_argument("--collection")
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--benchmark-corpus-root", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path)
    parser.add_argument("--retrieval-model-id")
    parser.add_argument("--retrieval-model-artifact", type=Path)
    parser.add_argument(
        "--backend-config-artifact",
        type=Path,
        action="append",
        default=[],
    )
    parser.add_argument("--path-prefix")
    parser.add_argument("--settings-lock")
    parser.add_argument("--setup-time-ms", type=float, required=True)
    parser.add_argument("--full-build-time-ms", type=float, required=True)
    parser.add_argument("--no-change-update-ms", type=float, required=True)
    parser.add_argument("--one-file-update-ms", type=float, required=True)
    parser.add_argument("--derived-index-size-bytes", type=int, required=True)
    parser.add_argument("--offline-verified", action="store_true", required=True)
    return parser


def main(argv=None, *, process_runner=None, token_counter=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    measurements = (
        args.setup_time_ms,
        args.full_build_time_ms,
        args.no_change_update_ms,
        args.one_file_update_ms,
    )
    if (
        any(not math.isfinite(value) or value < 0 for value in measurements)
        or args.derived_index_size_bytes <= 0
    ):
        parser.error("Benchmark measurements must be nonnegative and index size must be positive")
    if args.limit < 10:
        parser.error("The result limit must be at least 10 for Recall@10 and nDCG@10")
    if args.backend == "grooveseek" and (
        not args.groove_executable or not args.knowledge_base
    ):
        parser.error("GrooveSeek requires --groove-executable and --knowledge-base")
    if args.backend == "qmd" and any(
        not value
        for value in (
            args.node_executable,
            args.qmd_script,
            args.index,
            args.collection,
            args.corpus_root,
        )
    ):
        parser.error(
            "QMD requires --node-executable, --qmd-script, --index, "
            "--collection, and --corpus-root"
        )
    if args.privacy == "private":
        if args.split is None or args.output is None:
            parser.error("Private benchmarks require --split and --output")
        if not _private_paths_are_vault_local(args):
            parser.error(
                "Private benchmark inputs and reports must stay in the "
                "vault-side private workspace"
            )
        if args.queries.resolve() == args.output.resolve():
            parser.error("The private report path must differ from the workbook path")
        if args.output.exists():
            parser.error("The private report path already exists")
        if not args.retrieval_model_id or args.retrieval_model_artifact is None:
            parser.error(
                "Private benchmarks require --retrieval-model-id and "
                "--retrieval-model-artifact"
            )
    if token_counter is None and args.tokenizer is None:
        parser.error("Production benchmark runs require --tokenizer")
    try:
        settings_identity = _backend_settings_payload(args)
    except (OSError, UnicodeError, sqlite3.Error):
        parser.error("Benchmark artifacts could not be fingerprinted")
    actual_settings_lock = retrieval_benchmark.backend_settings_lock(
        settings_identity
    )
    if process_runner is None:
        process_runner = retrieval_backends.run_process
    if token_counter is None:
        try:
            token_counter = load_token_counter(args.tokenizer)
        except Exception:
            parser.error("Tokenizer could not be loaded")
    try:
        payload = json.loads(args.queries.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        parser.error("Benchmark input could not be read")
    if not isinstance(payload, dict):
        parser.error("Benchmark input is invalid")
    try:
        records = (
            payload.get("records", [])
            if args.privacy == "private"
            else payload.get("queries", [])
        )
        validate_records(records)
        if args.privacy == "private":
            validate_private_workbook(payload)
        validate_manifest(
            payload,
            records,
            args.privacy,
            args.benchmark_corpus_root,
        )
    except ValueError as error:
        parser.error(str(error))
    try:
        retrieval_benchmark.validate_evidence_judgments(
            records,
            args.benchmark_corpus_root,
        )
    except (OSError, UnicodeError, ValueError):
        parser.error("Benchmark evidence verification failed")
    if not args.retrieval_model_id or args.retrieval_model_artifact is None:
        parser.error(
            "Benchmarks require --retrieval-model-id and "
            "--retrieval-model-artifact"
        )
    if args.backend == "grooveseek" and (
        args.groove_config is None
        or not args.retrieval_model_artifact.is_dir()
    ):
        parser.error(
            "GrooveSeek benchmarks require --groove-config and "
            "a model-cache directory"
        )
    if args.backend == "grooveseek" and not _groove_index_is_ready(args):
        parser.error(
            "The GrooveSeek benchmark index does not match the frozen corpus"
        )
    if args.backend == "qmd" and (
        args.qmd_config is None
        or args.qmd_index_db is None
        or args.qmd_build_receipt is None
        or not args.retrieval_model_artifact.is_file()
    ):
        parser.error(
            "QMD benchmarks require --qmd-config, --qmd-index-db, "
            "--qmd-build-receipt, and a model file"
        )
    if args.backend == "qmd":
        try:
            qmd_config_payload = _read_qmd_config_exact(args)
            model_is_pinned = _qmd_config_uses_model_artifact(
                args,
                qmd_config_payload,
            )
        except (
            OSError,
            subprocess.SubprocessError,
            UnicodeError,
            ValueError,
            yaml.YAMLError,
        ):
            parser.error("The QMD benchmark configuration is invalid")
        if not model_is_pinned:
            parser.error(
                "The QMD configuration must use the pinned model artifact"
            )
        if not _qmd_build_receipt_is_valid(args):
            parser.error(
                "The QMD build receipt does not match the runtime, model, "
                "corpus, and index"
            )
        if not _qmd_index_is_ready(args, qmd_config_payload):
            parser.error(
                "The QMD benchmark index is not ready for pinned hybrid retrieval"
            )
    if any(
        not fingerprint
        for fingerprint in settings_identity["artifact_hashes"].values()
    ):
        parser.error("Benchmark artifact fingerprints are incomplete")
    if args.privacy == "private" and args.split == "evaluation":
        locked_settings = payload.get("manifest", {}).get(
            "locked_backend_settings"
        )
        expected_lock = (
            locked_settings.get(args.backend)
            if isinstance(locked_settings, dict)
            else None
        )
        if (
            not SHA256_PATTERN.fullmatch(str(args.settings_lock or ""))
            or args.settings_lock != expected_lock
            or args.settings_lock != actual_settings_lock
        ):
            parser.error("Private evaluation requires locked backend settings")
    if args.privacy == "private":
        queries = [
            record for record in records if record.get("split") == args.split
        ]
    else:
        queries = records
        positive_count = sum(bool(query.get("required_groups")) for query in queries)
        negative_count = len(queries) - positive_count
        if positive_count < 5 or negative_count < 5:
            parser.error(
                "Public reports require at least five positive and five negative queries"
            )
    queries = sorted(queries, key=lambda record: record["id"])

    if args.backend == "grooveseek":
        adapter = retrieval_backends.GrooveSeekAdapter(
            executable=args.groove_executable,
            knowledge_base=args.knowledge_base,
            process_runner=process_runner,
            token_counter=token_counter,
            path_prefix=args.path_prefix,
            config=args.groove_config,
            model=args.retrieval_model_id,
            model_cache=args.retrieval_model_artifact,
        )
    else:
        adapter = retrieval_backends.QmdAdapter(
            node_executable=args.node_executable,
            qmd_script=args.qmd_script,
            index=args.index,
            collection=args.collection,
            corpus_root=args.corpus_root,
            process_runner=process_runner,
            token_counter=token_counter,
            path_prefix=args.path_prefix,
            index_db=args.qmd_index_db,
            config_dir=(args.qmd_config.parent if args.qmd_config else None),
            embed_model=args.retrieval_model_id,
        )

    try:
        runs = {
            query["id"]: adapter.query(query["query"], limit=args.limit)
            for query in queries
        }
    except (
        AttributeError,
        KeyError,
        OSError,
        TypeError,
        UnicodeError,
        ValueError,
        RuntimeError,
    ):
        parser.error("Retrieval backend execution failed")
    try:
        final_settings_identity = _backend_settings_payload(args)
    except (OSError, UnicodeError, sqlite3.Error):
        parser.error("Benchmark artifacts could not be fingerprinted")
    if final_settings_identity != settings_identity:
        parser.error("Benchmark artifacts changed during execution")
    try:
        retrieval_benchmark.verify_evidence_hits(
            queries,
            runs,
            args.benchmark_corpus_root,
        )
    except (OSError, UnicodeError, ValueError):
        parser.error("Evidence verification failed for the benchmark corpus")
    try:
        final_corpus_hash = retrieval_benchmark.corpus_snapshot_hash(
            args.benchmark_corpus_root
        )
    except (OSError, UnicodeError, ValueError):
        parser.error("Benchmark corpus could not be fingerprinted")
    if final_corpus_hash != payload["manifest"]["corpus_snapshot_hash"]:
        parser.error("Benchmark corpus changed during execution")
    summary = retrieval_benchmark.evaluate(queries, runs)
    report = {
        "schema_version": 1,
        "backend": args.backend,
        "privacy": args.privacy,
        "split": args.split,
        "query_count": len(queries),
        "benchmark": {
            "version": payload["benchmark_version"],
            "corpus_snapshot_hash": payload["manifest"]["corpus_snapshot_hash"],
            "corpus_verified": True,
            "settings_lock": actual_settings_lock,
            "artifact_hashes": settings_identity["artifact_hashes"],
        },
        "measurements": {
            "setup_time_ms": args.setup_time_ms,
            "full_build_time_ms": args.full_build_time_ms,
            "no_change_update_ms": args.no_change_update_ms,
            "one_file_update_ms": args.one_file_update_ms,
            "derived_index_size_bytes": args.derived_index_size_bytes,
            "offline_verified": args.offline_verified,
        },
        "summary": summary,
    }
    serialized = json.dumps(
        report,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
    )
    if args.privacy == "private":
        try:
            with args.output.open("x", encoding="utf-8", newline="\n") as output_file:
                output_file.write(serialized + "\n")
        except OSError:
            parser.error("Private benchmark report could not be written")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
