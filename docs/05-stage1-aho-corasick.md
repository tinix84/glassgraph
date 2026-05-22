# 5. Stage 1 — Aho-Corasick entity linking

*Part 5 of 8 in the glassgraph journey.*

## The missing-extractions problem

By month five I had a clear pattern in the wiki: source pages were getting structurally clean (good `touches:` lists, well-cited bodies) but the `touches:` lists were *incomplete*. A clipping might mention `BYD` 17 times in its body and the LLM-curated `touches:` field would list `[[BYD-Han]], [[Tesla]], [[CATL]]` — entirely missing `[[BYD]]` itself.

The lint couldn't catch this. The source page looked fine. The entity page (`BYD.md`) just didn't get the citation it deserved.

The cause was structural: the LLM, in its summarization pass, was deciding what to keep and what to drop based on what it judged as "important." A teardown that primarily reviews a Tesla Model 3 inverter but mentions BYD as a competitor 17 times might legitimately drop `[[BYD]]` from `touches:` because BYD isn't *the subject*. But that decision is wrong for my use case — I want every cross-mention in `touches:` so the graph compounds.

I needed a deterministic extractor that would scan the body of every raw clipping and emit *every* mention of *every* entity I'd already curated, regardless of importance ranking.

## Why a dictionary, not an LLM, for this job

The candidates:

1. **LLM entity extraction** (e.g., prompt Claude to "list every entity mentioned in this body"). I'd already seen this fail upstream — it's the same model making the same importance-based pruning decisions.
2. **Named-entity-recognition models** (e.g., spaCy NER, BERT-NER). Trained on Wikipedia / news English. Bad at Chinese teardown vocabulary. Bad at part numbers. Bad at my domain.
3. **Dictionary lookup over my curated alias list.** Every entity page already has an `aliases:` field. The wiki literally defines its own vocabulary. Use it.

(3) was the obviously right choice. The constraint: it had to handle CJK boundaries correctly, because Chinese text has no spaces — so the word-boundary heuristics that work for English fail completely.

## Aho-Corasick

