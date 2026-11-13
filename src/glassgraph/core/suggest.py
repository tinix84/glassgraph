"""TF-IDF-style alias candidate proposal.

Scans a raw body for CJK noun-like phrases and English title-case n-grams,
scores each by TF / (DF + 1) using a per-source-corpus DF index, filters out
tokens already in the alias trie, and emits the top-N candidates as a ranked
list for manual triage.
"""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from glassgraph.config import VaultConfig

# CJK noun candidate: 2-5 CJK chars
_CJK_RE = re.compile(r"[一-鿿]{2,5}")
# Single title-case word (capitalized or all-caps)
_EN_WORD_RE = re.compile(r"[A-Z][a-zA-Z]+|[A-Z]{2,}")

# Conservative stopword set — common verbs / pronouns / fillers
_STOPWORDS = {
    "The", "This", "That", "These", "Those", "There", "Their", "They",
    "And", "Or", "But", "For", "With", "From", "Into", "Onto",
    "Is", "Are", "Was", "Were", "Be", "Been", "Being",
    "I", "You", "It", "We", "Us", "He", "She",
    "Mr", "Mrs", "Ms", "Dr",
    # Common in our corpus
    "Figure", "Table", "Section", "Chapter", "PDF",
}


def extract_candidates(body: str) -> list[str]:
    """Extract candidate tokens from body: CJK 2-5 char phrases + EN title-case n-grams (1-3 words).

    Uses a sliding window over consecutive title-case tokens so both single
    words and multi-word compound names are scored independently.
    """
    out: list[str] = []
    out.extend(_CJK_RE.findall(body))

    # Find all title-case word positions so we can build 1-, 2-, 3-grams
    # from consecutive words (same region = separated by only spaces, no
    # intervening lowercase words).
    words = [(m.group(), m.start()) for m in _EN_WORD_RE.finditer(body)]

    i = 0
    while i < len(words):
        # Extend run of consecutive title-case words (adjacent with only spaces)
        run = [words[i][0]]
        pos = words[i][1] + len(words[i][0])
        j = i + 1
        while j < len(words):
            gap = body[pos:words[j][1]]
            if gap == " ":
                run.append(words[j][0])
                pos = words[j][1] + len(words[j][0])
                j += 1
            else:
                break
        # Emit 1-, 2-, 3-grams from this run
        for start in range(len(run)):
            for length in range(1, min(4, len(run) - start + 1)):
                out.append(" ".join(run[start:start + length]))
        i = j if j > i else i + 1

    return out


def compute_df_index(sources_dir: Path, *, config: VaultConfig | None = None) -> dict[str, int]:
    """Document-frequency index: token → number of source pages containing it.

    O(N_sources * candidates_per_source). Only the legacy cache caller persists this result.
    """
    df: Counter = Counter()
    if config is None and not sources_dir.exists():
        return {}
    pages = config.markdown_files(sources_dir) if config else sorted(sources_dir.glob("*.md"))
    for src in pages:
        text = src.read_text(encoding="utf-8")
        tokens = set(extract_candidates(text))
        for t in tokens:
            df[t] += 1
    return dict(df)


def rank_candidates(
    body: str,
    known_aliases: set[str],
    df: dict[str, int],
    top_n: int = 20,
) -> list[dict]:
    """Return top-N ranked candidates by tf / (df + 1)."""
    candidates = extract_candidates(body)
    tf = Counter(candidates)

    ranked: list[dict] = []
    for token, count in tf.items():
        if token in known_aliases:
            continue
        if token in _STOPWORDS:
            continue
        d = df.get(token, 0)
        score = count / (d + 1)
        ranked.append({
            "token": token,
            "tf": count,
            "df": d,
            "score": score,
        })

    ranked.sort(key=lambda x: -x["score"])
    return ranked[:top_n]


def _source_shas(sources_dir: Path) -> dict[str, str]:
    """SHA256 of every source file, keyed by relative filename."""
    if not sources_dir.exists():
        return {}
    out = {}
    for src in sorted(sources_dir.glob("*.md")):
        out[src.name] = hashlib.sha256(src.read_bytes()).hexdigest()
    return out


def load_or_build_df(
    sources_dir: Path,
    cache_path: Path,
    force: bool = False,
) -> dict[str, int]:
    """Load DF cache from JSON; rebuild if missing, forced, or source SHAs changed.

    Cache schema:
        {"sources_sha": {filename: sha256, ...}, "df": {token: count, ...}}

    Old plain-DF caches (no wrapper) are treated as stale and rebuilt.
    """
    current_shas = _source_shas(sources_dir)

    if cache_path.exists() and not force:
        try:
            cached = json.loads(cache_path.read_text(encoding="utf-8"))
            if (
                isinstance(cached, dict)
                and "sources_sha" in cached
                and "df" in cached
                and cached["sources_sha"] == current_shas
            ):
                return cached["df"]
        except (json.JSONDecodeError, OSError):
            pass

    df = compute_df_index(sources_dir)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {"sources_sha": current_shas, "df": df},
            ensure_ascii=False, indent=2,
        ),
        encoding="utf-8",
    )
    return df


def format_report(ranked: list[dict]) -> str:
    if not ranked:
        return "No candidates found.\n"
    lines = ["=== Alias candidates ===", ""]
    for c in ranked:
        lines.append(f"  tf={c['tf']:<3}  df={c['df']:<3}  score={c['score']:.2f}  {c['token']!r}")
    return "\n".join(lines) + "\n"
