import importlib.util, sys
from pathlib import Path
import ahocorasick

def _load(name):
    if name in sys.modules:
        return sys.modules[name]
    src = Path(__file__).resolve().parents[1] / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod

relink = _load("relink")

def _automaton(pairs):
    A = ahocorasick.Automaton()
    for alias, canonical in pairs:
        A.add_word(alias, (canonical, alias))
    A.make_automaton()
    return A

def test_relink_wraps_plaintext_entity_in_description():
    A = _automaton([("SiC MOSFET", "SiC-MOSFET"), ("gate driver", "Gate-driver")])
    body = ("## Key extractions\n\n### Companies mentioned\n"
            "- [[STMicroelectronics]] — SiC MOSFET and gate driver supplier\n")
    out = relink.relink_bullets(body, A)
    assert "[[SiC-MOSFET|SiC MOSFET]]" in out
    assert "[[Gate-driver|gate driver]]" in out
    assert "- [[STMicroelectronics]] —" in out          # subject untouched

def test_relink_is_idempotent():
    A = _automaton([("SiC MOSFET", "SiC-MOSFET")])
    body = ("## Key extractions\n\n### Technologies mentioned\n"
            "- [[IGBT]] — replaced by SiC MOSFET\n")
    once = relink.relink_bullets(body, A)
    twice = relink.relink_bullets(once, A)
    assert once == twice
    assert once.count("[[SiC-MOSFET") == 1

def test_relink_skips_existing_links_and_subject():
    A = _automaton([("SiC-MOSFET", "SiC-MOSFET"), ("Tesla", "Tesla")])
    body = ("## Key extractions\n\n### Companies mentioned\n"
            "- [[Tesla]] — Tesla uses [[SiC-MOSFET]] already\n")
    out = relink.relink_bullets(body, A)
    assert out.count("[[SiC-MOSFET") == 1                # existing link not double-wrapped
    assert "[[Tesla|Tesla]]" not in out                 # subject mention not linked

def test_relink_ignores_lines_outside_key_extractions():
    A = _automaton([("SiC MOSFET", "SiC-MOSFET")])
    body = "# TL;DR\n- SiC MOSFET is great\n\n## Quality verdict\n- SiC MOSFET again\n"
    out = relink.relink_bullets(body, A)
    assert out == body                                   # no '### ... mentioned' subsection

def test_relink_bare_link_when_surface_equals_canonical():
    A = _automaton([("Infineon", "Infineon")])
    body = ("## Key extractions\n\n### Companies mentioned\n"
            "- [[Tesla]] — competes with Infineon\n")
    out = relink.relink_bullets(body, A)
    assert "[[Infineon]]" in out
    assert "[[Infineon|Infineon]]" not in out            # no redundant pipe
