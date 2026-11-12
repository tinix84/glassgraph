"""Behavior tests for private evidence packets and untrusted advice."""
import pytest
import json
from copy import deepcopy


def test_packet_contains_current_evidence_and_rejects_edits(tmp_path, retrieval_benchmark_mod):
    from glassgraph.assist import AssistError, build_packet, validate_packet

    source = tmp_path / "example.md"
    source.write_text("# Example\n\nEfficiency is 98%.\n", encoding="utf-8")
    record = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path, {"path": "example.md", "text": "Efficiency is 98%."},
    )[0]
    packet = build_packet(tmp_path, "What is the efficiency?", [record])
    assert packet["evidence"] == [record]
    assert build_packet(tmp_path, "What is the efficiency?", [record]) == packet
    validate_packet(tmp_path, packet)
    source.write_text("# Example\n\nEfficiency is 97%.\n", encoding="utf-8")
    with pytest.raises(AssistError, match="current Markdown"):
        validate_packet(tmp_path, packet)


@pytest.fixture
def packet_case(tmp_path, retrieval_benchmark_mod):
    from glassgraph.assist import build_packet

    (tmp_path / "example.md").write_text("# Example\n\nEfficiency is 98%.\n", encoding="utf-8")
    record = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path, {"path": "example.md", "text": "Efficiency is 98%."},
    )[0]
    return tmp_path, build_packet(tmp_path, "Efficiency?", [record])


def test_assist_is_opt_in_and_missing_output_preserves_packet(packet_case):
    from glassgraph.assist import apply_advice

    root, packet = packet_case
    disabled = apply_advice(root, packet, response="invalid output")
    assert disabled["mode"] == "deterministic"
    assert disabled["packet"] == packet
    assert disabled["advice"] is None
    assert disabled["fallback_reason"] is None
    missing = apply_advice(root, packet, enabled=True)
    assert missing["packet"] == packet
    assert missing["mode"] == "deterministic"
    assert missing["fallback_reason"] == "output_unavailable"


def response_for(packet, task, payload):
    return json.dumps({"schema_version": "glassgraph.assist-output.v1",
                       "packet_hash": packet["packet_hash"], "task": task,
                       "payload": payload})


def test_query_rewrite_is_a_review_suggestion_and_does_not_change_query(packet_case):
    from glassgraph.assist import apply_advice

    root, packet = packet_case
    response = response_for(packet, "rewrite", {"query": "What efficiency is reported?"})
    result = apply_advice(root, packet, enabled=True, response=response)
    assert result["mode"] == "advisory"
    assert result["advice"]["payload"] == {"query": "What efficiency is reported?"}
    assert result["advice"]["requires_review"] is True
    assert result["packet"] == packet
    assert packet["query"] == "Efficiency?"


def test_disambiguation_can_only_select_supplied_evidence_ids(packet_case):
    from glassgraph.assist import apply_advice

    root, packet = packet_case
    evidence_id = packet["evidence"][0]["evidence_id"]
    valid = apply_advice(root, packet, enabled=True, response=response_for(
        packet, "disambiguate", {"evidence_ids": [evidence_id]},
    ))
    assert valid["mode"] == "advisory"
    assert valid["advice"]["payload"]["evidence_ids"] == [evidence_id]
    invalid = apply_advice(root, packet, enabled=True, response=response_for(
        packet, "disambiguate", {"evidence_ids": ["sha256:" + "0" * 64]},
    ))
    assert invalid["fallback_reason"] == "invalid_output"
    assert invalid["packet"] == packet


def test_compression_requires_exact_quotes_and_rejects_invented_facts(packet_case):
    from glassgraph.assist import apply_advice

    root, packet = packet_case
    evidence_id = packet["evidence"][0]["evidence_id"]
    for quote, expected in [("Efficiency is 98%.", "advisory"),
                            ("Efficiency is 99%.", "deterministic")]:
        result = apply_advice(root, packet, enabled=True, response=response_for(
            packet, "compress", {"extracts": [{"evidence_id": evidence_id, "quote": quote}]},
        ))
        assert result["mode"] == expected
        assert result["packet"] == packet


