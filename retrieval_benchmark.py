"""Evidence-level retrieval benchmark metrics."""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import unicodedata
from pathlib import Path, PurePosixPath

import frontmatter


ATX_HEADING = re.compile(r"^[ ]{0,3}(#{1,6})(?:[ \t]+(.*)|[ \t]*)$")
FENCE_OPEN = re.compile(r"^[ ]{0,3}(`{3,}|~{3,}).*$")
HTML_BLOCK_TAG = re.compile(
    r"^[ ]{0,3}</?(?:address|article|aside|base|basefont|blockquote|body|caption|"
    r"center|col|colgroup|dd|details|dialog|dir|div|dl|dt|fieldset|figcaption|"
    r"figure|footer|form|frame|frameset|h[1-6]|head|header|hr|html|iframe|legend|"
    r"li|link|main|menu|menuitem|nav|noframes|ol|optgroup|option|p|param|search|"
    r"section|summary|table|tbody|td|tfoot|th|thead|title|tr|track|ul)"
    r"(?:[ \t]+|/?>|$)",
    re.IGNORECASE,
)
HTML_ATTRIBUTE = (
    r"[ \t]+[A-Za-z_:][A-Za-z0-9_.:-]*"
    r"(?:[ \t]*=[ \t]*(?:\"[^\"]*\"|'[^']*'|[^\s\"'=<>`]+))?"
)
HTML_COMPLETE_TAG = re.compile(
    rf"^[ ]{{0,3}}(?:"
    rf"<[A-Za-z][A-Za-z0-9-]*(?:{HTML_ATTRIBUTE})*[ \t]*/?>"
    rf"|</[A-Za-z][A-Za-z0-9-]*[ \t]*>"
    rf")[ \t]*$"
)


def _html_block_start(
    line: str,
    *,
    allow_type_7: bool,
) -> tuple[bool, re.Pattern[str] | str | None]:
    stripped = line.lstrip(" ")
    if len(line) - len(stripped) > 3:
        return False, None
    special = (
        ("<!--", re.compile(r"-->")),
        ("<?", re.compile(r"\?>")),
        ("<![CDATA[", re.compile(r"\]\]>")),
    )
    for prefix, terminator in special:
        if stripped.startswith(prefix):
            next_state = (
                None if terminator.search(stripped[len(prefix) :]) else terminator
            )
            return True, next_state
    declaration = re.match(r"<![A-Z]", stripped)
    if declaration:
        terminator = re.compile(r">")
        return True, None if terminator.search(stripped[declaration.end() :]) else terminator
    raw_tag = re.match(
        r"<(script|pre|style|textarea)(?:[ \t]+|>|$)",
        stripped,
        re.IGNORECASE,
    )
    if raw_tag:
        terminator = re.compile(rf"</{raw_tag.group(1)}[ \t]*>", re.IGNORECASE)
        return True, None if terminator.search(stripped[raw_tag.end() :]) else terminator
    if HTML_BLOCK_TAG.match(line) or (
        allow_type_7 and HTML_COMPLETE_TAG.match(line)
    ):
        return True, "blank"
    return False, None


def _canonical_hash(domain: str, payload) -> str:
    canonical = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    normalized = unicodedata.normalize("NFC", canonical)
    digest = hashlib.sha256(f"{domain}\0{normalized}".encode()).hexdigest()
    return f"sha256:{digest}"


def query_set_hash(records: list[dict]) -> str:
    """Return the frozen hash of benchmark query text and query metadata."""
    fields = ("id", "query", "type", "split", "kind", "owner_authored")
    payload = [
        {key: record[key] for key in fields if key in record}
        for record in sorted(records, key=lambda item: item["id"])
    ]
    return _canonical_hash("glassgraph:benchmark-queries:v1", payload)


