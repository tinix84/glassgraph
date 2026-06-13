"""CLI entry point: link.py raw/X.md | link.py backfill"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import sys
from datetime import date
from pathlib import Path

# Force UTF-8 stdout on Windows — fixes UnicodeEncodeError when printing CJK
# filenames or canonicals. Safe no-op on systems where stdout already speaks UTF-8.
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

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


def _import_lint():
    return _import_module("lint")


def _result_to_dict(result) -> dict:
    out = {
        "source": result.source,
        "extracted_at": result.extracted_at,
        "manifest_sha": result.manifest_sha,
        "entities": [dataclasses.asdict(e) for e in result.entities],
        "disambiguation_warnings": result.disambiguation_warnings,
    }
    if result.vector_entities is not None:
        out["vector_entities"] = [dataclasses.asdict(h) for h in result.vector_entities]
        out["vector_manifest_sha"] = result.vector_manifest_sha
    return out


def run_single(
    raw_path: Path,
    wiki_root: Path = _WIKI_ROOT,
    index_dir: Path = _INDEX_DIR,
    cache_dir: Path = _CACHE_DIR,
    dry_run: bool = False,
    force: bool = False,
    verbose: bool = False,
    vector: bool = False,
    top_k: int = 20,
    threshold: float | None = None,
    rebuild_embeddings: bool = False,
) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_file = cache_dir / (raw_path.stem + ".json")

    index_mod = _import_index()
    linker_mod = _import_linker()

    manifest_path = index_dir / "manifest.json"
    aliases_path = index_dir / "aliases.json"
    automaton = index_mod.build_index(wiki_root, manifest_path, aliases_path)

    manifest_sha = hashlib.sha256(aliases_path.read_bytes()).hexdigest()[:16]

    if cache_file.exists() and not force:
        try:
            cached_sha = json.loads(cache_file.read_text(encoding="utf-8")).get("manifest_sha")
        except (json.JSONDecodeError, OSError):
            cached_sha = None
        if cached_sha == manifest_sha:
            print(f"skip (cached, fresh) | {raw_path.name}")
            return

    result = linker_mod.extract_file(
        raw_path, automaton, manifest_sha, _DISAMBIG_YAML
    )

    if vector:
        stage2 = _import_module("stage2")
        embeddings, canonicals = stage2.build_entity_embeddings(wiki_root, force=rebuild_embeddings)
        vector_hits = stage2.run_for_source(raw_path, embeddings, canonicals, top_k=top_k, threshold=threshold)
        result.vector_entities = vector_hits
        result.vector_manifest_sha = stage2.manifest_sha()

    summary = f"extract | {raw_path.name} | entities: {len(result.entities)} | warnings: {len(result.disambiguation_warnings)}"
    if vector:
        summary += f" | vector: {len(result.vector_entities) if result.vector_entities else 0}"
    if verbose:
        for e in result.entities:
            print(f"  {e.canonical} ({e.count}x) via {e.aliases_matched}")
        if result.vector_entities:
            for h in result.vector_entities:
                print(f"  [vector] {h.canonical} cosine={h.cosine:.3f} rank={h.rank}")

    if dry_run:
        print(summary)
        print(json.dumps(_result_to_dict(result), indent=2, ensure_ascii=False))
        return

    cache_file.write_text(
        json.dumps(_result_to_dict(result), indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(summary)


def _lint_gate(wiki_root: Path) -> bool:
    """Run lint and return True if backfill should abort. Prints CRITICAL-only on abort."""
    lint_mod = _import_lint()
    findings = lint_mod.run_lint(wiki_root)
    critical = [f for f in findings if f.severity == "CRITICAL"]
    if not critical:
        return False
    warn_count = sum(1 for f in findings if f.severity == "WARN")
    info_count = sum(1 for f in findings if f.severity == "INFO")
    print(lint_mod.format_report(critical), file=sys.stderr)
    if warn_count or info_count:
        print(
            f"({warn_count} WARN, {info_count} INFO suppressed — run 'link.py lint' for full report)",
            file=sys.stderr,
        )
    print(
        f"\nABORTED: {len(critical)} CRITICAL lint finding(s). Run --no-lint to bypass.",
        file=sys.stderr,
    )
    return True


def run_explain(
    raw_path: Path,
    wiki_root: Path = _WIKI_ROOT,
    index_dir: Path = _INDEX_DIR,
    filter_canonical: str | None = None,
    show_suppressed: bool = False,
    context_chars: int = 30,
) -> None:
    explain_mod = _import_module("explain")
    index_mod = _import_index()
    manifest_path = index_dir / "manifest.json"
    aliases_path = index_dir / "aliases.json"
    automaton = index_mod.build_index(wiki_root, manifest_path, aliases_path)
    out = explain_mod.explain_file(
        raw_path, automaton,
        filter_canonical=filter_canonical,
        show_suppressed=show_suppressed,
        context_chars=context_chars,
        disambiguation_yaml=_DISAMBIG_YAML,
    )
    print(out)


def run_suggest(
    raw_path: Path,
    wiki_root: Path = _WIKI_ROOT,
    index_dir: Path = _INDEX_DIR,
    top_n: int = 20,
) -> None:
    suggest_mod = _import_module("suggest")
    index_mod = _import_index()
    linker = _import_linker()

    aliases_path = index_dir / "aliases.json"
    # Build alias index first (so we know what's already aliased)
    index_mod.build_index(wiki_root, index_dir / "manifest.json", aliases_path)
    known_aliases = set(json.loads(aliases_path.read_text(encoding="utf-8")).keys())

    df_cache = index_dir / "token-df.json"
    df = suggest_mod.load_or_build_df(wiki_root / "sources", df_cache)

    text = raw_path.read_text(encoding="utf-8")
    body = linker._preprocess(text)
    ranked = suggest_mod.rank_candidates(body, known_aliases=known_aliases, df=df, top_n=top_n)
    print(suggest_mod.format_report(ranked))


def run_lookup(
    name: str,
    wiki_root: Path = _WIKI_ROOT,
    index_dir: Path = _INDEX_DIR,
) -> int:
    """Resolve a name/alias to its canonical page via the alias table.

    Dedup check for invariant #3: prints 'canonical | type | path' or NOT FOUND.
    Exit 0 = found, 1 = not found.
    """
    index_mod = _import_index()
    manifest_path = index_dir / "manifest.json"
    aliases_path = index_dir / "aliases.json"
    index_mod.build_index(wiki_root, manifest_path, aliases_path)
    alias_map = json.loads(aliases_path.read_text(encoding="utf-8"))

    canonical = alias_map.get(name)
    if canonical is None:
        lower = {k.lower(): v for k, v in alias_map.items()}
        canonical = lower.get(name.lower())
    if canonical is None:
        print(f"NOT FOUND: '{name}' — no page or alias resolves to it")
        return 1

    _type_name = {"companies": "company", "technologies": "technology", "products": "product", "themes": "theme"}
    for d in ("companies", "technologies", "products", "themes"):
        p = wiki_root / d / f"{canonical}.md"
        if p.exists():
            print(f"{canonical} | {_type_name[d]} | {p}")
            return 0
    print(f"{canonical} | (alias target, page file not located) |")
    return 0


def run_lint_cmd(
    wiki_root: Path = _WIKI_ROOT,
    severity_filter: str | None = None,
) -> int:
    lint_mod = _import_lint()
    findings = lint_mod.run_lint(wiki_root)
    if severity_filter:
        findings = [f for f in findings if f.severity == severity_filter.upper()]
    print(lint_mod.format_report(findings))
    return lint_mod.exit_code_from_findings(findings)


def run_backfill(
    wiki_root: Path = _WIKI_ROOT,
    raw_dir: Path = _RAW_DIR,
    sources_dir: Path = _SOURCES_DIR,
    index_dir: Path = _INDEX_DIR,
    cache_dir: Path = _CACHE_DIR,
    report_path: Path = _REPORT_PATH,
    dry_run: bool = False,
    skip_sanity_gate: bool = False,
    no_lint: bool = False,
    with_history: bool = False,
) -> bool:
    """Returns True if aborted by lint gate, False on normal completion."""
    if not no_lint and _lint_gate(wiki_root):
        return True  # aborted by lint gate

    index_mod = _import_index()
    linker_mod = _import_linker()
    graph_mod = _import_graph()

    manifest_path = index_dir / "manifest.json"
    aliases_path = index_dir / "aliases.json"
    automaton = index_mod.build_index(wiki_root, manifest_path, aliases_path)

    manifest_sha = hashlib.sha256(aliases_path.read_bytes()).hexdigest()[:16]

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

        if sanity_limit and len(stage1_results) == sanity_limit:
            print(f"\n--- Sanity gate: first {sanity_limit} sources ---")
            for stem, canonicals in stage1_results.items():
                print(f"  {stem}: {canonicals}")
            if not sys.stdin.isatty():
                print("Non-interactive session: rerun with --skip-sanity-gate to proceed.",
                      file=sys.stderr)
                sys.exit(2)
            print("--- Continue? Enter to proceed, Ctrl-C to abort. ---")
            try:
                input()
            except (EOFError, KeyboardInterrupt):
                sys.exit(2)
            sanity_limit = None  # gate fires once

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
        return False

    cache_dir.mkdir(parents=True, exist_ok=True)
    report_path.write_text(report, encoding="utf-8")
    print(summary)
    print(f"Report written to {report_path}")

    if with_history:
        from datetime import datetime, timezone
        history_mod = _import_module("history")

        history_path = cache_dir / "backfill-history.jsonl"
        prev = history_mod.read_last_run(history_path)
        entry = history_mod.build_history_entry(
            ts=datetime.now(timezone.utc).isoformat(),
            match_rate=graph_mod.compute_match_rate(G_current, G_stage1, sources),
            sources=sources,
            orphans=len(graph_mod.get_orphan_entities(G_stage1, entity_nodes)),
            phantoms=len(phantoms),
            G_current=G_current,
            G_stage1=G_stage1,
            entity_nodes=entity_nodes,
            top_n=50,
        )
        if prev:
            delta = history_mod.compute_delta(prev, entry, min_abs_delta=3)
            delta_section = history_mod.format_delta_section(delta)
            with report_path.open("a", encoding="utf-8") as f:
                f.write(delta_section)
            print(delta_section)
        else:
            print("\n(First backfill — no previous run to compare)")
        history_mod.append_run(history_path, entry)
        print(f"History entry appended to {history_path}")

    return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Deterministic entity linking for 2brain wiki")
    parser.add_argument("command", help="'backfill' | 'lint' | 'lookup' | 'explain' | 'suggest' | path to raw/*.md")
    parser.add_argument("extra", nargs="?", default=None, help="File path for explain/suggest commands")
    parser.add_argument("--force", action="store_true", help="Overwrite existing cache")
    parser.add_argument("--dry-run", action="store_true", help="Print to stdout, no files written")
    parser.add_argument("--verbose", action="store_true", help="Show per-entity hits")
    parser.add_argument("--skip-sanity-gate", action="store_true", help="Skip 10-source pause in backfill")
    parser.add_argument("--no-lint", action="store_true", help="Skip lint gate at start of backfill")
    parser.add_argument("--history", action="store_true", help="Track delta vs previous backfill")
    parser.add_argument("--filter", default=None, help="Filter explain output to one canonical")
    parser.add_argument("--suppressed", action="store_true", help="Show suppressed disambiguation hits")
    parser.add_argument("--context", type=int, default=30, help="Context chars around each hit")
    parser.add_argument("--severity", default=None, choices=["CRITICAL", "WARN", "INFO"],
                        help="Filter lint output to a single severity level")
    parser.add_argument("--vector", action="store_true", help="Enable Stage 2 BGE-M3 vector retrieval")
    parser.add_argument("--top-k", type=int, default=20, help="Stage 2 top-K (default 20)")
    parser.add_argument("--threshold", type=float, default=None, help="Stage 2 cosine threshold filter")
    parser.add_argument("--rebuild-embeddings", action="store_true", help="Force re-embed entity matrix")
    args = parser.parse_args()

    if args.command == "lint":
        sys.exit(run_lint_cmd(severity_filter=args.severity))
    elif args.command == "backfill":
        aborted = run_backfill(dry_run=args.dry_run, skip_sanity_gate=args.skip_sanity_gate, no_lint=args.no_lint, with_history=args.history)
        if aborted:
            sys.exit(1)
    elif args.command == "explain":
        if args.extra is None:
            print("ERROR: explain requires a raw file path", file=sys.stderr)
            sys.exit(1)
        run_explain(Path(args.extra), filter_canonical=args.filter, show_suppressed=args.suppressed, context_chars=args.context)
    elif args.command == "suggest":
        if args.extra is None:
            print("ERROR: suggest requires a raw file path", file=sys.stderr)
            sys.exit(1)
        run_suggest(Path(args.extra))
    elif args.command == "lookup":
        if args.extra is None:
            print("ERROR: lookup requires a name", file=sys.stderr)
            sys.exit(1)
        sys.exit(run_lookup(args.extra))
    else:
        raw_path = Path(args.command)
        if not raw_path.exists():
            print(f"ERROR: file not found: {raw_path}", file=sys.stderr); sys.exit(1)
        run_single(
            raw_path,
            dry_run=args.dry_run,
            force=args.force,
            verbose=args.verbose,
            vector=args.vector,
            top_k=args.top_k,
            threshold=args.threshold,
            rebuild_embeddings=args.rebuild_embeddings,
        )


if __name__ == "__main__":
    main()
