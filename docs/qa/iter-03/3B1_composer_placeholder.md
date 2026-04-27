# 3B.1 Composer placeholder reflects active Kasten (manual verification)

**Surface:** `/home/rag` composer textarea

## Checklist

- [ ] `/home/rag?sandbox=<id>` for a Kasten named "Knowledge Management" → placeholder reads `Ask Knowledge Management something…`.
- [ ] `/home/rag` with no sandbox → placeholder reads `Ask your Zettelkasten something…`.
- [ ] `/home/rag?sandbox=<id>&focus_node=...&focus_title=Reranking` → placeholder stays `Ask about Reranking...` (focus override wins).
- [ ] Switching sessions to one bound to a different sandbox updates the placeholder accordingly.
- [ ] Kasten names longer than 40 chars are truncated to 40.
