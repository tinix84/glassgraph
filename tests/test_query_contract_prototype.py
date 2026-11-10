"""Smoke tests for the portable issue #20 query-contract prototype."""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROTOTYPE = ROOT / "prototypes" / "issue-20-query-contract.html"
EXAMPLE = ROOT / "tests" / "fixtures" / "benchmark" / "v1" / "identity-cases" / "wiki" / "example.md"
PATH_ASSERTION_ID = "sha256:d4cdb32b5f1d1ae3ed800d1502ff784ea67a51c0dba9d9132719059fd1dedacb"


def test_query_contract_verifies_exact_fixture_evidence_only():
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js is not installed")

    source_bytes = EXAMPLE.read_bytes()
    passage = b"Efficiency is 98%.\n"
    byte_start = source_bytes.index(passage)
    line_start = source_bytes[:byte_start].count(b"\n") + 1
    expected = {
        "source_hash": "sha256:" + hashlib.sha256(source_bytes).hexdigest(),
        "line_start": line_start,
        "byte_start": byte_start,
        "byte_end": byte_start + len(passage),
        "path_assertion_id": PATH_ASSERTION_ID,
    }
    script = f"""
const fs = require('fs');
const html = fs.readFileSync({json.dumps(str(PROTOTYPE))}, 'utf8');
const moduleText = html.match(/\\/\\/ BEGIN PORTABLE MODULE([\\s\\S]*?)\\/\\/ END PORTABLE MODULE/)[1];
const QueryContract = new Function(moduleText + '\\nreturn QueryContract;')();
const expected = {json.dumps(expected)};

const fresh = QueryContract.verify(QueryContract.execute('groove', 'fresh', 'search'));
const evidence = fresh.results[0].evidence;
if (fresh.results[0].kind !== 'evidence_hit') throw new Error('fresh hit was not verified');
if (evidence.source_document_hash !== expected.source_hash) throw new Error('source hash mismatch');
if (evidence.locator.lines.start !== expected.line_start) throw new Error('line mismatch');
if (evidence.locator.utf8_bytes.start !== expected.byte_start) throw new Error('byte start mismatch');
if (evidence.locator.utf8_bytes.end !== expected.byte_end) throw new Error('byte end mismatch');

const wrong = QueryContract.execute('groove', 'fresh', 'search');
wrong.results[0].backend_trace.passage = 'Unrelated text.';
const rejected = QueryContract.verify(wrong);
if (rejected.results[0].evidence.evidence_id !== null) throw new Error('wrong passage was certified');

const wrongLocator = QueryContract.execute('groove', 'fresh', 'search');
wrongLocator.results[0].backend_trace.heading_path = ['Other'];
wrongLocator.results[0].backend_trace.line = 12;
wrongLocator.results[0].backend_trace.source_document_hash = 'sha256:' + '0'.repeat(64);
const locatorRejected = QueryContract.verify(wrongLocator);
if (locatorRejected.results[0].evidence.evidence_id !== null) throw new Error('wrong locator was certified');

const staleExplain = QueryContract.execute('groove', 'stale', 'explain');
if (staleExplain.results.some(result => (result.evidence_ids || []).length)) throw new Error('stale explain exposed evidence ID');
const freshExplain = QueryContract.execute('groove', 'fresh', 'explain');
if (freshExplain.results.some(result => (result.evidence_ids || []).length)) throw new Error('unverified explain exposed evidence ID');

const typedPath = QueryContract.execute('groove', 'fresh', 'path');
const edge = typedPath.results[0].steps.find(step => step.kind === 'edge').edge;
if (edge.id !== expected.path_assertion_id) throw new Error('typed path used the wrong assertion ID');
"""

    completed = subprocess.run(
        [node, "-e", script],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
