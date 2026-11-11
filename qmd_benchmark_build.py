"""Build one frozen QMD benchmark index and attest the completed build."""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import retrieval_backends
import retrieval_benchmark_cli


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--privacy", choices=["public", "private"], required=True)
    parser.add_argument("--queries", type=Path)
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
    args.backend = "qmd"
    args.qmd_build_receipt = args.output
    args.backend_config_artifact = []
    if args.privacy == "private":
        if args.queries is None:
            parser.error("Private QMD builds require --queries")
        if not retrieval_benchmark_cli._private_paths_are_vault_local(args):
            parser.error(
                "Private QMD build artifacts must stay in the unpublished "
                "vault workspace"
            )
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
    if retrieval_benchmark_cli._qmd_config_has_update_hooks(config_payload):
        parser.error("QMD benchmark builds do not allow collection update hooks")
    if not retrieval_benchmark_cli._qmd_config_uses_local_models(config_payload):
        parser.error("QMD benchmark builds require local model files")

    try:
        before = retrieval_benchmark_cli._qmd_build_receipt_payload(args)
    except (OSError, TypeError, ValueError):
        parser.error("QMD build inputs could not be fingerprinted")

    runner = process_runner or retrieval_backends.run_process
    common = [
        args.node_executable,
        args.qmd_script,
        "--index",
        args.index,
    ]
    environment = _environment(args)
    started = datetime.now(timezone.utc)
    started = started.replace(microsecond=(started.microsecond // 1000) * 1000)
    try:
        runner([*common, "update"], environment)
        runner(
            [*common, "embed", "-f", "-c", args.collection],
            environment,
        )
    except (OSError, RuntimeError, TypeError, ValueError):
        parser.error("The controlled QMD build failed")
    completed = datetime.now(timezone.utc)

    if not retrieval_benchmark_cli._qmd_index_is_ready(args, config_payload):
        parser.error("The controlled QMD build did not produce a ready index")
    try:
        after = retrieval_benchmark_cli._qmd_build_receipt_payload(args)
        stable_keys = set(after) - {"qmd_index_sha256"}
        if any(before.get(key) != after.get(key) for key in stable_keys):
            parser.error("QMD build inputs changed during forced embedding")
        embedding_times = retrieval_benchmark_cli._qmd_active_embedding_times(args)
        if (
            before.get("qmd_index_sha256") == after.get("qmd_index_sha256")
            or not embedding_times
            or any(
                embedded_at < started - timedelta(milliseconds=10)
                or embedded_at > completed + timedelta(milliseconds=10)
                for embedded_at in embedding_times
            )
        ):
            parser.error("QMD forced embedding did not refresh every active chunk")
        build_proof = {
            "schema_version": "glassgraph.qmd-build-proof.v1",
            "forced_embed_started_at": started.isoformat().replace("+00:00", "Z"),
            "forced_embed_completed_at": completed.isoformat().replace(
                "+00:00", "Z"
            ),
            "active_chunk_count": len(embedding_times),
            "pre_index_sha256": before.get("qmd_index_sha256"),
            "post_index_sha256": after.get("qmd_index_sha256"),
        }
        retrieval_benchmark_cli._write_qmd_build_receipt(
            args.output,
            args,
            build_proof,
            payload=after,
        )
    except (OSError, TypeError, ValueError):
        parser.error("The QMD build receipt could not be written")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
