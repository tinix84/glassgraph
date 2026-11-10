"""Behavior tests for the retrieval benchmark command interface."""
from __future__ import annotations

import json

import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace


def test_public_cli_prints_aggregate_only(
    tmp_path, capsys, retrieval_benchmark_cli_mod
):
    queries_path = tmp_path / "queries.json"
    queries_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "queries": [
                    {
                        "id": "q1",
                        "query": "PRIVATE QUERY TEXT",
                        "required_groups": [
                            [
                                {
                                    "path": "answer.md",
                                    "text": "Exact answer passage.",
                                    "grade": "direct",
                                }
                            ]
                        ],
                    }
                ],
            }
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
            "--groove-executable",
            "groove",
            "--knowledge-base",
            "corpus",
            "--privacy",
            "public",
        ],
        process_runner=run_process,
        token_counter=lambda _text: 4,
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["schema_version"] == 1
    assert payload["backend"] == "grooveseek"
    assert payload["summary"]["group_recall_at_5"] == 1.0
    assert "PRIVATE QUERY TEXT" not in output
    assert "answer.md" not in output


def test_private_cli_filters_split_and_writes_report_without_stdout(
    tmp_path, capsys, retrieval_benchmark_cli_mod
):
    workbook_path = tmp_path / "authoring-workbook.json"
    output_path = tmp_path / "private-report.json"
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
                    "required_groups": [
                        [
                            {
                                "path": "wiki/answer.md",
                                "text": "Exact answer.",
                                "grade": "direct",
                            }
                        ]
                    ],
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
    workbook_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "benchmark_version": "private-v1",
                "records": records,
            }
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
        [
            "--queries",
            str(workbook_path),
            "--backend",
            "grooveseek",
            "--groove-executable",
            "groove",
            "--knowledge-base",
            "corpus",
            "--path-prefix",
            "wiki",
            "--privacy",
            "private",
            "--split",
            "development",
            "--output",
            str(output_path),
        ],
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


def test_public_cli_runs_qmd_adapter(tmp_path, capsys, retrieval_benchmark_cli_mod):
    queries_path = tmp_path / "queries.json"
    document = tmp_path / "answer.md"
    queries_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "queries": [
                    {
                        "id": "q1",
                        "query": "What is the answer?",
                        "required_groups": [
                            [{"path": "answer.md", "text": "Exact answer.", "grade": "direct"}]
                        ],
                    }
                ],
            }
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
                        "snippet": "@@ -1,1 @@\nExact answer.",
                        "explain": {"blendedScore": 1.0},
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
            "--node-executable",
            "node",
            "--qmd-script",
            "qmd",
            "--index",
            "glassgraph-m1-public",
            "--collection",
            "glassgraph-m1-public",
            "--corpus-root",
            str(tmp_path),
            "--privacy",
            "public",
        ],
        process_runner=run_process,
        token_counter=lambda _text: 5,
    )

    payload = json.loads(capsys.readouterr().out)
    assert exit_code == 0
    assert payload["backend"] == "qmd"
    assert payload["summary"]["group_recall_at_5"] == 1.0


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
    workbook_path = tmp_path / "incomplete.json"
    output_path = tmp_path / "report.json"
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
            ],
            process_runner=must_not_run,
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert not output_path.exists()


def test_private_cli_rejects_unadjudicated_record(
    tmp_path, retrieval_benchmark_cli_mod
):
    records = []
    for split, short, positive_count, negative_count in (
        ("development", "dev", 30, 10),
        ("evaluation", "eval", 15, 5),
    ):
        for kind, short_kind, count in (
            ("positive", "p", positive_count),
            ("negative", "n", negative_count),
        ):
            for index in range(1, count + 1):
                records.append(
                    {
                        "id": f"private-v1-{short}-{short_kind}{index:02d}",
                        "split": split,
                        "kind": kind,
                        "query": f"{split} {kind} {index}",
                        "required_groups": (
                            [[{"path": "wiki/a.md", "text": "A", "grade": "direct"}]]
                            if kind == "positive"
                            else []
                        ),
                        "adjudication_note": "Checked" if kind == "negative" else "",
                        "owner_authored": True,
                        "owner_adjudicated": True,
                    }
                )
    records[0]["owner_adjudicated"] = False
    workbook_path = tmp_path / "unadjudicated.json"
    output_path = tmp_path / "report.json"
    workbook_path.write_text(
        json.dumps({"schema_version": 1, "benchmark_version": "private-v1", "records": records}),
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
            ],
            process_runner=must_not_run,
            token_counter=lambda _text: 1,
        )

    assert error.value.code == 2
    assert not output_path.exists()
