# 6. Stage 2 — BGE-M3 dense retrieval

*Part 6 of 8 in the glassgraph journey.*

## The cold-start problem

Stage 1 — dictionary-based Aho-Corasick — works beautifully on entities the wiki already knows about. It fails completely on entities the wiki doesn't.

A concrete example. The 2026 Nvidia GTC announcement included references to "DG Matrix," a solid-state-transformer startup I hadn't heard of before. The raw clipping mentions DG Matrix four times. My Stage 1 extractor returned zero hits for it. The entity wasn't in my alias dictionary — and how could it be, before I'd ingested the source that introduced it?

This is the **cold-start failure mode** of dictionary approaches. The dictionary can only catch what's already curated. New material can introduce new entities, and a pure-dictionary system has nothing to say about them.

I needed a complementary mechanism for *retrieval by semantic similarity*: given a chunk of source text, surface candidate entity pages from the wiki that are semantically related, even if no alias matches verbatim.

## Why BGE-M3 specifically

The choices for semantic retrieval, as of 2025-2026:

| Model | Pros | Cons |
|---|---|---|
| OpenAI `text-embedding-3-*` | High quality, well-supported | Cloud API, not deterministic across calls, has a $ cost, ITAR / data-residency concerns |
| Cohere `embed-multilingual-v3` | Multilingual, high quality | Cloud API, same issues as OpenAI |
| `sentence-transformers/all-mpnet-base-v2` | Local, fast | English-only — useless for the CN teardown corpus |
| **`BAAI/bge-m3`** | Multilingual including CN, runs locally, sentence-transformers compatible, license OK | ~2GB model file, slower than smaller English-only models |
| `intfloat/multilingual-e5-large` | Multilingual, well-benchmarked | Similar size, similar speed; BGE-M3 just edged it on my domain |

BGE-M3 won for one reason that mattered more than benchmarks: **runs locally on CPU**, which means no API calls, no cost, no rate limits, and — critically — **determinism**.

Determinism in a sentence-transformer pipeline is not free. You have to:

1. Pin the random seed (`torch.manual_seed(0)`)
2. Disable cuDNN nondeterminism (`torch.backends.cudnn.deterministic = True`)
3. Set CUBLAS workspace config to a deterministic value (`CUBLAS_WORKSPACE_CONFIG=:16:8`)
4. Force `model.eval()` mode
5. Force CPU-only inference (GPU adds another layer of nondeterminism even with the flags above)

With all five, two consecutive runs produce byte-identical `.npy` embedding files. I verified this. SHA256-checked.

## What the embeddings represent

The unit being embedded: **the full body of each entity page** (companies, technologies, products, themes — about 1400 pages total). One embedding vector per page. Pre-computed and cached on disk.

At query time, for a given raw clipping, embed its body the same way, and compute cosine similarity against all 1400 entity embeddings. Top-K results are the candidate entities — ranked by semantic similarity, not by literal string match.

The whole thing fits in ~10 MB of `.npy` files for 1400 pages × 1024-dim float32 embeddings. CPU inference is ~30 seconds for the full corpus first run; sub-second on rerun thanks to the embedding manifest below.

## The embedding manifest — pinning reproducibility

This was the second design decision that mattered: caching the embeddings tied to a SHA of the source content.

```python
# Pseudocode of the manifest
manifest = {
    "model_revision": "BAAI/bge-m3@<commit-sha>",
    "torch_seed": 0,
    "cublas_config": ":16:8",
    "entity_pages": {
        "Tesla": {"sha256": "abc...", "embedding_path": "Tesla.npy"},
        "BYD":   {"sha256": "def...", "embedding_path": "BYD.npy"},
        # ...
    }
}
```

The SHA of each page's content is recorded. On rerun:

- If a page's content hasn't changed (SHA matches), reuse the cached embedding — sub-millisecond per page.
- If a page's content has changed (SHA differs), re-embed just that page.
- If a page is new, embed it.
- If the model revision changes (e.g., BGE-M3 upstream tags a new version), rebuild everything.

This is what makes the pipeline practical to rerun. The first run pays the ~30-second cost; every subsequent run amortizes to milliseconds unless wiki content has materially changed.