def judgment_set_hash(records: list[dict]) -> str:
    """Return the frozen hash of evidence judgments and adjudication metadata."""
    fields = (
        "id",
        "required_groups",
        "irrelevant",
        "adjudication_note",
        "owner_adjudicated",
        "adjudicated_by",
        "adjudicated_date",
    )
    payload = [
        {key: record[key] for key in fields if key in record}
        for record in sorted(records, key=lambda item: item["id"])
    ]
    return _canonical_hash("glassgraph:benchmark-judgments:v1", payload)


def benchmark_version(
    privacy: str,
    records: list[dict],
    corpus_snapshot_hash: str,
) -> str:
    """Return a content-addressed version for one frozen benchmark identity."""
    if privacy not in {"public", "private"}:
        raise ValueError("Benchmark privacy must be public or private")
    digest = _canonical_hash(
        "glassgraph:benchmark-version:v1",
        {
            "corpus_snapshot_hash": corpus_snapshot_hash,
            "query_set_hash": query_set_hash(records),
            "judgment_set_hash": judgment_set_hash(records),
        },
    ).removeprefix("sha256:")
    return f"{privacy}-v1-{digest[:12]}"


def backend_settings_lock(settings: dict) -> str:
    """Return the frozen identity of one backend evaluation configuration."""
    return _canonical_hash("glassgraph:benchmark-backend-settings:v1", settings)


def corpus_snapshot_hash(corpus_root: str | Path) -> str:
    """Return the frozen hash of all Markdown bytes below one corpus root."""
    root = Path(corpus_root)
    documents = [
        {
            "path": canonical_path,
            "sha256": "sha256:"
            + hashlib.sha256(
                unicodedata.normalize(
                    "NFC",
                    path.read_bytes()
                    .decode("utf-8")
                    .replace("\r\n", "\n")
                    .replace("\r", "\n"),
                ).encode()
            ).hexdigest(),
        }
        for canonical_path, path in _corpus_markdown_paths(root)
    ]
    return _canonical_hash("glassgraph:benchmark-corpus:v1", documents)


def _canonical_document_path(value: str) -> str:
    normalized = unicodedata.normalize("NFC", str(value).replace("\\", "/"))
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise ValueError("Evidence judgment path is outside the corpus")
    parts = [part for part in path.parts if part not in {"", "."}]
    if not parts:
        raise ValueError("Evidence judgment path is empty")
    canonical = "/".join(parts)
    if re.match(r"^[A-Za-z]:", canonical):
        raise ValueError("Evidence judgment path is outside the corpus")
    return canonical


def _corpus_markdown_paths(corpus_root: str | Path) -> list[tuple[str, Path]]:
    root = Path(corpus_root).resolve()
    documents = {}
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix != ".md":
            continue
        resolved = path.resolve()
        try:
            relative = resolved.relative_to(root).as_posix()
        except ValueError as error:
            raise ValueError("The Markdown corpus contains an unsafe path") from error
        canonical = _canonical_document_path(relative)
        if canonical in documents and documents[canonical] != resolved:
            raise ValueError("The Markdown corpus contains a canonical path collision")
        documents[canonical] = resolved
    return sorted(documents.items())


def _lf_lines(text: str):
    """Yield lines split only at the normalized Markdown LF delimiter."""
    start = 0
    while start < len(text):
        end = text.find("\n", start)
        if end < 0:
            yield text[start:]
            return
        yield text[start : end + 1]
        start = end + 1


