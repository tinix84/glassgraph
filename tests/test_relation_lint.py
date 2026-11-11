import hashlib, importlib.util, sys
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

lint = _load("lint")

def _write(p, body, md5=None):
    fm = ["---", "type: source", "source_url: u", "source_lang: en",
          "source_created: 2026-01-01", "ingested: 2026-01-01",
          "source_kind: teardown", "touches: []", "relations:",
          '  - {s: "[[A]]", p: uses, o: "[[B]]", by: lexicon}']
    if md5 is not None:
        fm.append(f'relations_src_md5: "{md5}"')
    fm.append("---")
    p.write_text("\n".join(fm) + "\n" + body, encoding="utf-8")

def test_relation_drift_flags_stale_hash(tmp_path):
    p = tmp_path / "s.md"
    _write(p, "\nreal body\n", md5="deadbeef")   # wrong hash
    findings = lint.check_relation_drift([p])
    assert any(f.check == "relation-drift" for f in findings)

def test_relation_drift_silent_when_hash_matches(tmp_path):
    p = tmp_path / "s.md"
    body = "\nreal body\n"
    _write(p, body, md5="__x__")
    fm = _load("frontmatter")
    parsed = fm.parse_file(p)
    good = hashlib.md5(parsed.body.strip("\n").encode("utf-8")).hexdigest()
    _write(p, body, md5=good)
    findings = lint.check_relation_drift([p])
    assert not any(f.check == "relation-drift" for f in findings)

def test_malformed_relations_flagged(tmp_path):
    p = tmp_path / "bad.md"
    p.write_text('---\ntype: source\nrelations: "notalist"\n---\nbody', encoding="utf-8")
    findings = lint.check_malformed_relations([p])
    assert any(f.check == "malformed-relation" and f.severity == "CRITICAL" for f in findings)