## The singleton bug that ate an afternoon

There's a specific lesson here worth recording. The first version of Stage 2 loaded the BGE-M3 model lazily, on first call. The function looked something like:

```python
def get_model():
    return SentenceTransformer("BAAI/bge-m3")  # 2GB load, ~5s
```

Called once per extraction request. So if I ran `link.py extract` on 25 raw files in one batch, the model loaded 25 times. ~2 minutes of pure wasted I/O.

The fix is a module-level singleton:

```python
_MODEL_SINGLETON = None

def get_model():
    global _MODEL_SINGLETON
    if _MODEL_SINGLETON is None:
        _MODEL_SINGLETON = SentenceTransformer("BAAI/bge-m3")
        _set_deterministic_flags()
        _MODEL_SINGLETON.eval()
    return _MODEL_SINGLETON
```

Embarrassingly basic. The afternoon went to finding it because the bug looked like "Stage 2 is mysteriously slow on batches" — not "load is repeating." Reading the load logs (not the extraction logs) is what surfaced it.

The lesson I'd take to anyone doing similar work: **log model loads explicitly**. They're easy to lose in stdout noise but they dominate latency.

## How Stage 2 plugs into the workflow

In practice, Stage 2 is **opt-in** via a `--vector` flag:

```bash
python link.py extract raw/X.md --vector --top-k 20 --threshold 0.7
```

The cache JSON adds a `vector_entities` field alongside the Stage 1 `entities` field:

```json
{
  "source": "raw/X.md",
  "entities": [
    {"canonical": "Tesla", "aliases_matched": ["Tesla"], "count": 4, "confidence": "dict"},
    {"canonical": "SiC-MOSFET", "aliases_matched": ["SiC FETs"], "count": 3, "confidence": "dict"}
  ],
  "vector_entities": [
    {"canonical": "Tesla-Model-3-inverter", "cosine": 0.751, "rank": 1, "confidence": "vector"},
    {"canonical": "SiC-MOSFET", "cosine": 0.750, "rank": 2, "confidence": "vector"},
    {"canonical": "Tesla", "cosine": 0.720, "rank": 3, "confidence": "vector"}
  ]
}
```

The Stage 1 hits are the high-precision ground truth. The Stage 2 hits are the candidate set for *new aliases I might want to add* or *new entity pages I might want to create*.

The intended workflow is **Stage 2 informs the alias-curation feedback loop, not the immediate `touches:` field**:

1. Run Stage 1 + Stage 2 on a raw clipping.
2. Compare the two lists. If Stage 2 surfaces canonicals NOT in Stage 1 with cosine > 0.75, those are likely missing aliases or missing pages.
3. Decide: add the alias to an existing page, or create a new page.
4. Next Stage 1 run picks up the addition automatically.

This is the *promotion path* mentioned at the end of Part 7 — Stage 2 discovers, Stage 1 absorbs.

## What Stage 2 still can't do

Stage 2 isn't a panacea. It has its own failure modes:

- **Cold-start within a topic.** If a new entity has zero overlap with the curated wiki (e.g., a paper introduces a totally new concept like "vertical power delivery" that no existing page touches), Stage 2 returns low-cosine matches that aren't useful.
- **Topic creep within an entity page.** If `Tesla.md` accumulates content about charging stations, inverters, motors, and Cybertruck, its embedding becomes a vague average. The semantic-retrieval signal degrades.
- **Granularity mismatch.** Stage 2 retrieves the *page level*. A raw clipping that mentions a specific Tesla product mostly retrieves the generic `Tesla.md` page, not the specific product page. To fix this you'd need section-level embeddings, which is a much larger engineering investment.

By the time Stage 2 was working, I had a tool that combined deterministic dictionary lookup with semantic retrieval, both running locally, both byte-reproducible, both inspectable.

The natural next question: **how does this compare to a state-of-the-art LLM-based knowledge-graph extractor?**

That's Part 7.

---

← Previous: [Part 5 — Stage 1 — Aho-Corasick entity linking](05-stage1-aho-corasick.md)
→ Next: [Part 7 — The graphify comparison](07-graphify-comparison.md)
