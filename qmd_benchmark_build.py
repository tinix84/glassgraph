"""Build one frozen QMD benchmark index and attest the completed build."""
from __future__ import annotations

import argparse
from pathlib import Path

import retrieval_backends
import retrieval_benchmark_cli


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--node-executable", required=True)
    parser.add_argument("--qmd-script", required=True)
    parser.add_argument("--qmd-config", type=Path, required=True)
    parser.add_argument("--qmd-index-db", type=Path, required=True)
    parser.add_argument("--index", required=True)
    parser.add_argument("--collection", required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--benchmark-corpus-root", type=Path, required=True)
    parser.add_argument("--retrieval-model-id", required=True)
    parser.add_argument("--retrieval-model-artifact", type=Path, required=True)
    parser.add_argument("--path-prefix")
    parser.add_argument("--output", type=Path, required=True)
    return parser


def _environment(args) -> dict[str, str | None]:
    return {
        "INDEX_PATH": str(args.qmd_index_db.resolve()),
        "QMD_CONFIG_DIR": str(args.qmd_config.parent.resolve()),
        "QMD_EMBED_MODEL": args.retrieval_model_id,
        "QMD_FORCE_CPU": "1",
        "QMD_EMBED_CONTEXT_SIZE": None,
        "QMD_EMBED_PARALLELISM": None,
        "QMD_EXPAND_CONTEXT_SIZE": None,
        "QMD_LLAMA_GPU": None,
        "QMD_RERANK_CONTEXT_SIZE": None,
        "XDG_CACHE_HOME": None,
        "XDG_CONFIG_HOME": None,
    }


def main(argv=None, *, process_runner=None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("The QMD build receipt already exists")
    if not args.retrieval_model_artifact.is_file():
        parser.error("The pinned QMD embedding model is unavailable")
    try:
        config_payload = retrieval_benchmark_cli._read_qmd_config(args)
        model_is_pinned = retrieval_benchmark_cli._qmd_config_uses_model_artifact(
            args,
            config_payload,
        )
    except (OSError, TypeError, ValueError):
        parser.error("The QMD build configuration is invalid")
    if not model_is_pinned:
        parser.error("The QMD build configuration does not use the pinned model")

    runner = process_runner or retrieval_backends.run_process
    common = [
        args.node_executable,
        args.qmd_script,
        "--index",
        args.index,
    ]
    environment = _environment(args)
    try:
        runner([*common, "update"], environment)
        runner(
            [*common, "embed", "-f", "-c", args.collection],
            environment,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        parser.error("The controlled QMD build failed")

    if not retrieval_benchmark_cli._qmd_index_is_ready(args, config_payload):
        parser.error("The controlled QMD build did not produce a ready index")
    try:
        retrieval_benchmark_cli._write_qmd_build_receipt(args.output, args)
    except (OSError, TypeError, ValueError):
        parser.error("The QMD build receipt could not be written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
