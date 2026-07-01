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

def test_extract_relations_glue(tmp_path):
    body = ("## Key extractions\n\n### Technologies mentioned\n"
            "- [[IGBT]] — predecessor technology to [[SiC-MOSFET]]\n")
    src = tmp_path / "x.md"
    src.write_text("---\ntype: source\n---\n" + body, encoding="utf-8")
    lex = R.load_lexicon(Path(__file__).resolve().parents[1] / "predicates.json")
    types = {"IGBT": "technology", "SiC-MOSFET": "technology"}
    scored = R.extract_relations(src, types, lex, focus=None)
    accepted = [s.rel for s in scored if s.accepted]
    assert R.Relation("[[SiC-MOSFET]]", "succeeds", "[[IGBT]]", "lexicon") in accepted
