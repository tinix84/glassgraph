"""Read-only assist-contract demonstration using the public synthetic fixture."""
import json
from pathlib import Path

from glassgraph.assist import apply_advice, build_packet
from glassgraph.core.retrieval_benchmark import derive_evidence_records


def main():
    corpus = Path(__file__).resolve().parents[1] / "tests/fixtures/benchmark/v1/corpus"
    passage = "Its measured peak efficiency is 99.1% at 180 kW and a 650 V DC input."
    record = derive_evidence_records(corpus, {"path": "auriga-drive.md", "text": passage})[0]
    packet = build_packet(corpus, "What efficiency does Auriga report?", [record])
    output = {"schema_version": "glassgraph.assist-output.v1",
              "packet_hash": packet["packet_hash"], "task": "compress",
              "payload": {"extracts": [{"evidence_id": record["evidence_id"], "quote": passage}]}}
    results = {
        "fixture": "public synthetic; no model executed",
        "deterministic": apply_advice(corpus, packet),
        "advisory": apply_advice(corpus, packet, enabled=True, response=json.dumps(output)),
        "invalid_output_fallback": apply_advice(corpus, packet, enabled=True, response="invalid"),
    }
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
