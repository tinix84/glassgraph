"""Local command interface for evidence-level retrieval benchmarks."""
from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from tokenizers import Tokenizer

import retrieval_backends
import retrieval_benchmark


def load_token_counter(path: Path):
    """Load one pinned tokenizer and return a text-to-token-count function."""
    tokenizer = Tokenizer.from_file(str(path))

    def count_tokens(text: str) -> int:
        return len(tokenizer.encode(text).ids)

    return count_tokens


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
    missing = [
        f"{split} {kind} {counts[(split, kind)]}/{count}"
        for (split, kind), count in expected.items()
        if counts[(split, kind)] != count
    ]
    if missing:
        raise ValueError("Private benchmark distribution is incomplete: " + ", ".join(missing))
    unapproved = [
        record.get("id", "<missing-id>")
        for record in payload.get("records", [])
        if record.get("owner_authored") is not True
        or record.get("owner_adjudicated") is not True
    ]
    if unapproved:
        raise ValueError(
            "Private benchmark records need owner authorship and adjudication: "
            + ", ".join(unapproved)
        )


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
    parser.add_argument("--tokenizer", type=Path)
    parser.add_argument("--path-prefix")
    return parser


def main(argv=None, *, process_runner=None, token_counter=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if process_runner is None:
        process_runner = retrieval_backends.run_process
    if token_counter is None:
        token_counter = load_token_counter(args.tokenizer)
    payload = json.loads(args.queries.read_text(encoding="utf-8"))
    if args.privacy == "private":
        try:
            validate_private_workbook(payload)
        except ValueError as error:
            parser.error(str(error))
        queries = [
            record for record in payload["records"] if record.get("split") == args.split
        ]
    else:
        queries = payload["queries"]

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

    runs = {
        query["id"]: adapter.query(query["query"], limit=args.limit)
        for query in queries
    }
    summary = retrieval_benchmark.evaluate(queries, runs)
    report = {
        "schema_version": 1,
        "backend": args.backend,
        "privacy": args.privacy,
        "split": args.split,
        "query_count": len(queries),
        "summary": summary,
    }
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    if args.privacy == "private":
        args.output.write_text(serialized + "\n", encoding="utf-8")
    else:
        print(serialized)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