def _heading_instances(text: str, document_id: str) -> list[dict]:
    root = {
        "id": _canonical_hash(
            "glassgraph:heading:v1",
            {
                "document_id": document_id,
                "level": 0,
                "parent_id": None,
                "same_name_ordinal": 0,
                "title": "",
            },
        ),
        "level": 0,
        "title": "",
        "start": -1,
        "line": 1,
        "path": [],
    }
    headings = [root]
    stack = []
    sibling_counts = {}
    offset = 0
    parsed_page = frontmatter.parse(text)
    frontmatter_end = (
        len(text) - len(parsed_page.body)
        if parsed_page.fm_text is not None
        else 0
    )
    fence = None
    html_block = None
    paragraph_open = False
    for line_number, line in enumerate(_lf_lines(text), start=1):
        source_line = line.rstrip("\n")
        if offset < frontmatter_end:
            paragraph_open = False
            offset += len(line)
            continue
        if line_number == 1:
            source_line = source_line.removeprefix("\ufeff")
        if fence is not None:
            if re.match(rf"^[ ]{{0,3}}{re.escape(fence[0])}{{{fence[1]},}}[ \t]*$", source_line):
                fence = None
            paragraph_open = False
            offset += len(line)
            continue
        if html_block is not None:
            if html_block == "blank":
                if not source_line.strip(" \t"):
                    html_block = None
            elif html_block.search(source_line):
                html_block = None
            paragraph_open = False
            offset += len(line)
            continue
        if not source_line.strip(" \t"):
            paragraph_open = False
            offset += len(line)
            continue
        html_start, next_html_block = _html_block_start(
            source_line,
            allow_type_7=not paragraph_open,
        )
        if html_start:
            html_block = next_html_block
            paragraph_open = False
            offset += len(line)
            continue
        fence_match = FENCE_OPEN.match(source_line)
        if fence_match:
            marker = fence_match.group(1)
            info_string = source_line[fence_match.end(1) :]
            if marker[0] != "`" or "`" not in info_string:
                fence = (marker[0], len(marker))
                paragraph_open = False
                offset += len(line)
                continue
        match = ATX_HEADING.match(source_line)
        if match:
            level = len(match.group(1))
            raw_title = match.group(2) or ""
            if re.fullmatch(r"#+[ \t]*", raw_title):
                raw_title = ""
            else:
                raw_title = re.sub(r"[ \t]+#+[ \t]*$", "", raw_title)
            title = unicodedata.normalize("NFC", raw_title.strip(" \t"))
            while stack and stack[-1]["level"] >= level:
                stack.pop()
            parent_id = stack[-1]["id"] if stack else None
            key = (parent_id, level, title)
            ordinal = sibling_counts.get(key, 0)
            sibling_counts[key] = ordinal + 1
            heading = {
                "id": _canonical_hash(
                    "glassgraph:heading:v1",
                    {
                        "document_id": document_id,
                        "level": level,
                        "parent_id": parent_id,
                        "same_name_ordinal": ordinal,
                        "title": title,
                    },
                ),
                "level": level,
                "title": title,
                "start": offset,
                "line": line_number,
                "path": [item["title"] for item in stack] + [title],
            }
            headings.append(heading)
            stack.append(heading)
            paragraph_open = False
        else:
            paragraph_open = True
        offset += len(line)
    for index, heading in enumerate(headings):
        heading["end"] = (
            headings[index + 1]["start"] if index + 1 < len(headings) else len(text)
        )
    return headings


def _physical_lines(text: str):
    """Yield source lines split only at CR, LF, or CRLF delimiters."""
    start = 0
    index = 0
    while index < len(text):
        if text[index] not in "\r\n":
            index += 1
            continue
        end = index + 1
        if text[index] == "\r" and end < len(text) and text[end] == "\n":
            end += 1
        yield text[start:index], text[index:end]
        start = end
        index = end
    if start < len(text):
        yield text[start:], ""


