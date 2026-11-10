"""Contract tests for the public benchmark fixture and golden identifiers."""
from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from decimal import Decimal
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "benchmark" / "v1"
SHA256_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def _nfc(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, list):
        return [_nfc(item) for item in value]
    if isinstance(value, dict):
        return {key: _nfc(item) for key, item in value.items()}
    return value


def _identifier(domain, payload):
    canonical = json.dumps(
        _nfc(payload),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(f"{domain}\0{canonical}".encode()).hexdigest()
    return f"sha256:{digest}"


def _passage_hash(text):
    normalized = unicodedata.normalize("NFC", text).replace("\r\n", "\n")
    return "sha256:" + hashlib.sha256(normalized.encode()).hexdigest()


def _document_id(path):
    return _identifier("glassgraph:document:v1", {"path": path})


def _heading_id(document_id, level, parent_id, ordinal, title):
    return _identifier(
        "glassgraph:heading:v1",
        {
            "document_id": document_id,
            "level": level,
            "parent_id": parent_id,
            "same_name_ordinal": ordinal,
            "title": title,
        },
    )


def _evidence_id(document_id, heading_id, passage_hash, ordinal=0):
    return _identifier(
        "glassgraph:evidence:v1",
        {
            "document_id": document_id,
            "heading_id": heading_id,
            "passage_hash": passage_hash,
            "passage_ordinal": ordinal,
        },
    )


def _normalize_decimal(value):
    normalized = format(Decimal(value), "f")
    if "." in normalized:
        normalized = normalized.rstrip("0").rstrip(".")
    if normalized in {"-0", ""}:
        return "0"
    if normalized.startswith("."):
        return "0" + normalized
    if normalized.startswith("-."):
        return "-0" + normalized[1:]
    return normalized


def _normalize_integer(value):
    normalized = str(int(value, 10))
    return "0" if normalized == "-0" else normalized


def _heading_instances(path, document_id):
    headings = []
    stack = []
    counts = {}
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if not match:
            continue
        level = len(match.group(1))
        title = unicodedata.normalize("NFC", match.group(2))
        while stack and stack[-1]["level"] >= level:
            stack.pop()
        parent_id = stack[-1]["id"] if stack else None
        key = (parent_id, level, title)
        ordinal = counts.get(key, 0)
        counts[key] = ordinal + 1
        heading = {
            "id": _heading_id(document_id, level, parent_id, ordinal, title),
            "level": level,
            "line": line_number,
            "title": title,
        }
        headings.append(heading)
        stack.append(heading)
    return headings


def _judgment_evidence_id(corpus_root, judgment):
    document_id = _document_id(judgment["path"])
    path = corpus_root / judgment["path"]
    headings = _heading_instances(path, document_id)
    matching_headings = [
        heading for heading in headings if heading["title"] == judgment["heading"]
    ]
    assert len(matching_headings) == 1
    heading = matching_headings[0]
    passage = judgment["text"] + "\n"
    assert path.read_text(encoding="utf-8").count(passage) == 1
    return _evidence_id(document_id, heading["id"], _passage_hash(passage))


def test_identity_fixture_matches_all_adr_0013_golden_vectors():
    golden = json.loads((FIXTURE / "golden-identifiers.json").read_text(encoding="utf-8"))
    example = FIXTURE / "identity-cases" / "wiki" / "example.md"
    document_id = _document_id("wiki/example.md")
    root_heading_id = _heading_id(document_id, 0, None, 0, "")
    first_results = _heading_id(document_id, 2, None, 0, "Results")
    second_results = _heading_id(document_id, 2, None, 1, "Results")
    unicode_heading = _heading_id(document_id, 2, None, 0, "Résultats")
    passage_hash = _passage_hash("Efficiency is 98%.\n")
    vendor_hash = _passage_hash('vendor: "[[Tesla]]"\n')

    assert "# Example\n" not in example.read_text(encoding="utf-8")
    assert golden["document_id"] == document_id
    assert golden["root_heading_id"] == root_heading_id
    assert golden["first_results_heading_id"] == first_results
    assert golden["second_results_heading_id"] == second_results
    assert golden["unicode_heading_id"] == unicode_heading
    assert golden["passage_hash"] == passage_hash
    assert golden["first_evidence_id"] == _evidence_id(
        document_id, first_results, passage_hash
    )
    assert golden["second_evidence_id"] == _evidence_id(
        document_id, second_results, passage_hash
    )
    assert golden["first_evidence_id"] != golden["second_evidence_id"]
    assert golden["vendor_passage_hash"] == vendor_hash
    assert golden["vendor_evidence_id"] == _evidence_id(
        document_id, root_heading_id, vendor_hash
    )

    entity_id = _identifier(
        "glassgraph:entity:v1",
        {
            "canonical_name": "Example",
            "document_id": document_id,
            "page_type": "product",
        },
    )
    predicate_id = _identifier(
        "glassgraph:predicate:v1",
        {"ontology_version": "v1", "predicate_key": "achieves_spec"},
    )
    assertion_id = _identifier(
        "glassgraph:assertion:v1",
        {
            "evidence_ids": [golden["first_evidence_id"]],
            "object": {"kind": "scalar", "type": "decimal", "value": "0.98"},
            "predicate_id": predicate_id,
            "subject_id": entity_id,
        },
    )
    assert golden["entity_id"] == entity_id
    assert golden["predicate_id"] == predicate_id
    assert golden["scalar_assertion_id"] == assertion_id


def test_scalar_golden_vectors_normalize_all_adr_inputs():
    assert {_normalize_decimal(value) for value in ("0.980", "+0.98", "00.9800", ".98")} == {"0.98"}
    assert {_normalize_integer(value) for value in ("+001", "01", "1")} == {"1"}


def test_public_queries_cite_computed_evidence_ids():
    payload = json.loads((FIXTURE / "queries.json").read_text(encoding="utf-8"))
    for query in payload["queries"]:
        for group in query["required_groups"]:
            for judgment in group:
                assert SHA256_PATTERN.fullmatch(judgment["evidence_id"])
                assert judgment["evidence_id"] == _judgment_evidence_id(
                    FIXTURE / "corpus",
                    judgment,
                )
        if query["required_groups"]:
            assert query["irrelevant"]
            for judgment in query["irrelevant"]:
                assert judgment["grade"] == "irrelevant"
                assert judgment["evidence_id"] == _judgment_evidence_id(
                    FIXTURE / "corpus",
                    judgment,
                )


def test_public_benchmark_manifest_matches_frozen_inputs(retrieval_benchmark_mod):
    payload = json.loads((FIXTURE / "queries.json").read_text(encoding="utf-8"))
    manifest = payload["manifest"]
    queries = payload["queries"]

    assert manifest["schema_version"] == payload["schema_version"]
    assert manifest["corpus_snapshot_hash"] == retrieval_benchmark_mod.corpus_snapshot_hash(
        FIXTURE / "corpus"
    )
    assert manifest["query_set_hash"] == retrieval_benchmark_mod.query_set_hash(queries)
    assert manifest["judgment_set_hash"] == retrieval_benchmark_mod.judgment_set_hash(queries)
    assert payload["benchmark_version"] == retrieval_benchmark_mod.benchmark_version(
        "public", queries
    )
    assert manifest["split_membership"] == {
        "public": [query["id"] for query in queries]
    }
    assert manifest["adjudication_date"] == "2026-11-09"


def test_corpus_snapshot_hash_normalizes_checkout_line_endings(
    tmp_path, retrieval_benchmark_mod
):
    crlf_root = tmp_path / "corpus"
    crlf_root.mkdir()
    for source in (FIXTURE / "corpus").glob("*.md"):
        normalized = source.read_text(encoding="utf-8").replace("\r\n", "\n")
        (crlf_root / source.name).write_bytes(normalized.replace("\n", "\r\n").encode())

    assert retrieval_benchmark_mod.corpus_snapshot_hash(crlf_root) == (
        retrieval_benchmark_mod.corpus_snapshot_hash(FIXTURE / "corpus")
    )


def test_public_fixture_forces_lf_checkout():
    attributes = (ROOT := FIXTURE.parents[3]) / ".gitattributes"
    assert "tests/fixtures/benchmark/v1/** text eol=lf" in attributes.read_text(
        encoding="utf-8"
    )
