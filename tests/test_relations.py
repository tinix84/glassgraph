import importlib.util, sys
from pathlib import Path

def _load(name):
    if name in sys.modules:
        return sys.modules[name]
    src = Path(__file__).resolve().parents[1] / f"{name}.py"
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