def _original_utf8_byte_offset(
    original_text: str,
    normalized_offset: int,
) -> int:
    normalized_cursor = 0
    byte_cursor = 0
    for content, ending in _physical_lines(original_text):
        original_line = content + ending
        normalized_content = unicodedata.normalize("NFC", content)
        content_end = normalized_cursor + len(normalized_content)
        if normalized_offset <= content_end:
            column = normalized_offset - normalized_cursor
            if unicodedata.is_normalized("NFC", content):
                return byte_cursor + len(content[:column].encode("utf-8"))
            target_prefix = normalized_content[:column]
            target_suffix = normalized_content[column:]
            boundaries = [
                index
                for index in range(len(content) + 1)
                if unicodedata.normalize("NFC", content[:index]) == target_prefix
                and unicodedata.normalize("NFC", content[index:]) == target_suffix
            ]
            if len(boundaries) == 1:
                return byte_cursor + len(content[: boundaries[0]].encode("utf-8"))
            raise ValueError(
                "Normalized evidence coordinate has no exact source interval"
            )
        normalized_cursor = content_end
        if ending:
            normalized_cursor += 1
            if normalized_offset <= normalized_cursor:
                return byte_cursor + len(original_line.encode("utf-8"))
        byte_cursor += len(original_line.encode("utf-8"))
    if normalized_offset == normalized_cursor:
        return byte_cursor
    raise ValueError("Normalized evidence coordinate is outside the source document")


def derive_evidence_records(
    corpus_root: str | Path,
    judgment: dict,
) -> list[dict]:
    """Derive every ADR-0013 identity for an exact judged passage occurrence."""
    root = Path(corpus_root).resolve()
    canonical_path = _canonical_document_path(judgment["path"])
    if PurePosixPath(canonical_path).suffix != ".md":
        raise ValueError("Evidence judgment is outside the frozen Markdown corpus")
    source_path = dict(_corpus_markdown_paths(root)).get(canonical_path)
    if source_path is None:
        raise ValueError("Evidence judgment path is outside the corpus")
    source_bytes = source_path.read_bytes()
    original_text = source_bytes.decode("utf-8")
    text = unicodedata.normalize(
        "NFC",
        original_text.replace("\r\n", "\n").replace("\r", "\n"),
    )
    passage = unicodedata.normalize(
        "NFC",
        str(judgment["text"]).replace("\r\n", "\n").replace("\r", "\n"),
    )
    if not passage:
        raise ValueError("Evidence judgment passage is empty")

    document_id = _canonical_hash("glassgraph:document:v1", {"path": canonical_path})
    headings = _heading_instances(text, document_id)
    source_hash = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    records = []
    start = 0
    ordinals = {}
    while True:
        occurrence = text.find(passage, start)
        if occurrence < 0:
            break
        occurrence_passage = (
            passage + "\n"
            if not passage.endswith("\n")
            and text.startswith(passage + "\n", occurrence)
            else passage
        )
        passage_hash = "sha256:" + hashlib.sha256(
            occurrence_passage.encode("utf-8")
        ).hexdigest()
        heading = max(
            (item for item in headings if item["start"] <= occurrence),
            key=lambda item: item["start"],
        )
        occurrence_end = occurrence + len(occurrence_passage)
        if occurrence_end > heading["end"]:
            start = occurrence + 1
            continue
        ordinal_key = (heading["id"], passage_hash)
        passage_ordinal = ordinals.get(ordinal_key, 0)
        ordinals[ordinal_key] = passage_ordinal + 1
        line_start = text.count("\n", 0, occurrence) + 1
        line_end = (
            line_start
            + occurrence_passage.count("\n")
            - int(occurrence_passage.endswith("\n"))
        )
        records.append(
            {
                "document_id": document_id,
                "heading_id": heading["id"],
                "evidence_id": _canonical_hash(
                    "glassgraph:evidence:v1",
                    {
                        "document_id": document_id,
                        "heading_id": heading["id"],
                        "passage_hash": passage_hash,
                        "passage_ordinal": passage_ordinal,
                    },
                ),
                "passage_hash": passage_hash,
                "normalized_passage": occurrence_passage,
                "source_hash": source_hash,
                "path": canonical_path,
                "heading": heading["title"],
                "heading_path": heading["path"],
                "line_start": line_start,
                "line_end": max(line_start, line_end),
                "utf8_byte_start": _original_utf8_byte_offset(
                    original_text, occurrence
                ),
                "utf8_byte_end": _original_utf8_byte_offset(
                    original_text, occurrence_end
                ),
            }
        )
        start = occurrence + 1
    return records


