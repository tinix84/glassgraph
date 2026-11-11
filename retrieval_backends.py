"""Adapters for local retrieval backends."""
from __future__ import annotations

import json
import math
import os
import re
import tempfile
import time
from pathlib import Path

import psutil


def _finite_number(value: object) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _valid_match_span(value: object) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("start"), int)
        and not isinstance(value["start"], bool)
        and isinstance(value.get("end"), int)
        and not isinstance(value["end"], bool)
        and 0 <= value["start"] <= value["end"]
    )


def _with_prefix(path: str, prefix: str | None) -> str:
    normalized = path.replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:/", normalized):
        raise RuntimeError("Backend returned an unsafe result path")
    parts = [part for part in normalized.split("/") if part not in {"", "."}]
    if not parts or ".." in parts:
        raise RuntimeError("Backend returned an unsafe result path")
    relative = "/".join(parts)
    if re.match(r"^[A-Za-z]:", relative):
        raise RuntimeError("Backend returned an unsafe result path")
    if prefix is None:
        return relative
    safe_prefix = _with_prefix(prefix, None)
    return f"{safe_prefix}/{relative}"


def run_process(args: list[str], environment: dict[str, str | None]) -> dict:
    """Run one backend command and measure its process-tree working set."""
    process_environment = os.environ.copy()
    for name, value in environment.items():
        if value is None:
            process_environment.pop(name, None)
        else:
            process_environment[name] = value
    started = time.perf_counter()
    with tempfile.TemporaryFile() as stdout_file, tempfile.TemporaryFile() as stderr_file:
        process = psutil.Popen(
            args,
            stdout=stdout_file,
            stderr=stderr_file,
            env=process_environment,
        )
        try:
            peak_working_set = process.memory_info().rss
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            peak_working_set = 0
        while process.poll() is None:
            try:
                working_set = process.memory_info().rss
                for child in process.children(recursive=True):
                    try:
                        working_set += child.memory_info().rss
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        pass
                peak_working_set = max(peak_working_set, working_set)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass
            time.sleep(0.01)
        process.wait()
        stdout_file.seek(0)
        stderr_file.seek(0)
        stdout = stdout_file.read().decode("utf-8", errors="replace")
        stderr = stderr_file.read().decode("utf-8", errors="replace")
    if process.returncode:
        raise RuntimeError(f"backend command failed with exit code {process.returncode}")
    return {
        "stdout": stdout,
        "stderr": stderr,
        "elapsed_ms": (time.perf_counter() - started) * 1000,
        "peak_working_set_bytes": peak_working_set,
    }


class GrooveSeekAdapter:
    """Normalize GrooveSeek query output for the benchmark metric seam."""

    def __init__(
        self,
        *,
        executable: str,
        knowledge_base: str,
        process_runner,
        token_counter,
        path_prefix: str | None = None,
        config: str | Path | None = None,
        model: str | None = None,
        model_cache: str | Path | None = None,
        low_confidence_policy: str = "abstain",
    ) -> None:
        if low_confidence_policy not in {"abstain", "preserve"}:
            raise ValueError("Unknown GrooveSeek low-confidence policy")
        self.executable = executable
        self.knowledge_base = knowledge_base
        self.process_runner = process_runner
        self.token_counter = token_counter
        self.path_prefix = path_prefix
        self.config = str(config) if config is not None else None
        self.model = model
        self.low_confidence_policy = low_confidence_policy
        self.model_cache = (
            str(Path(model_cache).resolve()) if model_cache is not None else None
        )

    def query(self, text: str, *, limit: int) -> dict:
        command = [
            self.executable,
            "search",
            text,
        ]
        if self.config is not None:
            command.extend(["--config", self.config])
        if self.model is not None:
            command.extend(["--model", self.model])
        command.extend([
            "--kb-path", self.knowledge_base,
            "--limit",
            str(limit),
            "--format",
            "json",
            "--include-low-quality",
        ])
        environment = (
            {"FASTEMBED_CACHE_DIR": self.model_cache}
            if self.model_cache is not None
            else {}
        )
        measured = self.process_runner(command, environment)
        payload = json.loads(measured["stdout"])
        if (
            not isinstance(payload, dict)
            or not isinstance(payload.get("results"), list)
            or not isinstance(payload.get("low_confidence"), bool)
            or any(
                not isinstance(hit, dict)
                or not isinstance(hit.get("path"), str)
                or not hit["path"]
                or not isinstance(hit.get("content"), str)
                or not _finite_number(hit.get("score"))
                or not isinstance(hit.get("match_spans", []), list)
                or any(
                    not _valid_match_span(span)
                    for span in hit.get("match_spans", [])
                )
                for hit in payload["results"]
            )
        ):
            raise RuntimeError("GrooveSeek returned an invalid response")
        raw_hits = []
        for hit in payload.get("results", []):
            content = hit["content"]
            raw_hits.append(
                {
                    "path": _with_prefix(str(hit.get("path") or ""), self.path_prefix),
                    "text": content,
                    "backend_score": {
                        "adapter": "grooveseek",
                        "kind": "rrf",
                        "raw": hit.get("score"),
                    },
                    "context_tokens": self.token_counter(content),
                    "explanation": {
                        "kind": "match_spans",
                        "value": hit.get("match_spans", []),
                    },
                    "backend_locator": {
                        "kind": "utf8_match_spans",
                        "value": hit.get("match_spans", []),
                    },
                    **(
                        {"heading": hit["heading"]}
                        if isinstance(hit.get("heading"), str)
                        else {}
                    ),
                }
            )

        low_confidence = payload.get("low_confidence") is True
        abstained = low_confidence and self.low_confidence_policy == "abstain"
        return {
            "hits": [] if abstained else raw_hits,
            "raw_hits": raw_hits,
            "abstained": abstained,
            "low_confidence": low_confidence,
            "latency_ms": measured["elapsed_ms"],
            "peak_working_set_bytes": measured["peak_working_set_bytes"],
        }


