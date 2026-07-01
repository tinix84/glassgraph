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

rg = _load("relation_graph")

def _src(dir, name, rels):
    lines = ["---", "type: source", "source_url: u", "source_lang: en",
             "source_created: 2026-01-01", "ingested: 2026-01-01",
             "source_kind: teardown", "touches: []", "relations:"]
    lines += [f'  - {{s: "{s}", p: {p}, o: "{o}", by: lexicon}}' for s, p, o in rels]
    lines += ['relations_src_md5: "x"', "---", "body"]
    (dir / name).write_text("\n".join(lines), encoding="utf-8")

def test_directed_edge_added(tmp_path):
    _src(tmp_path, "a.md", [("[[Tesla]]", "uses", "[[SiC-MOSFET]]")])
    g = rg.build_relation_graph(tmp_path)
    assert g.has_edge("Tesla", "SiC-MOSFET")

def test_symmetric_expands_both_ways(tmp_path):
    _src(tmp_path, "b.md", [("[[Huawei]]", "competes_with", "[[Delta]]")])
    g = rg.build_relation_graph(tmp_path)
    assert g.has_edge("Huawei", "Delta") and g.has_edge("Delta", "Huawei")

def test_export_roundtrip(tmp_path):
    _src(tmp_path, "a.md", [("[[Tesla]]", "uses", "[[SiC-MOSFET]]")])
    g = rg.build_relation_graph(tmp_path)
    rg.export_json(g, tmp_path / "graph.json")
    rg.export_graphml(g, tmp_path / "graph.graphml")
    assert (tmp_path / "graph.json").exists()
    assert (tmp_path / "graph.graphml").exists()