def validate_evidence_judgments(records: list[dict], corpus_root: str | Path) -> None:
    """Reject benchmark judgments that are not valid ADR-0013 evidence identities."""
    for query in records:
        judgments = _passages(query.get("required_groups", []))
        judgments.extend(query.get("irrelevant") or [])
        for judgment in judgments:
            derived = derive_evidence_records(corpus_root, judgment)
            matching = [
                record
                for record in derived
                if record["evidence_id"] == judgment.get("evidence_id")
                and record["heading"] == judgment.get("heading", record["heading"])
            ]
            if len(matching) != 1:
                raise ValueError("A benchmark record has an invalid evidence identity")


def verify_evidence_hits(
    queries: list[dict],
    runs: dict[str, dict],
    corpus_root: str | Path,
) -> None:
    """Attach only ADR-0013 evidence IDs proven by exact source coordinates."""
    root = Path(corpus_root).resolve()
    for query in queries:
        passages = _passages(query.get("required_groups", []))
        judgments = []
        for passage in passages:
            records = derive_evidence_records(root, passage)
            selected = [
                record
                for record in records
                if record["evidence_id"] == passage["evidence_id"]
                and record["heading"] == passage.get("heading", record["heading"])
            ]
            if len(selected) == 1:
                judgments.append((passage, records, selected[0]))
        run = runs.get(query["id"], {})
        seen_hits = set()
        for hit_list in (run.get("raw_hits", []), run.get("hits", [])):
            for hit in hit_list:
                if id(hit) in seen_hits:
                    continue
                seen_hits.add(id(hit))
                verified_ids = set()
                for passage, occurrences, selected in judgments:
                    if (
                        not isinstance(hit.get("path"), str)
                        or _canonical_document_path(hit["path"]) != selected["path"]
                        or not _normalized_hit_contains_passage(
                            str(hit.get("text") or ""),
                            selected["normalized_passage"],
                        )
                    ):
                        continue
                    locator = hit.get("backend_locator") or {}
                    line = locator.get("line")
                    if locator.get("kind") == "heuristic_line":
                        matching_occurrences = [
                            record
                            for record in occurrences
                            if isinstance(line, int)
                            and record["line_start"] <= line <= record["line_end"]
                        ]
                        if matching_occurrences == [selected]:
                            verified_ids.add(selected["evidence_id"])
                    elif len(occurrences) == 1:
                        verified_ids.add(selected["evidence_id"])
                hit["evidence_ids"] = sorted(verified_ids)


def _normalized_hit_contains_passage(hit_text: str, passage: str) -> bool:
    normalized_hit = unicodedata.normalize(
        "NFC",
        hit_text.replace("\r\n", "\n").replace("\r", "\n"),
    )
    if passage in normalized_hit:
        return True
    if not passage.endswith("\n"):
        return False
    line_without_ending = passage[:-1]
    start = 0
    while True:
        occurrence = normalized_hit.find(line_without_ending, start)
        if occurrence < 0:
            return False
        end = occurrence + len(line_without_ending)
        if end == len(normalized_hit) or normalized_hit[end] == "\n":
            return True
        start = occurrence + max(1, len(line_without_ending))


def _passages(groups: list[list[dict]]) -> list[dict]:
    passages = [passage for group in groups for passage in group]
    if any(not passage.get("evidence_id") for passage in passages):
        raise ValueError("Every positive evidence judgment needs an evidence_id")
    return passages


def _matches(hit: dict, passage: dict) -> bool:
    return passage["evidence_id"] in hit.get("evidence_ids", [])


def _dcg(grades: list[int]) -> float:
    return sum((2**grade - 1) / math.log2(rank + 1) for rank, grade in enumerate(grades, start=1))


