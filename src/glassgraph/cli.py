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
    args = parser.parse_args(argv)
    try:
        config = load_config(args.root)
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
