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

m = _load("relation_metrics")

def test_wilson_lower_bound_small_n_is_conservative():
    assert m.wilson_lower_bound(4, 4) < 0.8    # 4/4 must NOT clear the 0.80 bar
    assert m.wilson_lower_bound(19, 20) > 0.7  # 19/20 is a strong signal

def test_score_per_predicate():
    pred = {("[[A]]", "uses", "[[B]]"), ("[[A]]", "uses", "[[C]]")}
    gold = {("[[A]]", "uses", "[[B]]"), ("[[A]]", "supplies", "[[D]]")}
    out = m.score(pred, gold)
    assert out["uses"]["tp"] == 1 and out["uses"]["fp"] == 1
    assert out["uses"]["precision"] == 0.5
    assert out["supplies"]["fn"] == 1 and out["supplies"]["tp"] == 0
