"""Private, model-free validation of evidence packets and advisory output."""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json

from glassgraph.core.retrieval_benchmark import derive_evidence_records

PACKET_SCHEMA = "glassgraph.assist-packet.v1"
MAX_PACKET_BYTES = 32_768
MAX_EVIDENCE = 20
OUTPUT_SCHEMA = "glassgraph.assist-output.v1"
MAX_OUTPUT_BYTES = 8_192


class AssistError(ValueError):
    """Reject stale evidence or an invalid assist contract."""


def _bytes(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def _hash(value):
    return "sha256:" + hashlib.sha256(b"glassgraph:assist-packet:v1\0" + _bytes(value)).hexdigest()


def build_packet(corpus_root, query: str, evidence: list[dict]) -> dict:
    """Build a bounded packet from exact, current ADR-0013 evidence records."""
    if not isinstance(query, str) or not query.strip():
        raise AssistError("Supply a nonempty research query")
    if not isinstance(evidence, list) or len(evidence) > MAX_EVIDENCE:
        raise AssistError("Supply at most 20 evidence records")
    try:
        if len(_bytes({"query": query, "evidence": evidence})) > MAX_PACKET_BYTES:
            raise AssistError("Reduce the evidence packet below the byte budget")
        current = []
        seen = set()
        for record in evidence:
            records = derive_evidence_records(corpus_root, {
                "path": record["path"], "text": record["normalized_passage"],
            })
            if not any(_bytes(record) == _bytes(item) for item in records):
                raise AssistError("Resolve evidence against the current Markdown")
            if record["evidence_id"] not in seen:
                current.append(deepcopy(record))
                seen.add(record["evidence_id"])
    except (OSError, UnicodeError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, AssistError):
            raise
        raise AssistError("Resolve evidence against the current Markdown") from None
    packet = {"schema_version": PACKET_SCHEMA, "query": query, "evidence": current}
    packet["packet_hash"] = _hash(packet)
    if len(_bytes(packet)) > MAX_PACKET_BYTES:
        raise AssistError("Reduce the evidence packet below the byte budget")
    return packet


def validate_packet(corpus_root, packet: dict) -> None:
    """Reject tampered packets and evidence from changed or missing documents."""
    try:
        rebuilt = build_packet(corpus_root, packet["query"], packet["evidence"])
        if packet != rebuilt:
            raise AssistError("Rebuild the evidence packet before assist")
    except (KeyError, TypeError):
        raise AssistError("Supply a valid evidence packet") from None


def _unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise AssistError("Remove duplicate output fields")
        value[key] = item
    return value


def _validate_output(packet, response):
    if not isinstance(response, str) or len(response.encode("utf-8")) > MAX_OUTPUT_BYTES:
        raise AssistError("Supply bounded JSON output")
    output = json.loads(response, object_pairs_hook=_unique_object)
    if (not isinstance(output, dict)
            or set(output) != {"schema_version", "packet_hash", "task", "payload"}
            or output["schema_version"] != OUTPUT_SCHEMA
            or output["packet_hash"] != packet["packet_hash"]):
        raise AssistError("Bind output to the current packet")
    payload = output["payload"]
    if not isinstance(payload, dict):
        raise AssistError("Use an enabled advisory task")
    if output["task"] == "rewrite":
        if (set(payload) != {"query"} or not isinstance(payload["query"], str)
                or not payload["query"].strip() or len(payload["query"].encode("utf-8")) > 1024):
            raise AssistError("Supply a bounded query suggestion")
    elif output["task"] == "disambiguate":
        supplied = {record["evidence_id"] for record in packet["evidence"]}
        selected = payload.get("evidence_ids")
        if (set(payload) != {"evidence_ids"} or not isinstance(selected, list)
                or any(not isinstance(item, str) or item not in supplied for item in selected)
                or len(set(selected)) != len(selected)):
            raise AssistError("Select each supplied evidence ID at most once")
    elif output["task"] == "compress":
        supplied = {record["evidence_id"]: record["normalized_passage"]
                    for record in packet["evidence"]}
        extracts = payload.get("extracts")
        if set(payload) != {"extracts"} or not isinstance(extracts, list) or not extracts:
            raise AssistError("Supply cited exact extracts")
        for extract in extracts:
            if (not isinstance(extract, dict) or set(extract) != {"evidence_id", "quote"}
                    or not isinstance(extract["evidence_id"], str)
                    or extract["evidence_id"] not in supplied
                    or not isinstance(extract["quote"], str) or not extract["quote"].strip()
                    or extract["quote"] not in supplied[extract["evidence_id"]]):
                raise AssistError("Quote a contiguous passage from the cited evidence")
    else:
        raise AssistError("Use an enabled advisory task")
    return {"task": output["task"], "payload": payload, "requires_review": True,
            "authority": "advisory", "packet_hash": packet["packet_hash"]}


def apply_advice(corpus_root, packet: dict, *, enabled: bool = False,
                 response: str | None = None) -> dict:
    """Preserve the deterministic packet unless valid advisory output is supplied."""
    validate_packet(corpus_root, packet)
    if type(enabled) is not bool:
        raise AssistError("Set enabled to a boolean")
    result = {"schema_version": "glassgraph.assist-result.v1",
              "mode": "deterministic", "packet": deepcopy(packet),
              "advice": None, "fallback_reason": None}
    if not enabled:
        return result
    if response is None:
        result["fallback_reason"] = "output_unavailable"
        return result
    try:
        advice = _validate_output(packet, response)
    except (ValueError, TypeError, UnicodeError, RecursionError):
        result["fallback_reason"] = "invalid_output"
        return result
    result.update(mode="advisory", advice=advice, provenance={
        "mode": "supplied-output", "model_runtime_attested": False,
        "output_sha256": "sha256:" + hashlib.sha256(response.encode("utf-8")).hexdigest(),
    })
    return result
