"""Shared pytest fixtures for entity_linker tests."""
from __future__ import annotations

import importlib.util
import sys
import textwrap
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[2]  # .tools/


def _load(name: str) -> object:
    if name in sys.modules:
        return sys.modules[name]
    src = _TOOLS / "entity_linker" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="session")
def index_mod():
    return _load("index")


@pytest.fixture(scope="session")
def linker_mod():
    return _load("linker")


@pytest.fixture(scope="session")
def graph_mod():
    return _load("graph")


@pytest.fixture(scope="session")
def lint_mod():
    return _load("lint")


@pytest.fixture(scope="session")
def explain_mod():
    return _load("explain")


@pytest.fixture
def wiki_dir(tmp_path):
    """Synthetic wiki with 3 entity pages: Tesla, BYD, SiC-MOSFET."""
    companies = tmp_path / "wiki" / "companies"
    techs = tmp_path / "wiki" / "technologies"
    companies.mkdir(parents=True)
    techs.mkdir(parents=True)

    (companies / "Tesla.md").write_text(textwrap.dedent("""\
        ---
        type: company
        aliases_en: [Tesla, TSLA]
        aliases_cn: [特斯拉]
        aliases: [Tesla, TSLA, 特斯拉]
        ---
        Tesla is an EV company.
    """), encoding="utf-8")

    (companies / "BYD.md").write_text(textwrap.dedent("""\
        ---
        type: company
        aliases_en: [BYD]
        aliases_cn: [比亚迪]
        aliases: [BYD, 比亚迪]
        ---
        BYD makes EVs.
    """), encoding="utf-8")

    (techs / "SiC-MOSFET.md").write_text(textwrap.dedent("""\
        ---
        type: technology
        aliases_en: [SiC MOSFET, SiC]
        aliases_cn: [碳化硅MOSFET, 碳化硅]
        aliases: [SiC MOSFET, SiC, 碳化硅MOSFET, 碳化硅]
        ---
        SiC MOSFET is a power semiconductor.
    """), encoding="utf-8")

    return tmp_path / "wiki"


@pytest.fixture
def sample_body():
    return (
        "Tesla unveiled a new inverter using SiC MOSFET technology. "
        "特斯拉's competitor BYD (比亚迪) also uses 碳化硅 in their designs. "
        "SiC is widely adopted in power electronics."
    )


@pytest.fixture
def disambiguation_yaml(tmp_path):
    path = tmp_path / "disambiguation.yaml"
    path.write_text(
        "- pattern: Tesla coil\n  reason: Physics term\n",
        encoding="utf-8",
    )
    return path
