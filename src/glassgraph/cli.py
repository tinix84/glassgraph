"""Portable command entry point using the shared vault configuration."""
from __future__ import annotations

import argparse
import json
import sys

from glassgraph.config import ConfigError, load_config
from glassgraph.core import lint


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")
    parser = argparse.ArgumentParser(prog="glassgraph")
    parser.add_argument("--root", help="Vault directory")
    commands = parser.add_subparsers(dest="command", required=True)
    lint_parser = commands.add_parser("lint", help="Read-only deterministic wiki lint")
    lint_parser.add_argument("--root", default=argparse.SUPPRESS, help="Vault directory")
    lint_parser.add_argument("--severity", choices=["CRITICAL", "WARN", "INFO"])
    extract_parser = commands.add_parser("extract", help="Extract Stage 1 entity candidates")
    extract_parser.add_argument("--root", default=argparse.SUPPRESS, help="Vault directory")
    extract_parser.add_argument("source", help="Markdown source path relative to the vault root")
    extract_parser.add_argument("--dry-run", action="store_true", help="Print JSON without writing derived state")
    explain_parser = commands.add_parser("explain", help="Explain Stage 1 matches without writing state")
    explain_parser.add_argument("--root", default=argparse.SUPPRESS, help="Vault directory")
    explain_parser.add_argument("source", help="Markdown source path relative to the vault root")
    explain_parser.add_argument("--filter", dest="filter_canonical", help="Show matches for one canonical entity")
    explain_parser.add_argument("--suppressed", action="store_true", help="Show disambiguation warnings")
    explain_parser.add_argument("--context", type=int, default=30, help="Surrounding characters per side (default: 30)")
    suggest_parser = commands.add_parser("suggest", help="Propose alias candidates without writing state")
    suggest_parser.add_argument("--root", default=argparse.SUPPRESS, help="Vault directory")
    suggest_parser.add_argument("source", help="Markdown source path relative to the vault root")
    suggest_parser.add_argument("--top", type=int, default=20, help="Candidate limit (default: 20)")
    lookup_parser = commands.add_parser("lookup", help="Resolve a name or alias without writing state")
    lookup_parser.add_argument("--root", default=argparse.SUPPRESS, help="Vault directory")
    lookup_parser.add_argument("name", help="Canonical name or alias")
    relink_parser = commands.add_parser("relink", help="Preview source relinking without writing the page")
    relink_parser.add_argument("--root", default=argparse.SUPPRESS, help="Vault directory")
    relink_parser.add_argument("source", help="Curated Markdown source relative to the vault root")
    cluster_parser = commands.add_parser("cluster", help="Print a read-only co-occurrence cluster report")
    cluster_parser.add_argument("--root", default=argparse.SUPPRESS, help="Vault directory")
    cluster_parser.add_argument("--min-sources", type=int, default=5, help="Minimum pair co-citations (default: 5)")
    cluster_parser.add_argument("--coverage", type=float, default=0.6, help="Theme coverage fraction (default: 0.6)")
    cluster_parser.add_argument("--date", dest="date_str", help="Report date in YYYY-MM-DD form")
    args = parser.parse_args(argv)
    try:
        config = load_config(args.root)
        if args.command == "cluster":
            from glassgraph.core.cluster import preview
            print(preview(config, min_sources=args.min_sources, coverage=args.coverage,
                          date_str=args.date_str), end="")
            return 0
        if args.command == "relink":
            from glassgraph.extraction import relink
            preview = relink(config, args.source)
            if hasattr(sys.stdout, "reconfigure"):
                sys.stdout.reconfigure(newline="")
            sys.stdout.write(preview)
            return 0
        if args.command == "lookup":
            from glassgraph.core.lookup import lookup
            status, report = lookup(config, args.name)
            print(report, end="")
            return status
        if args.command == "suggest":
            from glassgraph.extraction import suggest
            print(suggest(config, args.source, top_n=args.top), end="")
            return 0
        if args.command == "explain":
            from glassgraph.extraction import explain
            print(explain(config, args.source, filter_canonical=args.filter_canonical,
                          show_suppressed=args.suppressed, context_chars=args.context), end="")
            return 0
        if args.command == "extract":
            from glassgraph.extraction import extract
            print(json.dumps(extract(config, args.source, dry_run=args.dry_run), indent=2, ensure_ascii=False))
            return 0
        if not config.wiki.is_dir():
            raise ConfigError("Select an existing configured wiki directory")
        findings = lint.run_lint(config.wiki, config=config)
        visible = [f for f in findings if f.severity == args.severity] if args.severity else findings
        print(lint.format_report(visible))
        return lint.exit_code_from_findings(findings)
    except (ConfigError, OSError, UnicodeError) as error:
        print(f"glassgraph: {error}", file=sys.stderr)
        return 2