@pytest.mark.parametrize("field,value", [
    ("evidence_id", "sha256:" + "0" * 64),
    ("source_hash", "sha256:" + "0" * 64),
    ("path", "../private.md"), ("utf8_byte_start", 0),
    ("normalized_passage", "Efficiency is 99%.\n"),
])
def test_packet_rejects_forged_identity_or_locator(packet_case, field, value):
    from glassgraph.assist import AssistError, build_packet

    root, packet = packet_case
    record = dict(packet["evidence"][0], **{field: value})
    with pytest.raises(AssistError, match="current Markdown"):
        build_packet(root, packet["query"], [record])


def test_boolean_is_not_an_evidence_coordinate(tmp_path, retrieval_benchmark_mod):
    from glassgraph.assist import AssistError, build_packet

    (tmp_path / "one.md").write_text("Evidence.\n", encoding="utf-8")
    record = retrieval_benchmark_mod.derive_evidence_records(
        tmp_path, {"path": "one.md", "text": "Evidence."},
    )[0]
    record["line_start"] = True
    with pytest.raises(AssistError):
        build_packet(tmp_path, "Evidence?", [record])


@pytest.mark.parametrize("attack", ["wrong-packet", "extra-field", "synthesis", "duplicate-key",
                                   "bad-json", "oversized", "unknown-schema", "wrong-payload"])
def test_invalid_output_falls_back_without_exposing_rejected_text(packet_case, attack):
    from glassgraph.assist import apply_advice

    root, packet = packet_case
    output = json.loads(response_for(packet, "rewrite", {"query": "PRIVATE rejected text"}))
    if attack == "wrong-packet":
        output["packet_hash"] = "sha256:" + "0" * 64
    elif attack == "extra-field":
        output["canonical"] = True
    elif attack == "synthesis":
        output["task"] = "synthesize"
    elif attack == "unknown-schema":
        output["schema_version"] = "future"
    elif attack == "wrong-payload":
        output["payload"] = {"query": 123}
    response = json.dumps(output)
    if attack == "duplicate-key":
        response = response[:-1] + ', "task": "rewrite"}'
    elif attack == "bad-json":
        response = "PRIVATE rejected text"
    elif attack == "oversized":
        response += " " * 8192
    result = apply_advice(root, packet, enabled=True, response=response)
    assert result["mode"] == "deterministic"
    assert result["packet"] == packet
    assert result["fallback_reason"] == "invalid_output"
    assert "PRIVATE" not in json.dumps(result)


def test_packet_budget_deduplication_and_empty_evidence(packet_case):
    from glassgraph.assist import AssistError, build_packet, apply_advice

    root, packet = packet_case
    record = packet["evidence"][0]
    assert build_packet(root, packet["query"], [record, record]) == packet
    with pytest.raises(AssistError, match="byte budget"):
        build_packet(root, "x" * 32768, [])
    with pytest.raises(AssistError, match="at most 20"):
        build_packet(root, "query", [record] * 21)
    empty = build_packet(root, "No answer?", [])
    assert apply_advice(root, empty)["packet"]["evidence"] == []


def test_edit_outside_passage_and_tampered_query_are_rejected(packet_case):
    from glassgraph.assist import AssistError, validate_packet

    root, packet = packet_case
    changed = deepcopy(packet)
    changed["query"] = "Different query"
    with pytest.raises(AssistError):
        validate_packet(root, changed)
    (root / "example.md").write_text("# Example\n\nEfficiency is 98%.\n\nNew content.\n", encoding="utf-8")
    with pytest.raises(AssistError, match="current Markdown"):
        validate_packet(root, packet)


def test_replay_uses_no_network_or_runtime_and_does_not_write(packet_case, monkeypatch):
    import socket
    import subprocess
    from glassgraph.assist import apply_advice

    root, packet = packet_case
    source = root / "example.md"
    before = source.read_bytes()

    def denied(*args, **kwargs):
        raise AssertionError("Transport or inference must not run")

    monkeypatch.setattr(socket, "socket", denied)
    monkeypatch.setattr(subprocess, "Popen", denied)
    result = apply_advice(root, packet, enabled=True, response=response_for(
        packet, "rewrite", {"query": "Reported efficiency?"},
    ))
    assert result["mode"] == "advisory"
    assert result["provenance"]["model_runtime_attested"] is False
    assert source.read_bytes() == before
    assert [path.name for path in root.iterdir()] == ["example.md"]
