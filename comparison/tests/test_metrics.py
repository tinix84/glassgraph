"""Tests for metrics.py — P/R/F1, Jaccard, graph summaries, name normalization."""
from __future__ import annotations

import networkx as nx


def test_precision_recall_perfect_match(metrics_mod):
    truth = {"a": {"Tesla", "BYD"}}
    extracted = {"a": {"Tesla", "BYD"}}
    result = metrics_mod.precision_recall(extracted, truth)
    assert result["macro_precision"] == 1.0
    assert result["macro_recall"] == 1.0
    assert result["macro_f1"] == 1.0


def test_precision_recall_half_correct(metrics_mod):
    truth = {"a": {"Tesla", "BYD"}}
    extracted = {"a": {"Tesla", "Huawei"}}  # Tesla correct, Huawei wrong, BYD missed
    result = metrics_mod.precision_recall(extracted, truth)
    # P = 1/2 = 0.5, R = 1/2 = 0.5, F1 = 0.5
    assert result["macro_precision"] == 0.5
    assert result["macro_recall"] == 0.5
    assert result["macro_f1"] == 0.5


def test_precision_recall_skips_empty_truth(metrics_mod):
    truth = {"a": {"Tesla"}, "b": set()}  # b has no ground truth
    extracted = {"a": {"Tesla"}, "b": {"BYD"}}
    result = metrics_mod.precision_recall(extracted, truth)
    # Only 'a' counts in macro avg; 'b' is excluded (no truth)
    assert result["macro_recall"] == 1.0
    assert result["sources_scored"] == 1
    assert result["sources_skipped_empty_truth"] == 1


def test_jaccard_identical(metrics_mod):
    a = {"src1": {"Tesla", "BYD"}}
    b = {"src1": {"Tesla", "BYD"}}
    j = metrics_mod.mean_jaccard(a, b)
    assert j == 1.0


def test_jaccard_disjoint(metrics_mod):
    a = {"src1": {"Tesla"}}
    b = {"src1": {"BYD"}}
    j = metrics_mod.mean_jaccard(a, b)
    assert j == 0.0


def test_graph_summary_basic(metrics_mod):
    G = nx.DiGraph()
    G.add_edge("src1", "Tesla")
    G.add_edge("src1", "BYD")
    G.add_edge("src2", "Tesla")
    s = metrics_mod.graph_summary(G)
    assert s["nodes"] == 4  # src1, src2, Tesla, BYD
    assert s["edges"] == 3
    assert s["density"] > 0
    top = dict(s["top_in_degree"])
    assert top["Tesla"] == 2


def test_normalize_name_basic_cases(metrics_mod):
    assert metrics_mod.normalize_name("Tesla, Inc.") == "tesla"
    assert metrics_mod.normalize_name("BYD Co. Ltd.") == "byd"
    assert metrics_mod.normalize_name("Tesla") == "tesla"
    assert metrics_mod.normalize_name("The Tesla") == "tesla"
    assert metrics_mod.normalize_name("  Tesla  ") == "tesla"


def test_normalize_name_aggressive_slugify(metrics_mod):
    """Punctuation/whitespace differences should collapse — the main wedge between
    our hyphenated canonicals (SiC-MOSFET) and graphify's free-form labels (SiC MOSFET)."""
    # Hyphen vs space
    assert metrics_mod.normalize_name("SiC-MOSFET") == metrics_mod.normalize_name("SiC MOSFET")
    # Parenthetical aliases dropped
    assert metrics_mod.normalize_name("Texas Instruments (TI)") == metrics_mod.normalize_name("Texas-Instruments")
    # Mixed punctuation
    assert metrics_mod.normalize_name("PFC+LLC+SR") == metrics_mod.normalize_name("PFC / LLC / SR")
    # CJK preserved
    assert metrics_mod.normalize_name("华为DriveONE") == "华为driveone"


def test_match_set_with_normalization(metrics_mod):
    a = {"Tesla, Inc.", "BYD Co. Ltd."}
    b = {"Tesla", "BYD"}
    matches = metrics_mod.match_sets_normalized(a, b)
    # All four entries match after normalization
    assert len(matches) == 2


def test_match_set_with_aggressive_slugify(metrics_mod):
    """Demo-realistic mismatches between our hyphenated wiki and graphify's free-form labels."""
    ours = {"SiC-MOSFET", "Texas-Instruments", "Tesla-Model-3", "Huawei-DriveONE"}
    graphify = {"SiC MOSFET", "Texas Instruments (TI)", "Tesla Model 3 Inverter", "Huawei DriveONE 3-in-1"}
    matches = metrics_mod.match_sets_normalized(ours, graphify)
    # First two collapse on whitespace/punctuation; last two are graphify being
    # more specific than ours (different granularity, won't normalize-match).
    matched_ours = {m[0] for m in matches}
    assert "SiC-MOSFET" in matched_ours
    assert "Texas-Instruments" in matched_ours
