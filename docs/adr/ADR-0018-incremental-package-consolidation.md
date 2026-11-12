# ADR-0018: Consolidate shared validation before vault operations

- Date: 2026-11-12
- Author: Codex
- Version: 1.0
- Audience: Glassgraph maintainers

## Decision

We allow the v1 compiler work to proceed through one Glassgraph package before the full tooling migration in issue #4.

## Context

Issue #21 asks whether full consolidation must precede v1 compiler work.
The page writer and deterministic lint need the same metadata rules.
Moving all vault operations together would combine packaging, root discovery, state migration, hooks, and Zotero changes.
Markdown authority and the existing evidence contract remain requirements.

## Options

| Option | Pros | Cons | Cost / effort |
|---|---|---|---|
| Finish all consolidation first | Establishes every final interface together | Couples unrelated migration risks to the compiler | Full issue #4 migration |
| Consolidate validation first | Gives callers one metadata authority through a portable package | Legacy callers need temporary import adapters | Small, independently testable increment |
| Add a separate compiler package | Allows independent packaging | Creates competing package and validation ownership | Additional permanent integration work |

## Decision and rationale

Use `glassgraph.core.frontmatter` as the parser and structural-validation authority.
Use `glassgraph.wiki.schema` for writer policy and recommendations.
Keep the legacy `frontmatter.py` import as an adapter to the same implementation.
The adapter may locate package code in an uninstalled checkout; it must not discover a vault from code location.

This increment introduces no command entry point, vault discovery, or runtime-state migration.
Before exposing root-dependent package commands, implement issue #4's ordered root resolution and parity gates.
All package commands must share that resolver and the same CLI.
New compiler work must extend this package and preserve Markdown authority.

## Consequences

Validation can be installed and tested outside an embedded vault checkout.
The writer compatibility adapter must preserve existing errors, warnings, aliases, and relation checks.
Issue #4 remains the owner of full command, hook, maintenance, and Zotero migration.
Its acceptance criteria are not satisfied by this increment.
No vault files or private reports enter the package.

## Status

Proposed through the issue #21 pull request on 2026-11-12.
