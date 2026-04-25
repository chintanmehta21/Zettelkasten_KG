"""Context assembly for grounded generation."""

from __future__ import annotations

import html
import re
from collections import OrderedDict

from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate

_BUDGET_BY_QUALITY = {"fast": 6000, "high": 12000}
_MIN_USEFUL_TOKENS = 40
_MIN_USEFUL_CHARS = 40

# Minimum overlap (in chars) between prev-chunk tail and curr-chunk head that
# we're willing to call "the late-chunker's sliding window" and trim. Anything
# shorter is likely coincidence (shared stop-words, repeated title) and leaving
# it alone is safer than a lossy trim. 40 chars ≈ one short sentence.
_MIN_OVERLAP_TRIM = 40
# Cap the overlap search so a pathologically long chunk doesn't turn this into
# a hot loop; real chunks are well under this in practice.
_MAX_OVERLAP_SEARCH = 2000

# Placeholders that survive extraction failures and carry no signal. Matching
# is case-insensitive and ignores surrounding markdown/punctuation so variants
# like "## Transcript\n\n(Transcript not available)" are caught.
_STUB_PLACEHOLDERS = (
    "transcript not available",
    "transcript unavailable",
    "content unavailable",
    "no content available",
    "[deleted]",
    "[removed]",
)


