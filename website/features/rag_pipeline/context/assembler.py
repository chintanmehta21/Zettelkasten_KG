"""Context assembly for grounded generation."""

from __future__ import annotations

import html
from collections import OrderedDict

from website.features.rag_pipeline.types import ChunkKind, RetrievalCandidate

_BUDGET_BY_QUALITY = {"fast": 6000, "high": 12000}
_MIN_USEFUL_TOKENS = 40


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
        grouped = self._group_by_node(candidates)
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
        if it overflows). For every subsequent group, include as many of its
        items as fit — items are already sorted summary-first / chunk_idx
        ascending, so the highest-signal items land first. This preserves the
        old "top group wins" ranking while letting a summary from a lower-
        ranked group survive when a fat earlier group ate most of the budget.
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
            subset: list[RetrievalCandidate] = []
            subset_tokens = 0
            for item in group:
                item_tokens = max(_MIN_USEFUL_TOKENS, len(item.content) // 4)
                if subset_tokens + item_tokens > remaining:
                    break
                subset.append(item)
                subset_tokens += item_tokens
            if subset:
                fitted.append(subset)
                used.extend(subset)
                used_tokens += subset_tokens
        return fitted, used

    def _render_xml(self, grouped: list[list[RetrievalCandidate]]) -> str:
        lines = ["<context>"]
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
                lines.append(
                    f'    <passage chunk_id="{html.escape(str(chunk_id))}"{timestamp_attr}>'
                    f'{html.escape(candidate.content)}</passage>'
                )
            lines.append("  </zettel>")
        lines.append("</context>")
        return "\n".join(lines)

