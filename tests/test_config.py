"""Vault discovery through the shared portable configuration interface."""
import pytest


def test_root_precedence_and_upward_discovery(tmp_path, monkeypatch):
    from glassgraph.config import discover_root, ConfigError

    flag = tmp_path / "flag"
    environment = tmp_path / "environment"
    discovered = tmp_path / "discovered"
    for root in (flag, environment, discovered):
        root.mkdir()
    (discovered / ".glassgraph").mkdir()
    nested = discovered / "wiki" / "companies"
    nested.mkdir(parents=True)
    monkeypatch.setenv("GLASSGRAPH_ROOT", str(environment))
    assert discover_root(flag, start=nested) == flag
    assert discover_root(start=nested) == environment
    monkeypatch.delenv("GLASSGRAPH_ROOT")
    assert discover_root(start=nested) == discovered
    with pytest.raises(ConfigError, match="--root.*GLASSGRAPH_ROOT.*.glassgraph"):
        discover_root(start=flag)


def test_config_defaults_and_explicit_layout(tmp_path):
    from glassgraph.config import load_config

    config = load_config(tmp_path)
    assert config.wiki == tmp_path / "wiki"
    assert config.raw == tmp_path / "raw"
    assert config.entity_dirs == ("companies", "technologies", "products", "markets", "themes")
    assert config.exclude == (tmp_path / ".temp",)
    marker = tmp_path / ".glassgraph"
    marker.mkdir()
    (marker / "config.toml").write_text(
        '[paths]\nwiki="notes"\nraw="clippings"\nentity_dirs=["vendors"]\nexclude=["notes/vendors/skip.md"]\n'
        '[zotero]\ndb="library.sqlite"\n', encoding="utf-8",
    )
    config = load_config(tmp_path)
    assert config.wiki == tmp_path / "notes"
    assert config.raw == tmp_path / "clippings"
    assert config.entity_dirs == ("vendors",)
    assert config.exclude == (tmp_path / "notes/vendors/skip.md",)
    assert config.zotero_db == tmp_path / "library.sqlite"


@pytest.mark.parametrize("document", [
    '[paths]\nwiki="../outside"', '[paths]\nraw="C:/outside"',
    '[paths]\nwiki=123', '[paths]\nentity_dirs="companies"',
    '[paths]\nentity_dirs=["companies","companies"]',
    '[paths]\nentity_dirs=["../outside"]', '[paths]\nexclude=".temp"',
    '[paths]\nexclude=[123]', '[paths]\nunknown=true', '[paths]\nwiki=[',
    'paths=1', '[unknown]\nvalue=1', '[zotero]\ndb=1',
    '[paths]\nwiki="\\u0000"', '[paths]\nentity_dirs=["\\u0000"]',
])
def test_invalid_config_is_rejected(tmp_path, document):
    from glassgraph.config import ConfigError, load_config

    (tmp_path / ".glassgraph").mkdir()
    (tmp_path / ".glassgraph/config.toml").write_text(document, encoding="utf-8")
    with pytest.raises(ConfigError):
        load_config(tmp_path)


def test_invalid_explicit_or_environment_root_does_not_fall_back(tmp_path, monkeypatch):
    from glassgraph.config import discover_root, ConfigError

    (tmp_path / ".glassgraph").mkdir()
    monkeypatch.setenv("GLASSGRAPH_ROOT", str(tmp_path))
    with pytest.raises(ConfigError):
        discover_root(tmp_path / "missing", start=tmp_path)
    monkeypatch.setenv("GLASSGRAPH_ROOT", "")
    with pytest.raises(ConfigError):
        discover_root(start=tmp_path)


def test_nearest_marker_and_hook_start_directory(tmp_path, monkeypatch):
    from glassgraph.config import discover_root

    monkeypatch.delenv("GLASSGRAPH_ROOT", raising=False)
    (tmp_path / ".glassgraph").mkdir()
    nested = tmp_path / "nested"
    (nested / ".glassgraph").mkdir(parents=True)
    target_parent = nested / "wiki/companies"
    target_parent.mkdir(parents=True)
    assert discover_root(start=target_parent) == nested


def test_configured_directory_cannot_escape_through_symlink(tmp_path):
    from glassgraph.config import ConfigError, load_config

    vault = tmp_path / "vault"
    (vault / ".glassgraph").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (vault / "wiki").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlink creation is unavailable")
    with pytest.raises(ConfigError, match="inside the vault"):
        load_config(vault)
