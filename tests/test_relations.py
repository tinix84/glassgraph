import importlib.util, sys
from pathlib import Path as _P

def _load(name):
    if name in sys.modules:
        return sys.modules[name]
    src = _P(__file__).resolve().parents[1] / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

R = _load("relations")

def test_ten_predicates_partitioned():
    assert len(R.PREDICATES) == 10
    assert R.DERIVED == frozenset({"vendor_of", "mentions", "evidence_for"})
    assert R.SYMMETRIC == frozenset({"competes_with", "partners_with"})
    assert "uses" in R.EXTRACTED and "vendor_of" not in R.EXTRACTED

def test_canonical_orders_symmetric_only():
    sym = R.Relation(s="[[Zeta]]", p="competes_with", o="[[Alpha]]", by="lexicon")
    assert R.canonical(sym) == R.Relation(s="[[Alpha]]", p="competes_with", o="[[Zeta]]", by="lexicon")
    directed = R.Relation(s="[[Zeta]]", p="succeeds", o="[[Alpha]]", by="lexicon")
    assert R.canonical(directed) == directed

def test_load_lexicon_seed(tmp_path):
    import json
    p = tmp_path / "predicates.json"
    p.write_text(json.dumps([
        {"trigger": "Supplier", "predicate": "supplies",
         "subj_type": "company", "obj_type": "technology",
         "direction": "subject_to_object"}
    ]), encoding="utf-8")
    entries = R.load_lexicon(p)
    assert entries[0].predicate == "supplies"
    assert entries[0].trigger == "supplier"          # lowercased
    assert entries[0].direction == "subject_to_object"

def test_load_lexicon_rejects_unknown_predicate(tmp_path):
    import json, pytest
    p = tmp_path / "bad.json"
    p.write_text(json.dumps([
        {"trigger": "x", "predicate": "frobnicates",
         "subj_type": "company", "obj_type": "technology",
         "direction": "subject_to_object"}]), encoding="utf-8")
    with pytest.raises(ValueError):
        R.load_lexicon(p)

def test_shipped_seed_lexicon_is_valid():
    # predicates.json sits next to relations.py, i.e. one level up from tests/
    seed = _P(__file__).resolve().parents[1] / "predicates.json"
    entries = R.load_lexicon(seed)
    assert len(entries) >= 8
    assert all(e.predicate in R.EXTRACTED for e in entries)


SAMPLE_BODY = """# Source: X

## Key extractions

### Companies mentioned
- [[STMicroelectronics]] — SiC MOSFET and [[SiC-MOSFET]] gate driver supplier
- [[Tesla]] — designer/OEM of the inverter

### Technologies mentioned
- [[IGBT]] — predecessor technology to [[SiC-MOSFET]]

## Quality verdict
- irrelevant
"""

def test_parse_key_extractions():
    bullets = R.parse_key_extractions(SAMPLE_BODY)
    subs = {b.subject for b in bullets}
    assert subs == {"STMicroelectronics", "Tesla", "IGBT"}
    st = next(b for b in bullets if b.subject == "STMicroelectronics")
    assert "SiC-MOSFET" in st.links

def test_resolve_object_prefers_in_bullet_link():
    b = R.Bullet(subject="STMicroelectronics", text="... supplier",
                 links=("SiC-MOSFET",))
    entry = R.LexEntry("supplier", "supplies", "company", "technology", "subject_to_object")
    assert R.resolve_object(b, entry, focus="Tesla") == "SiC-MOSFET"

def test_resolve_object_falls_back_to_focus_then_none():
    b = R.Bullet(subject="Tesla", text="designer/OEM", links=())
    entry = R.LexEntry("designer", "vendor_of", "company", "product", "subject_to_object")
    assert R.resolve_object(b, entry, focus="Inverter") == "Inverter"
    assert R.resolve_object(b, entry, focus=None) is None

def test_lexicon_vote_direction_and_wrapping():
    bullets = R.parse_key_extractions(SAMPLE_BODY)
    types = {"STMicroelectronics": "company", "Tesla": "company",
             "IGBT": "technology", "SiC-MOSFET": "technology"}
    lex = R.load_lexicon(_P(__file__).resolve().parents[1] / "predicates.json")
    rels = R.lexicon_vote(bullets, types, lex, focus=None)
    # "IGBT — predecessor ... [[SiC-MOSFET]]" ⇒ SiC-MOSFET succeeds IGBT (object_to_subject)
    assert R.Relation("[[SiC-MOSFET]]", "succeeds", "[[IGBT]]", "lexicon") in rels
    # "STMicroelectronics — ... supplier ... [[SiC-MOSFET]]" ⇒ ST supplies SiC-MOSFET
    assert R.Relation("[[STMicroelectronics]]", "supplies", "[[SiC-MOSFET]]", "lexicon") in rels


def test_derived_vendor_of():
    rels = R.derived_edges("Tesla-Model-3-inverter", "product",
                           {"vendor": "[[Tesla]]"})
    assert R.Relation("[[Tesla]]", "vendor_of", "[[Tesla-Model-3-inverter]]", "derived") in rels

def test_derived_mentions_from_touches():
    rels = R.derived_edges("some-source", "source",
                           {"touches": ["[[Tesla]]", "[[SiC-MOSFET]]"]})
    assert R.Relation("[[some-source]]", "mentions", "[[Tesla]]", "derived") in rels
    assert len(rels) == 2

def test_derived_evidence_for_from_theme_sources():
    rels = R.derived_edges("Si-to-SiC-transition", "theme",
                           {"sources": ["srcA.md", "srcB.md"]})
    assert R.Relation("[[srcA]]", "evidence_for", "[[Si-to-SiC-transition]]", "derived") in rels


def test_combine_single_voter_floor_accepts():
    lex = [R.Relation("[[A]]", "uses", "[[B]]", "lexicon")]
    scored = R.combine([lex], min_votes=2)
    assert len(scored) == 1
    assert scored[0].accepted is True          # single-voter floor
    assert scored[0].rel.by == "lexicon"
    assert scored[0].conf == 1.0

def test_combine_majority_marks_consensus():
    a = R.Relation("[[A]]", "uses", "[[B]]", "lexicon")
    b = R.Relation("[[A]]", "uses", "[[B]]", "glirel")
    c = R.Relation("[[A]]", "supplies", "[[B]]", "depparse")
    scored = {s.rel.p: s for s in R.combine([[a], [b], [c]], min_votes=2)}
    assert scored["uses"].votes == 2 and scored["uses"].accepted
    assert scored["uses"].rel.by == "consensus"
    assert scored["supplies"].votes == 1 and not scored["supplies"].accepted