[Aho-Corasick](https://en.wikipedia.org/wiki/Aho%E2%80%93Corasick_algorithm) is a multi-pattern string-matching algorithm: given a dictionary of N patterns and a text body of length M, find all occurrences of all patterns in O(M + sum-of-pattern-lengths + number-of-hits) time. Linear in the body, regardless of dictionary size.

In Python, [`pyahocorasick`](https://pyahocorasick.readthedocs.io/) is the bindings package. Build an Automaton, add all aliases, scan the body — done.

The naïve version is ~30 lines:

```python
import ahocorasick

automaton = ahocorasick.Automaton()
for canonical, aliases in alias_dict.items():
    for alias in aliases:
        automaton.add_word(alias, (canonical, alias))
automaton.make_automaton()

for end_idx, (canonical, alias) in automaton.iter(body):
    start_idx = end_idx - len(alias) + 1
    # We have a hit at body[start_idx : end_idx+1]
```

That works. It just matches anywhere, including inside other words. `Tesla` matches inside `Tesla-Coil`. `EV` matches inside `EVENT`. For English text we need word boundaries.

For Chinese text we *don't* — `特斯拉` in 中国市场的特斯拉Model3 is a legitimate hit even though there's no space before or after. The boundary rules have to depend on the script of the alias.

## The CJK boundary rule

The rule I converged on:

```python
_BOUNDARY_RE = re.compile(r"[\W_]", re.UNICODE)
_CJK_RE = re.compile(r"[一-鿿㐀-䶿豈-﫿]")

def _is_cjk(s: str) -> bool:
    return bool(_CJK_RE.search(s))

def is_word_boundary_ok(alias: str, before_char: str, after_char: str) -> bool:
    if _is_cjk(alias):
        # CJK aliases: no whitespace boundary needed
        return True
    # Non-CJK aliases: require word boundary on both sides
    is_before_boundary = (not before_char) or bool(_BOUNDARY_RE.match(before_char))
    is_after_boundary = (not after_char) or bool(_BOUNDARY_RE.match(after_char))
    return is_before_boundary and is_after_boundary
```

If the *alias* contains CJK, the hit is accepted regardless of surrounding characters. If the alias is pure ASCII/Latin, the hit requires a non-word character (or string boundary) on both sides.

This handles:

- `Tesla` in `Tesla Model 3 inverter` → hit (spaces are boundaries)
- `Tesla` in `Tesla-Coil` → still hit (hyphen is `[\W_]`), filtered by disambiguation pass below
- `EV` in `EVENT` → no hit (no boundary after)
- `特斯拉` in `中国市场的特斯拉Model3` → hit (CJK rule, no boundary check)
- `BYD` in `BYDX9000` → no hit (X is a word character)
- `BYD` in `BYD-X9000` → hit (hyphen is a boundary)

## Greedy dedup and disambiguation

Two more passes after the raw Aho-Corasick scan:

**Greedy dedup**: when overlapping hits exist (e.g., `Tesla` matches at position 100-104 *and* `Tesla Model 3` matches at position 100-112), keep the longer one. Implementation: sort hits by (start asc, length desc), sweep left-to-right with a cursor, keep hits whose start ≥ cursor.

**Disambiguation**: a YAML file with patterns to suppress. `Tesla coil` suppresses the bare `Tesla` match when the body contains the phrase. This is a tiny manually-curated list (~20 entries) but it kills the obvious false positives.

The result: every hit comes with `(start, end, canonical, alias_matched)`. Crucially, **every hit is auditable** — you know what text matched, what canonical it resolves to, and where in the body it occurred.

## The audit trail in practice

```
$ python link.py explain raw/拆解Tesla\ Model\ 3逆变器.md

[176:181]    'Tesla'                  → Tesla                  via 'Tesla'
[527:549]    'Tesla Model 3 inverter' → Tesla-Model-3-inverter via 'Tesla Model 3 inverter'
[2954:2962]  'SiC FETs'               → SiC-MOSFET             via 'SiC FETs'
[3610:3625]  'Silicon Carbide'        → SiC-MOSFET             via 'Silicon Carbide'
[4848:4850]  'TI'                     → Texas-Instruments      via 'TI'
[7400:7402]  'ST'                     → STMicroelectronics     via 'ST'
[6313:6321]  'Infineon'               → Infineon               via 'Infineon'
```

Every line tells you exactly which substring of the body matched and what canonical entity it resolved to. The alias `SiC FETs` and the alias `Silicon Carbide` both collapse to canonical `SiC-MOSFET` — the alias dictionary is the source of truth and the trace shows the resolution.

This audit trail is what made it impossible for me to go back to a black-box LLM extractor. Every claim I can defend.

## Backfill against the LLM-curated `touches:`

The other thing the deterministic extractor gave me: a way to *measure* how well the LLM had been doing.

I ran Stage 1 over every existing `wiki/sources/*.md`, comparing extraction against the LLM-curated `touches:`. The first run came out at **43.2% match rate** — meaning of all the entities the LLM had put in `touches:`, only 43% were also found by deterministic dictionary scan. The other 57% were either:

- Aliases that should have been added to entity pages but weren't (the curated alias dictionary was incomplete)
- LLM hallucinations / over-attribution (rare but real)
- Page renamings that left stale `touches:` entries (the rename workflow didn't update inbound references)

I spent a few sessions running `link.py suggest <source>` (which proposes alias candidates from raw bodies via TF/DF scoring) and triaging the results into the wiki. Over a few weeks, the match rate climbed:

- 43.2% → 47.0% (after adding ~80 missing CJK aliases)
- 47.0% → 49.7% (alias collision fixes via the new lint)
- 49.7% → 50.1% (YAML bug fixes from the wiki lint module)
- 50.1% → 50.3% (drift reconciliation — the 161 invisible terms incident)

The endpoint isn't 100% (and shouldn't be — see Part 7 for why a deterministic linker has structural blind spots). But the **direction** matters: every percentage-point gain is an audit-trail improvement, a more complete graph, a wiki that compounds better.

## What Stage 1 is and isn't

Stage 1 is great at:

- Catching every mention of every known entity in every clipping (high recall on curated vocabulary)
- Producing byte-identical reruns
- Running in ~1 second on the full 502-source corpus
- Being inspectable per-hit

Stage 1 is bad at:

- New entities. If a teardown mentions a vendor not in the wiki yet (`Innoscience`, `DG Matrix`), Stage 1 produces zero hits for it. The alias dictionary has to be expanded before Stage 1 can find it.
- Semantic equivalence beyond aliases. `Si MOSFET` and `silicon MOSFET` are both legitimate canonical names; Stage 1 only matches if both are explicit aliases.
- Concepts. Entities are nouns. Themes ("the SiC-to-GaN transition in EV chargers") are not nouns; Stage 1 has nothing to say about them.

Those gaps drove Stage 2.

---

← Previous: [Part 4 — When LLM curation fails — Python lint](04-python-lint.md)
→ Next: [Part 6 — Stage 2 — BGE-M3 dense retrieval](06-stage2-bge-m3.md)
