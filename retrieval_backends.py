"""Adapters for local retrieval backends."""
from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

import psutil


def _with_prefix(path: str, prefix: str | None) -> str:
    normalized = path.replace("\\", "/").lstrip("./")
    return f"{prefix.strip('/')}/{normalized}" if prefix else normalized


def run_process(args: list[str], environment: dict[str, str]) -> dict:
    """Run one backend command and measure its process-tree working set."""
    process_environment = os.environ.copy()
    process_environment.update(environment)
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
    ) -> None:
        self.executable = executable
        self.knowledge_base = knowledge_base
        self.process_runner = process_runner
        self.token_counter = token_counter
        self.path_prefix = path_prefix

    def query(self, text: str, *, limit: int) -> dict:
        command = [
            self.executable,
            "search",
            text,
            "--kb-path",
            self.knowledge_base,
            "--limit",
            str(limit),
            "--format",
            "json",
            "--include-low-quality",
        ]
        measured = self.process_runner(command, {})
        payload = json.loads(measured["stdout"])
        raw_hits = []
        for hit in payload.get("results", []):
            content = str(hit.get("content") or "")
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
                }
            )

        abstained = payload.get("low_confidence") is True
        return {
            "hits": [] if abstained else raw_hits,
            "raw_hits": raw_hits,
            "abstained": abstained,
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
    ) -> None:
        self.node_executable = node_executable
        self.qmd_script = qmd_script
        self.index = index
        self.collection = collection
        self.corpus_root = Path(corpus_root).resolve()
        self.process_runner = process_runner
        self.token_counter = token_counter
        self.path_prefix = path_prefix

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
        measured = self.process_runner(command, {"QMD_FORCE_CPU": "1"})
        payload = json.loads(measured["stdout"])
        raw_hits = []
        for hit in payload:
            content = str(hit.get("snippet") or "")
            relative_path = Path(hit["file"]).resolve().relative_to(self.corpus_root).as_posix()
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
