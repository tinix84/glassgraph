"""Proof-of-concept Stage 2 vector retrieval using BGE-M3.

NOT FOR PRODUCTION USE. This module validates the Stage 2 design from
2026-05-19 spec by:
1. Pre-computing entity-page embeddings (cached in .tools/index/embeddings_poc.npy)
2. For a given raw source, computing top-K entity matches via cosine similarity
3. Comparing against Stage 1 results to surface candidates Stage 1 missed

Determinism: model.eval(), torch.manual_seed(0), cudnn.deterministic, no GPU.
"""
from __future__ import annotations

import json
import hashlib
import os
import sys
from pathlib import Path
from typing import Iterator

import numpy as np


_HERE = Path(__file__).resolve().parent
_INDEX_DIR = _HERE.parent / "index"
_EMBEDDINGS_PATH = _INDEX_DIR / "embeddings_poc.npy"
_MANIFEST_PATH = _INDEX_DIR / "embeddings_poc_manifest.json"
_CANONICALS_PATH = _INDEX_DIR / "embeddings_poc_canonicals.json"
_MODEL_NAME = "BAAI/bge-m3"
_ENTITY_DIRS = ("companies", "technologies", "products", "themes")
_CHUNK_SIZE = 512  # token approximation via chars; bge-m3 handles 8k anyway


def _set_deterministic() -> None:
    """Pin random state for reproducibility per the spec."""
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":16:8")
    os.environ.setdefault("PYTHONHASHSEED", "0")
    import random
    random.seed(0)
    np.random.seed(0)
    try:
        import torch
        torch.manual_seed(0)
        torch.use_deterministic_algorithms(True, warn_only=True)
        if hasattr(torch.backends, "cudnn"):
            torch.backends.cudnn.deterministic = True
            torch.backends.cudnn.benchmark = False
    except Exception:
        pass


def _entity_pages(wiki_root: Path) -> list[Path]:
    pages = []
    for d in _ENTITY_DIRS:
        p = wiki_root / d
        if p.exists():
            pages.extend(sorted(p.glob("*.md")))
    return pages


def _strip_frontmatter_and_body(text: str) -> tuple[str, str]:
    """Return (frontmatter_text, body_text). Body has frontmatter stripped."""
    if not text.startswith("---"):
        return "", text
    end = text.find("\n---", 3)
    if end == -1:
        return "", text
    return text[3:end], text[end + 4:]


def _page_text_for_embedding(page: Path) -> str:
    """Construct the text to embed for an entity page.

    Use the canonical stem + first 1000 chars of body. This captures the
    entity name + its definition without bloating the embedding input.
    """
    text = page.read_text(encoding="utf-8")
    _, body = _strip_frontmatter_and_body(text)
    return f"{page.stem}\n\n{body[:1000].strip()}"


def _load_model():
    """Load bge-m3 in CPU/eval mode for determinism."""
    from sentence_transformers import SentenceTransformer
    model = SentenceTransformer(_MODEL_NAME, device="cpu")
    model.eval()
    return model


def build_entity_embeddings(wiki_root: Path, force: bool = False) -> tuple[np.ndarray, list[str]]:
    """Compute (or load cached) entity-page embeddings.

    Returns (embeddings_matrix, canonicals_list) where row i of the matrix
    corresponds to canonicals_list[i].
    """
    pages = _entity_pages(wiki_root)
    canonicals = [p.stem for p in pages]

    # Check cache
    current_shas = {}
    for p in pages:
        current_shas[p.stem] = hashlib.sha256(p.read_bytes()).hexdigest()

    cache_valid = False
    if not force and _EMBEDDINGS_PATH.exists() and _MANIFEST_PATH.exists():
        try:
            manifest = json.loads(_MANIFEST_PATH.read_text(encoding="utf-8"))
            if manifest.get("page_shas") == current_shas:
                cache_valid = True
        except Exception:
            cache_valid = False

    if cache_valid:
        embeddings = np.load(_EMBEDDINGS_PATH)
        canonicals_cached = json.loads(_CANONICALS_PATH.read_text(encoding="utf-8"))
        return embeddings, canonicals_cached

    # Fresh build
    _set_deterministic()
    model = _load_model()

    texts = [_page_text_for_embedding(p) for p in pages]
    print(f"Embedding {len(texts)} entity pages with {_MODEL_NAME}...", file=sys.stderr)
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=True, batch_size=8)
    embeddings = np.asarray(embeddings, dtype=np.float32)

    # Persist
    _INDEX_DIR.mkdir(parents=True, exist_ok=True)
    np.save(_EMBEDDINGS_PATH, embeddings)
    _CANONICALS_PATH.write_text(json.dumps(canonicals, ensure_ascii=False, indent=2), encoding="utf-8")
    _MANIFEST_PATH.write_text(
        json.dumps({"model": _MODEL_NAME, "page_shas": current_shas, "rows": len(canonicals)}, indent=2),
        encoding="utf-8",
    )
    return embeddings, canonicals


def _chunk_body(body: str, chunk_chars: int = 2000, overlap_chars: int = 200) -> list[str]:
    """Split body into overlapping chunks. Chars approximate tokens for bge-m3."""
    if len(body) <= chunk_chars:
        return [body]
    chunks = []
    start = 0
    while start < len(body):
        end = min(start + chunk_chars, len(body))
        chunks.append(body[start:end])
        if end == len(body):
            break
        start = end - overlap_chars
    return chunks


def top_k_for_source(
    raw_path: Path,
    embeddings: np.ndarray,
    canonicals: list[str],
    k: int = 20,
) -> list[tuple[str, float]]:
    """For one raw source, return top-K (canonical, similarity) pairs.

    Strategy: embed each chunk of the body, take max similarity per entity
    across chunks. Sort descending.
    """
    _set_deterministic()
    model = _load_model()

    text = raw_path.read_text(encoding="utf-8")
    _, body = _strip_frontmatter_and_body(text)
    chunks = _chunk_body(body)

    chunk_embs = model.encode(chunks, normalize_embeddings=True, batch_size=8)
    chunk_embs = np.asarray(chunk_embs, dtype=np.float32)

    # Similarity per entity = max over chunks
    sims = chunk_embs @ embeddings.T  # shape (n_chunks, n_entities)
    max_sims = sims.max(axis=0)        # shape (n_entities,)

    ranked = sorted(zip(canonicals, max_sims.tolist()), key=lambda x: -x[1])
    return ranked[:k]
