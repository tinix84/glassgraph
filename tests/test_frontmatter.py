"""Tests for the single shared frontmatter parser."""
from __future__ import annotations

import textwrap


def _fm(name="frontmatter"):
    import importlib.util, sys
    from pathlib import Path
    if name in sys.modules:
        return sys.modules[name]
    src = Path(__file__).resolve().parents[1] / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


PAGE = textwrap.dedent("""\
    ---
    type: company
    aliases_en: [Tesla]
    aliases_cn: [特斯拉]
    ---
    Body text here.
""")


def test_parse_basic():
    p = _fm().parse(PAGE)
    assert p.metadata == {"type": "company", "aliases_en": ["Tesla"], "aliases_cn": ["特斯拉"]}
    assert p.body == "Body text here.\n"
    assert p.error is None and not p.duplicate_keys and not p.had_bom


def test_parse_bom_tolerated_and_reported():
    p = _fm().parse("﻿" + PAGE)
    assert p.had_bom is True
    assert p.metadata is not None and p.metadata["type"] == "company"


def test_parse_crlf():
    p = _fm().parse(PAGE.replace("\n", "\r\n"))
    assert p.metadata is not None and p.metadata["type"] == "company"


def test_parse_duplicate_keys_detected():
    text = "---\ntype: company\nupdated: 2026-05-01\nupdated: 2026-06-07\n---\nBody.\n"
    p = _fm().parse(text)
    assert p.duplicate_keys == ["updated"]
    assert p.metadata is not None  # still parses (last wins) but dupes reported


def test_parse_no_frontmatter():
    p = _fm().parse("Just text.\n---\nnot frontmatter\n")
    assert p.metadata is None and p.error is None
    assert p.body == "Just text.\n---\nnot frontmatter\n"


def test_parse_unclosed_delimiter_is_error():
    p = _fm().parse("---\ntype: company\nNo closing delimiter.\n")
    assert p.metadata is None and "not closed" in p.error


def test_parse_four_dashes_is_not_a_delimiter():
    text = "---\ntype: company\n---\nBody with a rule:\n----\nmore body\n"
    p = _fm().parse(text)
    assert p.metadata == {"type": "company"}
    assert "----" in p.body


def test_parse_yaml_error_reported():
    # the documented double-double-quote breakage pattern from log [2026-06-07]
    p = _fm().parse('---\nkey: ""x""\n---\nBody.\n')
    assert p.metadata is None and p.error is not None


def test_parse_non_mapping_is_error():
    p = _fm().parse("---\n- just\n- a list\n---\nBody.\n")
    assert p.metadata is None and "mapping" in p.error


def test_parse_file_detects_bom(tmp_path):
    f = tmp_path / "page.md"
    f.write_bytes(b"\xef\xbb\xbf" + PAGE.encode("utf-8"))
    p = _fm().parse_file(f)
    assert p.had_bom is True and p.metadata["type"] == "company"


def test_wikilink_re_exported():
    m = _fm().WIKILINK_RE.search("see [[SiC-MOSFET|SiC]] here")
    assert m.group(1) == "SiC-MOSFET"
