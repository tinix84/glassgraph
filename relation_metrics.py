"""Per-predicate precision/recall/F1 with Wilson lower bound, vs frozen gold."""
from __future__ import annotations

import math


def wilson_lower_bound(hits: int, n: int, z: float = 1.96) -> float:
    if n == 0:
        return 0.0
    phat = hits / n
    denom = 1 + z * z / n
    centre = phat + z * z / (2 * n)
    margin = z * math.sqrt((phat * (1 - phat) + z * z / (4 * n)) / n)
    return (centre - margin) / denom


def score(predicted: set[tuple], gold: set[tuple]) -> dict[str, dict]:
    preds = {p for _, p, _ in predicted} | {p for _, p, _ in gold}
    out: dict[str, dict] = {}
    for p in preds:
        P = {t for t in predicted if t[1] == p}
        G = {t for t in gold if t[1] == p}
        tp = len(P & G); fp = len(P - G); fn = len(G - P)
        precision = tp / (tp + fp) if (tp + fp) else 0.0
        recall = tp / (tp + fn) if (tp + fn) else 0.0
        f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
        out[p] = {"tp": tp, "fp": fp, "fn": fn, "precision": precision,
                  "recall": recall, "f1": f1,
                  "precision_lb": wilson_lower_bound(tp, tp + fp), "n_pred": tp + fp}
    return out
