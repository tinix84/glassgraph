"""CLI entry point: link.py raw/X.md | link.py backfill"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
from datetime import date
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_TOOLS = _HERE.parent
_WIKI_ROOT = _TOOLS.parent / "wiki"
_INDEX_DIR = _TOOLS / "index"
_CACHE_DIR = _TOOLS / "extraction-cache"
_RAW_DIR = _TOOLS.parent / "raw"
_SOURCES_DIR = _WIKI_ROOT / "sources"
_DISAMBIG_YAML = _INDEX_DIR / "disambiguation.yaml"
_REPORT_PATH = _CACHE_DIR / "backfill-delta.md"


# Lazy imports so test fixtures can override paths without triggering side effects
def _import_module(name: str) -> object:
    """Load a sibling module by name, registering it in sys.modules before exec."""
    import importlib.util
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, _HERE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # must register before exec_module (dataclass needs it)
    spec.loader.exec_module(mod)
    return mod


def _import_index():
    return _import_module("index")


def _import_linker():
    return _import_module("linker")


def _import_graph():
    return _import_module("graph")


def _result_to_dict(result) -> dict:
    return {
        "source": result.source,
        "extracted_at": result.extracted_at,
        "manifest_sha": result.manifest_sha,
        "entities": [dataclasses.asdict(e) for e in result.entities],
        "disambiguation_warnings": result.disambiguation_warnings,
    }


def run_single(
    raw_path: Path,
    wiki_root: Path = _WIKI_ROOT,
    index_dir: Path = _INDEX_DIR,
    cache_dir: Path = _CACHE_DIR,
    dry_run: bool = False,
    force: bool = False,
    verbose: bool = False,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / (raw_path.stem + ".json")

    if cache_file.exists() and not force:
        print(f"skip (cached) | {raw_path.name}")
        return

    index_mod = _import_index()
    linker_mod = _import_linker()

    manifest_path = index_dir / "manifest.json"
    aliases_path = index_dir / "aliases.json"
    automaton = index_mod.build_index(wiki_root, manifest_path, aliases_path)

    import hashlib
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()[:16]

    result = linker_mod.extract_file(
        raw_path, automaton, manifest_sha, _DISAMBIG_YAML
    )

    summary = f"extract | {raw_path.name} | entities: {len(result.entities)} | warnings: {len(result.disambiguation_warnings)}"
    if verbose:
        for e in result.entities:
            print(f"  {e.canonical} ({e.count}x) via {e.aliases_matched}")

    if dry_run:
        print(summary)
        print(json.dumps(_result_to_dict(result), indent=2, ensure_ascii=False))
        return

    cache_file.write_text(
        json.dumps(_result_to_dict(result), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(summary)


def run_backfill(
    wiki_root: Path = _WIKI_ROOT,
    raw_dir: Path = _RAW_DIR,
    sources_dir: Path = _SOURCES_DIR,
    index_dir: Path = _INDEX_DIR,
    cache_dir: Path = _CACHE_DIR,
    report_path: Path = _REPORT_PATH,
    dry_run: bool = False,
    skip_sanity_gate: bool = False,
) -> None:
    index_mod = _import_index()
    linker_mod = _import_linker()
    graph_mod = _import_graph()

    manifest_path = index_dir / "manifest.json"
    aliases_path = index_dir / "aliases.json"
    automaton = index_mod.build_index(wiki_root, manifest_path, aliases_path)

    import hashlib
    manifest_sha = hashlib.sha256(manifest_path.read_bytes()).hexdigest()[:16]

    source_pages = sorted(p for p in sources_dir.glob("*.md") if ".archive" not in str(p))
    stage1_results: dict[str, list[str]] = {}

    sanity_limit = None if skip_sanity_gate else 10

    for i, source_page in enumerate(source_pages):
        raw_file = raw_dir / source_page.name
        if not raw_file.exists():
            print(f"WARN raw file not found: {source_page.name}")
            continue
        result = linker_mod.extract_file(raw_file, automaton, manifest_sha, _DISAMBIG_YAML)
        stage1_results[source_page.stem] = [e.canonical for e in result.entities]

        if sanity_limit and i + 1 == sanity_limit:
            print(f"\n--- Sanity gate: first {sanity_limit} sources ---")
            for stem, canonicals in stage1_results.items():
                print(f"  {stem}: {canonicals}")
            print("--- Continue? Run with --skip-sanity-gate to bypass. Ctrl-C to abort. ---")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                sys.exit(0)

    G_current = graph_mod.build_current_graph(sources_dir)
    G_stage1 = graph_mod.build_stage1_graph(stage1_results)

    entity_nodes = graph_mod._entity_nodes_from_wiki(wiki_root)
    all_s1_canonicals = {c for cs in stage1_results.values() for c in cs}
    phantoms = graph_mod.get_phantoms(all_s1_canonicals, wiki_root)
    sources = [p.stem for p in source_pages if (raw_dir / p.name).exists()]

    report = graph_mod.render_report(
        sources=sources,
        G_current=G_current,
        G_stage1=G_stage1,
        entity_nodes=entity_nodes,
        wiki_dir=wiki_root,
        phantom_canonicals=phantoms,
        date_str=date.today().isoformat(),
    )

    summary = (
        f"backfill | {len(sources)} sources | "
        f"match_rate: {graph_mod.compute_match_rate(G_current, G_stage1, sources):.1%} | "
        f"orphan_entities: {len(graph_mod.get_orphan_entities(G_stage1, entity_nodes))} | "
        f"phantoms: {len(phantoms)}"
    )

    if dry_run:
        print(report)
        print(summary)
        return

    cache_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(summary)
    print(f"Report written to {report_path}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic entity linking for 2brain wiki"
    )
    parser.add_argument(
        "command",
        help="'backfill' or path to a raw/*.md file (e.g. raw/Tesla.md)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing cache")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout, no files written")
    parser.add_argument("--verbose", action="store_true", help="Show per-entity hits")
    parser.add_argument("--skip-sanity-gate", action="store_true", help="Skip 10-source pause in backfill")
    args = parser.parse_args()

    if args.command == "backfill":
        run_backfill(dry_run=args.dry_run, skip_sanity_gate=args.skip_sanity_gate)
    else:
        raw_path = Path(args.command)
        if not raw_path.exists():
            print(f"ERROR: file not found: {raw_path}", file=sys.stderr)
            sys.exit(1)
        run_single(raw_path, dry_run=args.dry_run, force=args.force, verbose=args.verbose)


if __name__ == "__main__":
    main()