class QmdAdapter:
    """Normalize QMD hybrid query output for the benchmark metric seam."""

    def __init__(
        self,
        *,
        node_executable: str,
        qmd_script: str,
        index: str,
        collection: str,
        corpus_root: str | Path,
        process_runner,
        token_counter,
        path_prefix: str | None = None,
        index_db: str | Path | None = None,
        config_dir: str | Path | None = None,
        embed_model: str | Path | None = None,
    ) -> None:
        self.node_executable = node_executable
        self.qmd_script = qmd_script
        self.index = index
        self.collection = collection
        self.corpus_root = Path(corpus_root).resolve()
        self.process_runner = process_runner
        self.token_counter = token_counter
        self.path_prefix = path_prefix
        self.index_db = (
            str(Path(index_db).resolve()) if index_db is not None else None
        )
        self.config_dir = (
            str(Path(config_dir).resolve()) if config_dir is not None else None
        )
        self.embed_model = (
            str(embed_model) if embed_model is not None else None
        )

    def query(self, text: str, *, limit: int) -> dict:
        structured_query = f"lex: {text}\nvec: {text}"
        command = [
            self.node_executable,
            self.qmd_script,
            "--index",
            self.index,
            "query",
            structured_query,
            "--no-rerank",
            "-c",
            self.collection,
            "-n",
            str(limit),
            "--format",
            "json",
            "--full-path",
            "--explain",
        ]
        environment = {
            "QMD_FORCE_CPU": "1",
            "QMD_EMBED_CONTEXT_SIZE": None,
            "QMD_EMBED_PARALLELISM": None,
            "QMD_EXPAND_CONTEXT_SIZE": None,
            "QMD_LLAMA_GPU": None,
            "QMD_RERANK_CONTEXT_SIZE": None,
        }
        if self.index_db is not None:
            environment.update(
                {
                    "INDEX_PATH": self.index_db,
                    "QMD_CONFIG_DIR": self.config_dir,
                    "QMD_EMBED_MODEL": self.embed_model,
                    "XDG_CACHE_HOME": None,
                    "XDG_CONFIG_HOME": None,
                }
            )
        measured = self.process_runner(command, environment)
        payload = json.loads(measured["stdout"])
        if not isinstance(payload, list) or any(
            not isinstance(hit, dict)
            or not isinstance(hit.get("file"), str)
            or not hit["file"]
            for hit in payload
        ):
            raise RuntimeError("QMD returned an invalid response")
        relative_paths = []
        for hit in payload:
            try:
                relative_paths.append(
                    Path(hit["file"])
                    .resolve()
                    .relative_to(self.corpus_root)
                    .as_posix()
                )
            except ValueError:
                raise RuntimeError(
                    "QMD returned a result outside the benchmark corpus"
                ) from None
        if any(
            not isinstance(hit.get("snippet"), str)
            or not _finite_number(hit.get("score"))
            or not isinstance(hit.get("line"), int)
            or isinstance(hit["line"], bool)
            or hit["line"] <= 0
            or not isinstance(hit.get("explain"), dict)
            or (
                "vectorScores" in hit["explain"]
                and (
                    not isinstance(hit["explain"]["vectorScores"], list)
                    or any(
                        not _finite_number(score)
                        for score in hit["explain"]["vectorScores"]
                    )
                )
            )
            for hit in payload
        ):
            raise RuntimeError("QMD returned an invalid response")
        if not any(hit["explain"].get("vectorScores") for hit in payload):
            raise RuntimeError("QMD did not prove vector retrieval")
        raw_hits = []
        for hit, relative_path in zip(payload, relative_paths, strict=True):
            content = hit["snippet"]
            path = _with_prefix(relative_path, self.path_prefix)
            raw_hits.append(
                {
                    "path": path,
                    "text": content,
                    "backend_score": {
                        "adapter": "qmd",
                        "kind": "hybrid",
                        "raw": hit.get("score"),
                    },
                    "context_tokens": self.token_counter(content),
                    "explanation": {
                        "kind": "qmd_explain",
                        "value": hit.get("explain"),
                    },
                    "backend_locator": {
                        "kind": "heuristic_line",
                        "line": hit.get("line"),
                    },
                }
            )

        return {
            "hits": raw_hits,
            "raw_hits": raw_hits,
            "abstained": False,
            "latency_ms": measured["elapsed_ms"],
            "peak_working_set_bytes": measured["peak_working_set_bytes"],
        }