class ContextAssembler:
    """Build an XML context block from retrieval candidates."""

    def __init__(self, *, compressor=None):
        self._compressor = compressor

    async def build(
        self,
        *,
        candidates: list[RetrievalCandidate],
        quality: str = "fast",
        user_query: str,
    ) -> tuple[str, list[RetrievalCandidate]]:
        if not candidates:
            return "<context>\n  <!-- no relevant Zettels found -->\n</context>", []

        budget = _BUDGET_BY_QUALITY[quality]
        candidates = [c for c in candidates if not _is_stub_passage(c.content)]
        # iter-04 retune: soften the floor 0.30 -> 0.22. iter-03 showed
        # context_precision doubled (0.33 -> 0.67) but graph_lift_rerank flipped
        # +28.81 -> -11.67 because the floor was preferentially cutting
        # graph-boosted candidates whose rrf+rerank were modest but graph_score
        # was strong. The composite-floor 0.30 was a hammer; 0.22 keeps the
        # precision win while letting the KG signal shine through.
        # See iter-03/improvement_delta.json for the trade-off curve.
        _CONTEXT_FLOOR = 0.22
        def _passes_floor(c):
            score = c.final_score if c.final_score is not None else (c.rerank_score or 0.0)
            return score >= _CONTEXT_FLOOR
        floored = [c for c in candidates if _passes_floor(c)]
        # Safety: never empty the context due to the floor — if nothing passes,
        # keep the top-1 candidate so the LLM has something to ground on rather
        # than refusing.
        if floored:
            candidates = floored
        elif candidates:
            candidates = candidates[:1]
        if not candidates:
            return "<context>\n  <!-- no relevant Zettels found -->\n</context>", []
        grouped = self._group_by_node(candidates)
        grouped = [self._trim_intra_group_overlap(group) for group in grouped]
        # Overlap trimming can reduce a chunk below the stub threshold; drop
        # any group that ends up empty so we don't render a bare <zettel/>.
        grouped = [group for group in grouped if group]
        if not grouped:
            return "<context>\n  <!-- no relevant Zettels found -->\n</context>", []
        grouped.sort(key=lambda group: max(item.final_score or item.rrf_score for item in group), reverse=True)
        sandwiched = self._sandwich_order(grouped)
        fitted, used = await self._fit_within_budget(sandwiched, budget, user_query)
        return self._render_xml(fitted), used

    def _group_by_node(self, candidates: list[RetrievalCandidate]) -> list[list[RetrievalCandidate]]:
        groups = OrderedDict()
        for candidate in candidates:
            groups.setdefault(candidate.node_id, []).append(candidate)
        for group in groups.values():
            group.sort(key=lambda item: (item.kind != ChunkKind.SUMMARY, item.chunk_idx))
        return list(groups.values())

    def _trim_intra_group_overlap(
        self, group: list[RetrievalCandidate]
    ) -> list[RetrievalCandidate]:
        """Trim the sliding-window overlap from consecutive chunks in a group.

        Only chunk-kind passages are candidates — summaries are standalone and
        never trimmed. Adjacency is judged by ``chunk_idx``: a gap (e.g. 3→7)
        means the chunker dropped middle chunks and any literal head/tail
        match is coincidence, so we leave those alone.
        """
        if len(group) <= 1:
            return group
        chunk_items = [c for c in group if c.kind is ChunkKind.CHUNK]
        chunk_items.sort(key=lambda c: c.chunk_idx)
        trimmed_content: dict[int, str] = {}
        for index in range(1, len(chunk_items)):
            prev = chunk_items[index - 1]
            curr = chunk_items[index]
            if curr.chunk_idx - prev.chunk_idx != 1:
                continue
            prev_content = trimmed_content.get(index - 1, prev.content) or ""
            curr_content = curr.content or ""
            new_curr = _trim_leading_overlap(prev_content, curr_content)
            if new_curr != curr_content:
                trimmed_content[index] = new_curr
        if not trimmed_content:
            return group
        replacements: dict[int, RetrievalCandidate] = {}
        to_drop: set[int] = set()
        for index, new_content in trimmed_content.items():
            original = chunk_items[index]
            if _is_stub_passage(new_content):
                to_drop.add(id(original))
                continue
            replacements[id(original)] = original.model_copy(update={"content": new_content})
        result: list[RetrievalCandidate] = []
        for item in group:
            item_id = id(item)
            if item_id in to_drop:
                continue
            if item_id in replacements:
                result.append(replacements[item_id])
            else:
                result.append(item)
        return result

    def _sandwich_order(self, groups: list[list[RetrievalCandidate]]) -> list[list[RetrievalCandidate]]:
        if len(groups) <= 2:
            return groups
        return [groups[0], *groups[2:], groups[1]]

    async def _fit_within_budget(
        self,
        grouped: list[list[RetrievalCandidate]],
        budget: int,
        user_query: str,
    ) -> tuple[list[list[RetrievalCandidate]], list[RetrievalCandidate]]:
        """Greedy budget packing with per-group partial inclusion.

        The first group is always kept whole (minimum-coverage guarantee even
        if it overflows). For every subsequent group, the summary goes first
        (synthetic high-signal digest), then chunks are considered in
        descending final_score order so when budget is tight the
        highest-relevance chunks land ahead of lower-ranked siblings. Items
        that would overflow the remaining budget are skipped rather than
        breaking the loop — a fat high-score chunk shouldn't starve a smaller
        mid-score sibling of its slot. Once the subset is fixed, it's
        re-ordered back to summary-first / chunk_idx ascending so the rendered
        passage sequence preserves the document's narrative flow.
        """
        del user_query
        used_tokens = 0
        fitted: list[list[RetrievalCandidate]] = []
        used: list[RetrievalCandidate] = []
        for group in grouped:
            if not fitted:
                fitted.append(group)
                used.extend(group)
                used_tokens += sum(
                    max(_MIN_USEFUL_TOKENS, len(item.content) // 4) for item in group
                )
                continue
            remaining = budget - used_tokens
            if remaining <= 0:
                break
            summaries = [it for it in group if it.kind is ChunkKind.SUMMARY]
            chunks = [it for it in group if it.kind is not ChunkKind.SUMMARY]
            packing_order: list[RetrievalCandidate] = [
                *summaries,
                *sorted(
                    chunks,
                    key=lambda it: it.final_score if it.final_score is not None else it.rrf_score,
                    reverse=True,
                ),
            ]
            subset: list[RetrievalCandidate] = []
            subset_tokens = 0
            for item in packing_order:
                item_tokens = max(_MIN_USEFUL_TOKENS, len(item.content) // 4)
                if subset_tokens + item_tokens > remaining:
                    continue
                subset.append(item)
                subset_tokens += item_tokens
            if subset:
                render_order = [it for it in subset if it.kind is ChunkKind.SUMMARY]
                render_order.extend(
                    sorted(
                        (it for it in subset if it.kind is not ChunkKind.SUMMARY),
                        key=lambda it: it.chunk_idx,
                    )
                )
                fitted.append(render_order)
                used.extend(render_order)
                used_tokens += subset_tokens
        return fitted, used

    def _render_xml(self, grouped: list[list[RetrievalCandidate]]) -> str:
        lines = ["<context>"]
        primary = self._select_primary(grouped)
        for group in grouped:
            first = group[0]
            tags = ",".join(first.tags)
            lines.append(
                f'  <zettel id="{html.escape(first.node_id)}" source="{html.escape(first.source_type.value)}" '
                f'url="{html.escape(first.url)}" title="{html.escape(first.name)}" tags="{html.escape(tags)}">'
            )
            for candidate in group:
                chunk_id = candidate.chunk_id or ""
                timestamp = candidate.metadata.get("timestamp") if candidate.metadata else None
                timestamp_attr = f' timestamp="{html.escape(str(timestamp))}"' if timestamp else ""
                primary_attr = ' primary="true"' if candidate is primary else ""
                lines.append(
                    f'    <passage chunk_id="{html.escape(str(chunk_id))}"{primary_attr}{timestamp_attr}>'
                    f'{html.escape(candidate.content)}</passage>'
                )
            lines.append("  </zettel>")
        lines.append("</context>")
        return "\n".join(lines)

    @staticmethod
    def _select_primary(
        grouped: list[list[RetrievalCandidate]],
    ) -> RetrievalCandidate | None:
        """Pick the single highest-scoring passage across the whole block.

        Exposing one ``primary="true"`` marker gives the LLM a clean cue about
        which passage is the strongest grounding source for citation —
        cheaper to reason over than a full score attribute per passage and
        less likely to leak raw RRF numbers that don't calibrate across
        queries. Returns ``None`` when every candidate has no score at all.
        """
        best: RetrievalCandidate | None = None
        best_score: float | None = None
        for group in grouped:
            for candidate in group:
                score = (
                    candidate.final_score
                    if candidate.final_score is not None
                    else candidate.rrf_score
                )
                if score is None:
                    continue
                if best_score is None or score > best_score:
                    best_score = score
                    best = candidate
        return best


def _trim_leading_overlap(prev: str, curr: str) -> str:
    """Return ``curr`` with its leading overlap against ``prev``'s tail removed.

    Scans from the longest possible overlap down to ``_MIN_OVERLAP_TRIM`` and
    returns the first literal match. Leading whitespace remaining after the
    trim is stripped so the passage starts cleanly. If no qualifying overlap
    exists, returns ``curr`` unchanged.
    """
    if not prev or not curr:
        return curr
    max_check = min(len(prev), len(curr), _MAX_OVERLAP_SEARCH)
    if max_check < _MIN_OVERLAP_TRIM:
        return curr
    prev_tail = prev[-max_check:]
    for overlap_len in range(max_check, _MIN_OVERLAP_TRIM - 1, -1):
        if prev_tail[-overlap_len:] == curr[:overlap_len]:
            return curr[overlap_len:].lstrip()
    return curr


def _is_stub_passage(content: str | None) -> bool:
    """Return True for passages carrying no usable signal — either too short
    to be worth a slot or matching a known extraction-failure placeholder.
    Matching is case-insensitive with whitespace collapsed so markdown-wrapped
    stubs (``## Transcript\\n\\n(Transcript not available)``) are caught."""
    if not content:
        return True
    stripped = content.strip()
    if len(stripped) < _MIN_USEFUL_CHARS:
        return True
    normalized = re.sub(r"\s+", " ", stripped.lower())
    return any(placeholder in normalized for placeholder in _STUB_PLACEHOLDERS)