def _ranked_group_matches(groups: list[list[dict]], hits: list[dict]):
    grade_value = {"direct": 2, "supporting": 1}
    _passages(groups)
    unused = set(range(len(groups)))
    for hit in hits:
        matching = [
            (
                max(
                    grade_value[passage["grade"]]
                    for passage in groups[index]
                    if _matches(hit, passage)
                ),
                index,
            )
            for index in unused
            if any(_matches(hit, passage) for passage in groups[index])
        ]
        if not matching:
            yield 0, None
            continue
        grade, index = max(matching, key=lambda item: (item[0], -item[1]))
        unused.remove(index)
        yield grade, index


def _ndcg_at_10(groups: list[list[dict]], hits: list[dict]) -> float:
    grade_value = {"direct": 2, "supporting": 1}
    ranked_grades = [grade for grade, _index in _ranked_group_matches(groups, hits[:10])]

    ideal = sorted(
        (max(grade_value[passage["grade"]] for passage in group) for group in groups),
        reverse=True,
    )[:10]
    ideal_dcg = _dcg(ideal)
    return _dcg(ranked_grades) / ideal_dcg if ideal_dcg else 0.0


def _percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def _has_explanation_trace(hit: dict) -> bool:
    explanation = hit.get("explanation")
    if not isinstance(explanation, dict):
        return False
    kind = explanation.get("kind")
    value = explanation.get("value")
    if kind == "match_spans":
        text_byte_length = len(str(hit.get("text") or "").encode("utf-8"))
        return (
            isinstance(value, list)
            and bool(value)
            and all(
                isinstance(span, dict)
                and isinstance(span.get("start"), int)
                and isinstance(span.get("end"), int)
                and 0 <= span["start"] < span["end"] <= text_byte_length
                for span in value
            )
        )
    if kind == "qmd_explain":
        supported = {"blendedScore", "ftsScores", "vectorScores", "rrf", "lex", "vec"}
        return isinstance(value, dict) and any(
            key in value and _is_meaningful_explanation_value(value[key])
            for key in supported
        )
    return False


def _has_faithful_explanation(hit: dict, query_text: str) -> bool:
    """Return whether a trace can be verified against the query and returned text."""
    if not _has_explanation_trace(hit):
        return False
    explanation = hit["explanation"]
    if explanation["kind"] != "match_spans":
        return False
    normalized_query = unicodedata.normalize("NFC", query_text).casefold()
    if not normalized_query.strip():
        return False
    text_bytes = str(hit.get("text") or "").encode("utf-8")
    for span in explanation["value"]:
        try:
            matched_text = text_bytes[span["start"] : span["end"]].decode("utf-8")
        except UnicodeDecodeError:
            return False
        normalized_match = unicodedata.normalize("NFC", matched_text).casefold().strip()
        match_terms = re.findall(r"\w+", normalized_match)
        query_terms = set(re.findall(r"\w+", normalized_query))
        meaningful_term = any(
            len(term) >= 2
            or term.isdigit()
            for term in match_terms
        )
        cjk_match = (
            len(re.findall(r"[\u3400-\u9fff]", normalized_match)) >= 2
            and normalized_match in normalized_query
        )
        if not (
            cjk_match
            or (
                match_terms
                and meaningful_term
                and all(term in query_terms for term in match_terms)
            )
        ):
            return False
    return True


