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
