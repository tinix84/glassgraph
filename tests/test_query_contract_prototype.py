"""Smoke tests for the portable issue #20 query-contract prototype."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import unicodedata
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototypes" / "issue-20-query-contract.html"
EXAMPLE = ROOT / "tests" / "fixtures" / "benchmark" / "v1" / "identity-cases" / "wiki" / "example.md"
GOLDEN = ROOT / "tests" / "fixtures" / "benchmark" / "v1" / "golden-identifiers.json"


def _identifier(domain, payload):
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    normalized = unicodedata.normalize("NFC", canonical)
    return "sha256:" + hashlib.sha256(f"{domain}\0{normalized}".encode()).hexdigest()


def test_query_contract_verifies_exact_fixture_evidence_only():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")

    source_bytes = EXAMPLE.read_bytes()
    golden = json.loads(GOLDEN.read_text(encoding="utf-8"))
    passage = b"Unicode heading evidence.\n"
    byte_start = source_bytes.index(passage)
    line_start = source_bytes[:byte_start].count(b"\n") + 1
    tesla_document_id = _identifier(
        "glassgraph:document:v1",
        {"path": "wiki/Tesla.md"},
    )
    tesla_entity_id = _identifier(
        "glassgraph:entity:v1",
        {
            "canonical_name": "Tesla",
            "document_id": tesla_document_id,
            "page_type": "company",
        },
    )
    predicate_id = _identifier(
        "glassgraph:predicate:v1",
        {"ontology_version": "v1", "predicate_key": "vendor_of"},
    )
    assertion_id = _identifier(
        "glassgraph:assertion:v1",
        {
            "evidence_ids": [golden["vendor_evidence_id"]],
            "object": {"kind": "entity", "id": golden["entity_id"]},
            "predicate_id": predicate_id,
            "subject_id": tesla_entity_id,
        },
    )
    expected = {
        "source_hash": "sha256:" + hashlib.sha256(source_bytes).hexdigest(),
        "line_start": line_start,
        "byte_start": byte_start,
        "byte_end": byte_start + len(passage),
        "vendor_evidence_id": golden["vendor_evidence_id"],
        "vendor_entity_id": tesla_entity_id,
        "product_entity_id": golden["entity_id"],
        "vendor_predicate_id": predicate_id,
        "path_assertion_id": assertion_id,
    }
    script = f"""
const fs = require('fs');
const html = fs.readFileSync({json.dumps(str(PROTOTYPE))}, 'utf8');
const moduleText = html.match(/\\/\\/ BEGIN PORTABLE MODULE([\\s\\S]*?)\\/\\/ END PORTABLE MODULE/)[1];
const QueryContract = new Function(moduleText + '\\nreturn QueryContract;')();
const expected = {json.dumps(expected)};

const fresh = QueryContract.verify(QueryContract.execute('groove', 'fresh', 'search'));
const evidence = fresh.results[0].evidence;
const backendTrace = fresh.results[0].backend_trace;
if (fresh.results[0].kind !== 'evidence_hit') throw new Error('fresh hit was not verified');
if (backendTrace.locator_kind !== 'utf8_match_span') throw new Error('wrong backend locator kind');
if (!Array.isArray(backendTrace.match_spans) || backendTrace.match_spans.length !== 1) throw new Error('backend match spans were not preserved');
if (backendTrace.match_spans[0].start !== 0 || backendTrace.match_spans[0].end !== Buffer.byteLength(backendTrace.passage, 'utf8')) throw new Error('backend match span mismatch');
if (evidence.source_document_hash !== expected.source_hash) throw new Error('source hash mismatch');
if (evidence.locator.lines.start !== expected.line_start) throw new Error('line mismatch');
if (evidence.locator.utf8_bytes.start !== expected.byte_start) throw new Error('byte start mismatch');
if (evidence.locator.utf8_bytes.end !== expected.byte_end) throw new Error('byte end mismatch');

const wrong = QueryContract.execute('groove', 'fresh', 'search');
wrong.results[0].backend_trace.passage = 'Unrelated text.';
const rejected = QueryContract.verify(wrong);
if (rejected.results[0].evidence.evidence_id !== null) throw new Error('wrong passage was certified');

const ambiguous = QueryContract.execute('groove', 'fresh', 'search');
ambiguous.results[0].backend_trace.passage = 'Efficiency is 98%.\\n';
ambiguous.results[0].backend_trace.match_spans = [{{ start:0, end:19 }}];
const ambiguousRejected = QueryContract.verify(ambiguous);
if (ambiguousRejected.results[0].evidence.evidence_id !== null) throw new Error('ambiguous passage was certified');

const wrongSnapshot = QueryContract.execute('groove', 'fresh', 'search');
wrongSnapshot.index.corpus_snapshot_hash = 'sha256:' + '0'.repeat(64);
const snapshotRejected = QueryContract.verify(wrongSnapshot);
if (snapshotRejected.results[0].evidence.evidence_id !== null) throw new Error('wrong corpus snapshot was certified');

const wrongBackendSnapshot = QueryContract.execute('qmd', 'fresh', 'search');
if (wrongBackendSnapshot.results[0].backend_trace.line !== 16) throw new Error('QMD line was not preserved');
wrongBackendSnapshot.execution.backend_snapshot_hash = 'sha256:' + '0'.repeat(64);
const backendSnapshotRejected = QueryContract.verify(wrongBackendSnapshot);
if (backendSnapshotRejected.results[0].evidence.evidence_id !== null) throw new Error('wrong backend snapshot was certified');

const staleExplain = QueryContract.execute('groove', 'stale', 'explain');
if (staleExplain.results.some(result => (result.evidence_ids || []).length)) throw new Error('stale explain exposed evidence ID');
const freshExplain = QueryContract.execute('groove', 'fresh', 'explain');
if (freshExplain.results.some(result => (result.evidence_ids || []).length)) throw new Error('unverified explain exposed evidence ID');
if (freshExplain.results[0].trace.some(stage => stage.stage === 'compiler_verification' && /checked|verified/i.test(stage.detail))) throw new Error('standalone explain claimed verification');

const typedPath = QueryContract.execute('groove', 'fresh', 'path');
const edge = typedPath.results[0].steps.find(step => step.kind === 'edge').edge;
if (edge.id !== expected.path_assertion_id) throw new Error('typed path used the wrong assertion ID');
if (edge.predicate_id !== expected.vendor_predicate_id || edge.predicate_key !== 'vendor_of') throw new Error('typed path used the wrong predicate');
if (edge.subject_id !== expected.vendor_entity_id) throw new Error('typed path used the wrong vendor subject');
if (edge.object.id !== expected.product_entity_id) throw new Error('typed path used the wrong product object');
if (edge.direction !== 'reverse') throw new Error('product-to-vendor traversal was not reverse');
if (edge.evidence_ids.length !== 1 || edge.evidence_ids[0] !== expected.vendor_evidence_id) throw new Error('typed path used unrelated evidence');

const relatedRequest = QueryContract.requestFor('related');
if (!relatedRequest.filters.page_types.includes('company')) throw new Error('related result violates the page type filter');
if (!relatedRequest.filters.page_types.includes('product')) throw new Error('related source violates the page type filter');

for (const operation of ['related', 'path']) {{
  const staleGraph = QueryContract.execute('groove', 'stale', operation);
  if (staleGraph.results.length) throw new Error(`stale ${{operation}} exposed canonical graph IDs`);
}}
"""

    completed = subprocess.run(
        [node, "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
