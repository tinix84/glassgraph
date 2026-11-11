"""Private command interface for topic-driven search comparisons."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import retrieval_benchmark_cli
import retrieval_benchmark
import query_contract
import search_lab


def _load_object(path: Path, name: str) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ValueError(f"The {name} file is invalid") from error
    if not isinstance(payload, dict):
        raise ValueError(f"The {name} file must contain an object")
    return payload


def _paths_are_private(args) -> bool:
    try:
        workspace = args.brief.resolve().parent
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
        paths = [
            args.brief.resolve(),
            args.holdout_brief.resolve(),
            args.runs.resolve(),
            args.tuning.resolve(),
            args.settings_lock.resolve(),
            args.output.resolve(),
        ]
        for path in paths:
            path.relative_to(workspace)
        args.corpus_root.resolve().relative_to(vault_root)
        if any(
            retrieval_benchmark_cli._path_chain_has_nested_git(path, vault_root)
            for path in (
                workspace,
                args.output.resolve().parent,
                args.corpus_root.resolve(),
                *paths,
            )
        ):
            return False
        return retrieval_benchmark_cli._private_git_paths_are_unpublished(
            vault_root,
            workspace,
            paths,
        )
    except (AttributeError, IndexError, OSError, TypeError, ValueError):
        return False


def _trial_run(backend_payload: dict, trial: dict) -> dict:
    entry = backend_payload["trials"].get(trial["id"])
    if (
        not isinstance(entry, dict)
        or entry.get("role") != trial.get("role")
    ):
        raise ValueError(f"A matching backend run is missing for {trial['id']}")
    if isinstance(entry.get("request"), dict) and isinstance(
        entry.get("response"), dict
    ):
        if entry["request"].get("input", {}).get("text") != trial.get("query"):
            raise ValueError(f"A matching backend run is missing for {trial['id']}")
        return query_contract.backend_run(entry["request"], entry["response"])
    if entry.get("query") == trial.get("query") and isinstance(entry.get("run"), dict):
        return entry["run"]
    raise ValueError(f"A matching backend run is missing for {trial['id']}")


def main(argv=None) -> int:
    """Write one private Sol-versus-Glassgraph comparison report."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--brief", type=Path, required=True)
    parser.add_argument("--holdout-brief", type=Path, required=True)
    parser.add_argument("--runs", type=Path, required=True)
    parser.add_argument("--tuning", type=Path, required=True)
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--settings-lock", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--offline-verified", action="store_true", required=True)
    args = parser.parse_args(argv)

    if not _paths_are_private(args):
        parser.error("Search-lab files must stay in the vault-side private workspace")
    if args.output.exists():
        parser.error("The private report path already exists")

    try:
        brief = _load_object(args.brief, "research brief")
        runs = _load_object(args.runs, "backend runs")
        tuning = _load_object(args.tuning, "tuning history")
        settings_lock = _load_object(args.settings_lock, "settings lock")
        if settings_lock.get("corpus_snapshot_hash") != (
            retrieval_benchmark.corpus_snapshot_hash(args.corpus_root)
        ):
            raise ValueError("The corpus does not match the settings lock")
        session = search_lab.new_session(brief)
        comparisons = []

        for iteration in tuning.get("iterations", []):
            search_lab.record_iteration(session, iteration)

        locked_backends = settings_lock.get("backends")
        if not isinstance(locked_backends, dict) or set(runs) != set(locked_backends):
            raise ValueError("Backend runs do not match the settings lock")
        for backend, backend_payload in runs.items():
            locked_settings = locked_backends[backend]
            if (
                not isinstance(backend_payload, dict)
                or locked_settings.get("corpus_snapshot_hash")
                != settings_lock["corpus_snapshot_hash"]
                or backend_payload.get("settings") != locked_settings
                or not isinstance(backend_payload.get("trials"), dict)
            ):
                raise ValueError(f"Backend runs do not match the lock for {backend}")
            for trial in brief["questions"]:
                run = _trial_run(backend_payload, trial)
                comparison = search_lab.compare_trial(trial, run, args.corpus_root)
                comparison["backend"] = backend
                comparisons.append(comparison)

        search_lab.lock_settings(session, settings_lock)

        holdout_brief = _load_object(args.holdout_brief, "holdout brief")
        holdout_comparisons = []
        for trial in holdout_brief["questions"]:
            if trial.get("role") != "holdout":
                raise ValueError("The holdout brief can contain only holdout questions")
        for backend, backend_payload in runs.items():
            for trial in holdout_brief["questions"]:
                run = _trial_run(backend_payload, trial)
                comparison = search_lab.compare_trial(trial, run, args.corpus_root)
                comparison["backend"] = backend
                comparisons.append(comparison)
                holdout_comparisons.append(comparison)
        search_lab.record_holdout(
            session,
            {"brief": holdout_brief, "runs": holdout_comparisons},
        )
    except (KeyError, search_lab.SearchLabError, ValueError) as error:
        parser.error(str(error))

    report = {
        "privacy": "private",
        "offline_verified": True,
        "session": session,
        "comparisons": comparisons,
    }
    serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    try:
        with args.output.open("x", encoding="utf-8", newline="\n") as output_file:
            output_file.write(serialized + "\n")
    except OSError as error:
        parser.error(f"The private report cannot be written: {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
