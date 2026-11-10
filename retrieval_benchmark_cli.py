"""Local command interface for evidence-level retrieval benchmarks."""
from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from datetime import date
from pathlib import Path

from tokenizers import Tokenizer

import retrieval_backends
import retrieval_benchmark


SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _valid_judgment(passage: object, grades: set[str]) -> bool:
    return (
        isinstance(passage, dict)
        and bool(SHA256_PATTERN.fullmatch(str(passage.get("evidence_id") or "")))
        and isinstance(passage.get("path"), str)
        and bool(passage["path"])
        and isinstance(passage.get("text"), str)
        and bool(passage["text"])
        and passage.get("grade") in grades
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


def _backend_settings_payload(args) -> dict:
    common = {
        "backend": args.backend,
        "limit": args.limit,
        "path_prefix": args.path_prefix,
        "tokenizer": str(args.tokenizer) if args.tokenizer else None,
    }
    if args.backend == "grooveseek":
        return {
            **common,
            "executable": args.groove_executable,
            "knowledge_base": args.knowledge_base,
        }
    return {
        **common,
        "node_executable": args.node_executable,
        "qmd_script": args.qmd_script,
        "index": args.index,
        "collection": args.collection,
        "corpus_root": str(args.corpus_root) if args.corpus_root else None,
    }


def validate_private_workbook(payload: dict) -> None:
    expected = {
        ("development", "positive"): 30,
        ("development", "negative"): 10,
        ("evaluation", "positive"): 15,
        ("evaluation", "negative"): 5,
    }
    counts = Counter(
        (record.get("split"), record.get("kind"))
        for record in payload.get("records", [])
    )
    if len(payload.get("records", [])) != 60 or set(counts) != set(expected):
        raise ValueError("Private benchmark distribution contains unexpected records")
    missing = [
        f"{split} {kind} {counts[(split, kind)]}/{count}"
        for (split, kind), count in expected.items()
        if counts[(split, kind)] != count
    ]
    if missing:
        raise ValueError("Private benchmark distribution is incomplete: " + ", ".join(missing))
    records = payload.get("records", [])
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


def validate_records(records: list[dict]) -> None:
    record_ids = [record.get("id") for record in records]
    if any(not isinstance(record_id, str) or not record_id for record_id in record_ids):
        raise ValueError("Every benchmark record needs a nonempty ID")
    if len(set(record_ids)) != len(record_ids):
        raise ValueError("Benchmark record IDs must be unique")
    invalid_records = 0
    for record in records:
        groups = record.get("required_groups")
        irrelevant = record.get("irrelevant")
        relevant_ids = {
            judgment.get("evidence_id")
            for group in groups or []
            for judgment in group
            if isinstance(judgment, dict)
        }
        irrelevant_ids = {
            judgment.get("evidence_id")
            for judgment in irrelevant or []
            if isinstance(judgment, dict)
        }
        valid = (
            isinstance(record.get("query"), str)
            and bool(record["query"].strip())
            and isinstance(groups, list)
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
    expected_version = retrieval_benchmark.benchmark_version(privacy, records)
    if payload.get("benchmark_version") != expected_version:
        raise ValueError("The benchmark version is invalid")
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
    parser.add_argument("--knowledge-base")
    parser.add_argument("--node-executable")
    parser.add_argument("--qmd-script")
    parser.add_argument("--index")
    parser.add_argument("--collection")
    parser.add_argument("--corpus-root", type=Path)
    parser.add_argument("--benchmark-corpus-root", type=Path, required=True)
    parser.add_argument("--tokenizer", type=Path)
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
    actual_settings_lock = retrieval_benchmark.backend_settings_lock(
        _backend_settings_payload(args)
    )
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
    if args.privacy == "private":
        if args.split is None or args.output is None:
            parser.error("Private benchmarks require --split and --output")
        if args.queries.resolve() == args.output.resolve():
            parser.error("The private report path must differ from the workbook path")
        if args.output.exists():
            parser.error("The private report path already exists")
    if token_counter is None and args.tokenizer is None:
        parser.error("Production benchmark runs require --tokenizer")
    if process_runner is None:
        process_runner = retrieval_backends.run_process
    if token_counter is None:
        token_counter = load_token_counter(args.tokenizer)
    try:
        payload = json.loads(args.queries.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        parser.error("Benchmark input could not be read")
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
    if args.privacy == "private" and args.split == "evaluation":
        expected_lock = (
            payload.get("manifest", {})
            .get("locked_backend_settings", {})
            .get(args.backend)
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
        )

    try:
        runs = {
            query["id"]: adapter.query(query["query"], limit=args.limit)
            for query in queries
        }
    except RuntimeError:
        parser.error("Retrieval backend execution failed")
    try:
        retrieval_benchmark.verify_evidence_hits(
            queries,
            runs,
            args.benchmark_corpus_root,
        )
    except (OSError, UnicodeError, ValueError):
        parser.error("Evidence verification failed for the benchmark corpus")
    summary = retrieval_benchmark.evaluate(queries, runs)
    report = {
        "schema_version": 1,
        "backend": args.backend,
        "privacy": args.privacy,
        "split": args.split,
        "query_count": len(queries),
        "benchmark": {
            "version": payload["benchmark_version"],
            "corpus_verified": True,
            "settings_lock": actual_settings_lock,
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
        with args.output.open("x", encoding="utf-8", newline="\n") as output_file:
            output_file.write(serialized + "\n")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
