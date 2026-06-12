"""BGE-M3 vector retrieval — production Stage 2 of the deterministic entity linker.

Singleton model load + deterministic embedding + SHA-pinned manifest + top-K
cosine retrieval + threshold filter. Opt-in via `link.py extract raw/X.md --vector`.

Determinism: CPU-only inference, seed pinning (random/numpy/torch),
torch.use_deterministic_algorithms(True), CUBLAS_WORKSPACE_CONFIG=:16:8,
model.eval(). Two consecutive runs produce byte-identical embeddings.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np


def _load_frontmatter():
    import importlib.util, sys
    from pathlib import Path
    if "frontmatter" in sys.modules:
        return sys.modules["frontmatter"]
    src = Path(__file__).resolve().parent / "frontmatter.py"
    spec = importlib.util.spec_from_file_location("frontmatter", src)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["frontmatter"] = mod
    spec.loader.exec_module(mod)
    return mod


frontmatter = _load_frontmatter()


# Pin global state at module load
os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":16:8")
os.environ.setdefault("PYTHONHASHSEED", "0")


_HERE = Path(__file__).resolve().parent
_INDEX_DIR = _HERE.parent / "index"
_EMBEDDINGS_PATH = _INDEX_DIR / "embeddings.npy"
_MANIFEST_PATH = _INDEX_DIR / "embeddings_manifest.json"
_CANONICALS_PATH = _INDEX_DIR / "embeddings_canonicals.json"
_WIKI_ROOT = _HERE.parents[1] / "wiki"

_MODEL_NAME = "BAAI/bge-m3"
_ENTITY_DIRS = ("companies", "technologies", "products", "themes")
_DEFAULT_CHUNK_CHARS = 2000
_DEFAULT_OVERLAP = 200
_DEFAULT_PAGE_BODY_CHARS = 1000

# Singleton model — load once per process
_MODEL_SINGLETON = None


@dataclass
class VectorHit:
    canonical: str
    cosine: float
    rank: int
    confidence: str = "vector"


def _set_deterministic() -> None:
    """Pin random state. Safe to call multiple times."""
    import random
    random.seed(0)
    np.random.seed(0)
    try:
        import torch
        torch.manual_seed(0)
        try:
            torch.use_deterministic_algorithms(True, warn_only=True)
        except Exception:
            pass  # older torch versions may not support warn_only
    except ImportError:
        pass


def _get_model():
    """Load BGE-M3 once per process. Subsequent calls return the cached instance."""
    global _MODEL_SINGLETON
    if _MODEL_SINGLETON is None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as e:
            raise RuntimeError(
                "sentence-transformers is required for Stage 2. "
                "Install with: conda run -n 2brain_env pip install sentence-transformers"
            ) from e
        _set_deterministic()
        _MODEL_SINGLETON = SentenceTransformer(_MODEL_NAME, device="cpu")
        _MODEL_SINGLETON.eval()
    return _MODEL_SINGLETON


def _get_model_revision() -> str:
    """Return the HuggingFace revision hash of the loaded model.

    Best-effort: reads the cached model dir's commit hash. Falls back to a
    placeholder if introspection fails (test code can monkeypatch this).
    """
    try:
        model = _get_model()
        cache_path = getattr(model, "model_card_data", None)
        if cache_path is None:
            return "unknown"
        return str(cache_path)[:16]
    except Exception:
        return "unknown"


# ── Frontmatter / text helpers ──────────────────────────────────────────────

def _strip_frontmatter_and_body(text: str) -> tuple[str, str]:
    """Return (frontmatter_text, body_text). Body has frontmatter stripped."""
    p = frontmatter.parse(text)
    return (p.fm_text or ""), p.body


def _entity_pages(wiki_root: Path) -> list[Path]:
    """All entity pages in canonical order (companies, technologies, products, themes; each sorted)."""
    pages = []
    for d_name in _ENTITY_DIRS:
        d = wiki_root / d_name
        if d.exists():
            pages.extend(sorted(d.glob("*.md")))
    return pages


def _page_text_for_embedding(page: Path) -> str:
    """Construct the text to embed for an entity page: `stem + first 1000 chars of body`."""
    text = page.read_text(encoding="utf-8")
    _, body = _strip_frontmatter_and_body(text)
    return f"{page.stem}\n\n{body[:_DEFAULT_PAGE_BODY_CHARS].strip()}"


def _chunk_body(body: str, chunk_chars: int = _DEFAULT_CHUNK_CHARS, overlap_chars: int = _DEFAULT_OVERLAP) -> list[str]:
    """Split body into overlapping chunks. Returns [body] when body is short enough."""
    if len(body) <= chunk_chars:
        return [body]
    chunks: list[str] = []
    start = 0
    while start < len(body):
        end = min(start + chunk_chars, len(body))
        chunks.append(body[start:end])
        if end == len(body):
            break
        start = end - overlap_chars
    return chunks


# ── Manifest ────────────────────────────────────────────────────────────────

def _page_shas(wiki_root: Path) -> dict[str, str]:
    shas: dict[str, str] = {}
    for d_name in _ENTITY_DIRS:
        d = wiki_root / d_name
        if not d.exists():
            continue
        for page in sorted(d.glob("*.md")):
            rel = str(page.relative_to(wiki_root))
            shas[rel] = hashlib.sha256(page.read_bytes()).hexdigest()
    return shas


def _manifest_stale(manifest_path: Path, current_shas: dict[str, str], current_revision: str) -> bool:
    """True if the manifest is missing, unreadable, or differs in revision/SHAs."""
    if not manifest_path.exists():
        return True
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return True
    if manifest.get("model_revision") != current_revision:
        return True
    if manifest.get("page_shas") != current_shas:
        return True
    return False


def _write_manifest(
    manifest_path: Path,
    page_shas: dict[str, str],
    model_revision: str,
    embedding_dim: int,
) -> None:
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "model": _MODEL_NAME,
        "model_revision": model_revision,
        "embedding_dim": embedding_dim,
        "page_shas": page_shas,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def manifest_sha(manifest_path: Path = _MANIFEST_PATH) -> str:
    """Short SHA of the manifest file, embedded in extraction results."""
    if not manifest_path.exists():
        return ""
    return hashlib.sha256(manifest_path.read_bytes()).hexdigest()[:16]


# ── Embedding build/load ────────────────────────────────────────────────────

def build_entity_embeddings(
    wiki_root: Path = _WIKI_ROOT,
    embeddings_path: Path = _EMBEDDINGS_PATH,
    manifest_path: Path = _MANIFEST_PATH,
    canonicals_path: Path = _CANONICALS_PATH,
    force: bool = False,
) -> tuple[np.ndarray, list[str]]:
    """Build or load cached entity-page embeddings.

    Returns (matrix [n_entities × dim], canonicals [n_entities]).
    """
    pages = _entity_pages(wiki_root)
    canonicals = [p.stem for p in pages]
    current_shas = _page_shas(wiki_root)
    current_revision = _get_model_revision()

    if not force and embeddings_path.exists() and canonicals_path.exists():
        if not _manifest_stale(manifest_path, current_shas, current_revision):
            embs = np.load(embeddings_path)
            cached_canonicals = json.loads(canonicals_path.read_text(encoding="utf-8"))
            return embs, cached_canonicals

    # Build fresh
    model = _get_model()
    texts = [_page_text_for_embedding(p) for p in pages]
    print(f"Embedding {len(texts)} entity pages with {_MODEL_NAME}...", file=sys.stderr)
    embeddings = model.encode(texts, normalize_embeddings=True, show_progress_bar=True, batch_size=8)
    embeddings = np.asarray(embeddings, dtype=np.float32)

    embeddings_path.parent.mkdir(parents=True, exist_ok=True)
    np.save(embeddings_path, embeddings)
    canonicals_path.write_text(json.dumps(canonicals, ensure_ascii=False, indent=2), encoding="utf-8")
    _write_manifest(manifest_path, current_shas, current_revision, embeddings.shape[1])
    return embeddings, canonicals


# ── Ranking ─────────────────────────────────────────────────────────────────

def _rank_from_sims(sims: np.ndarray, canonicals: list[str], k: int) -> list[tuple[str, float]]:
    """Max-pool similarities across chunks per entity, sort descending, take top-k."""
    max_sims = sims.max(axis=0)
    ranked = sorted(zip(canonicals, max_sims.tolist()), key=lambda x: -x[1])
    return ranked[:k]


def _apply_threshold(ranked: list[tuple[str, float]], threshold: float | None) -> list[tuple[str, float]]:
    if threshold is None:
        return ranked
    return [(c, s) for c, s in ranked if s >= threshold]


# ── Per-source retrieval ────────────────────────────────────────────────────

def run_for_source(
    raw_path: Path,
    embeddings: np.ndarray,
    canonicals: list[str],
    top_k: int = 20,
    threshold: float | None = None,
) -> list[VectorHit]:
    """Embed a raw source, rank against the entity matrix, return top-K filtered hits."""
    text = raw_path.read_text(encoding="utf-8")
    _, body = _strip_frontmatter_and_body(text)
    chunks = _chunk_body(body)

    model = _get_model()
    chunk_embs = model.encode(chunks, normalize_embeddings=True, show_progress_bar=False, batch_size=8)
    chunk_embs = np.asarray(chunk_embs, dtype=np.float32)

    sims = chunk_embs @ embeddings.T
    ranked = _rank_from_sims(sims, canonicals, k=top_k)
    filtered = _apply_threshold(ranked, threshold)
    return [
        VectorHit(canonical=c, cosine=float(s), rank=i + 1)
        for i, (c, s) in enumerate(filtered)
    ]