def _is_meaningful_explanation_value(value) -> bool:
    if value is None:
        return False
    if isinstance(value, (list, dict, str)):
        return bool(value)
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def evaluate(queries: list[dict], runs: dict[str, dict]) -> dict:
    """Return aggregate metrics for ranked retrieval runs."""
    recalls_at_5 = []
    recalls_at_10 = []
    reciprocal_ranks = []
    ndcgs = []
    negative_queries = 0
    negative_false_positives = 0
    negative_raw_false_positives = 0
    latencies = []
    peak_working_sets = []
    path_relevant_hits = 0
    exact_evidence_hits = 0
    context_tokens_top_5 = []
    explained_hits_top_5 = []
    faithful_explanations_top_5 = []
    top_5_hit_count = 0
    for query in queries:
        run = runs.get(query["id"], {"hits": []})
        accepted_hits = run.get("hits", [])
        raw_hits = run.get("raw_hits", accepted_hits)
        if "latency_ms" in run:
            latencies.append(run["latency_ms"])
        if "peak_working_set_bytes" in run:
            peak_working_sets.append(run["peak_working_set_bytes"])
        context_tokens_top_5.append(
            sum(hit.get("context_tokens", 0) for hit in raw_hits[:5])
        )
        explained_hits_top_5.append(
            sum(_has_explanation_trace(hit) for hit in raw_hits[:5])
        )
        faithful_explanations_top_5.append(
            sum(
                _has_faithful_explanation(hit, str(query.get("query") or ""))
                for hit in raw_hits[:5]
            )
        )
        top_5_hit_count += len(raw_hits[:5])
        groups = query.get("required_groups", [])
        if not groups:
            negative_queries += 1
            if raw_hits[:5]:
                negative_raw_false_positives += 1
            if accepted_hits[:5]:
                negative_false_positives += 1
            continue
        _passages(groups)
        for limit, recalls in ((5, recalls_at_5), (10, recalls_at_10)):
            satisfied = sum(
                any(
                    _matches(hit, passage)
                    for hit in raw_hits[:limit]
                    for passage in group
                )
                for group in groups
            )
            recalls.append(satisfied / len(groups))
        expected_paths = {
            _canonical_document_path(passage["path"])
            for group in groups
            for passage in group
        }

        def hit_path(hit: dict) -> str | None:
            try:
                value = hit.get("path")
                return _canonical_document_path(value) if isinstance(value, str) else None
            except ValueError:
                return None

        first_relevant_rank = next(
            (
                rank
                for rank, hit in enumerate(raw_hits, start=1)
                if hit_path(hit) in expected_paths
            ),
            None,
        )
        reciprocal_ranks.append(1 / first_relevant_rank if first_relevant_rank else 0.0)
        ndcgs.append(_ndcg_at_10(groups, raw_hits))
        path_relevant_hits += sum(
            hit_path(hit) in expected_paths for hit in raw_hits[:10]
        )
        exact_evidence_hits += sum(
            any(
                _matches(hit, passage)
                for group in groups
                for passage in group
            )
            for hit in raw_hits[:10]
        )

    return {
        "positive_queries": len(recalls_at_5),
        "group_recall_at_5": (
            sum(recalls_at_5) / len(recalls_at_5) if recalls_at_5 else 0.0
        ),
        "group_recall_at_10": (
            sum(recalls_at_10) / len(recalls_at_10) if recalls_at_10 else 0.0
        ),
        "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks) if reciprocal_ranks else 0.0,
        "ndcg_at_10": sum(ndcgs) / len(ndcgs) if ndcgs else 0.0,
        "evidence_span_accuracy": (
            exact_evidence_hits / path_relevant_hits if path_relevant_hits else 0.0
        ),
        "negative_queries": negative_queries,
        "negative_false_positive_rate_at_5": (
            negative_false_positives / negative_queries if negative_queries else 0.0
        ),
        "negative_raw_false_positive_rate_at_5": (
            negative_raw_false_positives / negative_queries if negative_queries else 0.0
        ),
        "latency_ms_p50": statistics.median(latencies) if latencies else 0.0,
        "latency_ms_p95": _percentile(latencies, 0.95) if latencies else 0.0,
        "peak_working_set_bytes": max(peak_working_sets, default=0),
        "mean_context_tokens_top_5": (
            statistics.mean(context_tokens_top_5) if context_tokens_top_5 else 0.0
        ),
        "mean_explained_hits_top_5": (
            statistics.mean(explained_hits_top_5) if explained_hits_top_5 else 0.0
        ),
        "explanation_trace_availability_rate_top_5": (
            sum(explained_hits_top_5) / top_5_hit_count if top_5_hit_count else 0.0
        ),
        "explanation_fidelity_rate_top_5": (
            sum(faithful_explanations_top_5) / top_5_hit_count
            if top_5_hit_count
            else 0.0
        ),
    }
