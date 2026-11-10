"""Behavior tests for the retrieval benchmark command interface."""
from __future__ import annotations

import hashlib
import json
from types import SimpleNamespace

import pytest
from tokenizers import Tokenizer
from tokenizers.models import WordLevel
from tokenizers.pre_tokenizers import Whitespace


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
        (index, "index-v1"),
        (groove_index, "groove-index-v1"),
    ):
        path.write_text(value, encoding="utf-8")
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
    )

    original = retrieval_benchmark_cli_mod._backend_settings_payload(args)
    target = executable if backend == "grooveseek" else index
    target.write_text("replacement-v2", encoding="utf-8")
    changed = retrieval_benchmark_cli_mod._backend_settings_payload(args)

    assert all(
        value.startswith("sha256:")
        for value in original["artifact_hashes"].values()
        if value is not None
    )
    assert retrieval_benchmark_mod.backend_settings_lock(
        original
    ) != retrieval_benchmark_mod.backend_settings_lock(changed)


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
    payload["benchmark_version"] = retrieval_benchmark_mod.benchmark_version(
        privacy, records
    )
    payload["manifest"] = _manifest(
        records,
        retrieval_benchmark_mod,
        split_membership,
        corpus_root,
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


def _private_args(workbook_path, output_path, corpus_root):
    return [
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
        "--benchmark-corpus-root",
        str(corpus_root),
        *MEASUREMENT_ARGS,
    ]


def _write_corpus(tmp_path, *, private=False):
    corpus_root = tmp_path / "corpus"
    document = corpus_root / "wiki" / "answer.md" if private else corpus_root / "answer.md"
    document.parent.mkdir(parents=True)
    document.write_text("Exact answer passage. Exact answer.\n", encoding="utf-8")
    return corpus_root


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
        process_runner=run_process,
        token_counter=lambda _text: 4,
    )

    output = capsys.readouterr().out
    payload = json.loads(output)
    assert exit_code == 0
    assert payload["schema_version"] == 1
    assert payload["backend"] == "grooveseek"
    assert payload["summary"]["group_recall_at_5"] == 1.0
    assert payload["measurements"]["full_build_time_ms"] == 200
    assert payload["measurements"]["derived_index_size_bytes"] == 4096
    assert payload["measurements"]["offline_verified"] is True
    assert "PRIVATE QUERY TEXT" not in output
    assert "answer.md" not in output


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
        process_runner=run_process,
        token_counter=lambda _text: 0,
    )

    assert executed_queries == [
        record["query"] for record in sorted(queries, key=lambda item: item["id"])
    ]


def test_private_cli_filters_split_and_writes_report_without_stdout(
    tmp_path, capsys, retrieval_benchmark_cli_mod, retrieval_benchmark_mod
):
    workbook_path = tmp_path / "authoring-workbook.json"
    output_path = tmp_path / "private-report.json"
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
            "--benchmark-corpus-root",
            str(corpus_root),
            *MEASUREMENT_ARGS,
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
    expected_lock = retrieval_benchmark_mod.backend_settings_lock({
        "backend": "grooveseek",
        "limit": 10,
        "path_prefix": "wiki",
        "tokenizer": None,
        "executable": "groove",
        "knowledge_base": "corpus",
        "artifact_hashes": {
            "tokenizer": None,
            "executable": None,
            "index": None,
        },
    })
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
    workbook_path = tmp_path / "workbook.json"
    output_path = tmp_path / "report.json"
    workbook_path.write_text(json.dumps(payload), encoding="utf-8")
    args = _private_args(workbook_path, output_path, corpus_root)
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
    settings_lock = retrieval_benchmark_mod.backend_settings_lock({
        "backend": "grooveseek",
        "limit": 10,
        "path_prefix": "wiki",
        "tokenizer": None,
        "executable": "groove",
        "knowledge_base": "corpus",
        "artifact_hashes": {
            "tokenizer": None,
            "executable": None,
            "index": None,
        },
    })
    payload["manifest"]["locked_backend_settings"] = {
        "grooveseek": settings_lock
    }
    workbook_path = tmp_path / "workbook.json"
    output_path = tmp_path / "report.json"
    workbook_path.write_text(json.dumps(payload), encoding="utf-8")
    args = _private_args(workbook_path, output_path, corpus_root)
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


def test_public_cli_runs_qmd_adapter(
    tmp_path, capsys, retrieval_benchmark_cli_mod, retrieval_benchmark_mod
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
            str(corpus_root),
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
    tmp_path, capsys, retrieval_benchmark_cli_mod, retrieval_benchmark_mod
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
                "--node-executable", "node",
                "--qmd-script", "qmd",
                "--index", "glassgraph-test",
                "--collection", "glassgraph-test",
                "--corpus-root", str(corpus_root),
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
                    "explain": {"blendedScore": 1.0},
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
    workbook_path = tmp_path / "unadjudicated.json"
    output_path = tmp_path / "report.json"
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
    workbook_path = tmp_path / f"{invalid_case}.json"
    output_path = tmp_path / "report.json"
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
    workbook_path = tmp_path / "workbook.json"
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
    workbook_path = tmp_path / "workbook.json"
    output_path = tmp_path / "report.json"
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
        "private", records
    )
    payload["manifest"] = _manifest(
        records,
        retrieval_benchmark_mod,
        payload["manifest"]["split_membership"],
        corpus_root,
    )
    workbook_path = tmp_path / "private-workbook.json"
    output_path = tmp_path / "private-report.json"
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
    workbook_path = tmp_path / "secret-private-workbook.json"
    output_path = tmp_path / "report.json"

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
    workbook_path = tmp_path / "authoring-workbook.json"
    output_path = tmp_path / "secret-missing-parent" / "private-report.json"
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
    workbook_path = tmp_path / "extra.json"
    output_path = tmp_path / "report.json"
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
