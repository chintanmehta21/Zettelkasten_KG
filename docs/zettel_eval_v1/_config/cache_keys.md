# Canonical cache-key composition

Per Sub-5 sweep — Anthropic prompt-caching docs + Brenndoerfer 2026 reference pattern.
Cache invalidation is **input-chain cascading**: if facts re-run, judges invalidate; if
judge re-runs, composite invalidates.

The cache key tuple for each cache is:

```
sha256(
    provider                         # "google" | "anthropic" | "huggingface"
    || response_model                # the EXACT revision the API returned, not the requested alias
    || prompt_template_sha256        # sha256 of the rendered prompt template
    || prompt_version                # e.g. "evaluator.v7" | "atomic_facts.v1"
    || tool_schema_sha256            # sha256 of any function-calling / JSON schema attached
    || input_normalized_sha256       # sha256 of the canonicalised inputs (see per-cache below)
    || decoding_params_sha256        # temperature, max_output_tokens, top_p, seed, response_mime_type
)
```

## Per-cache specifics

### `_cache/ingests/<sha>.json`
- inputs: (normalized_url, ingestor_version, ingestor_config_sha)
- existing pattern in `summary_eval_v2`; keep.

### `_cache/atomic_facts/<sha>.json`
- inputs: (canonical_zettel_id, ingestor_version, source_text_sha256, extractor_id, extractor_temperature)
- **ADD** `response_model` from the Gemini SDK response (`GenerateContentResponse.modelVersion`).
  Without this, a silent Google-side model swap returns identical facts cache hits with
  different semantics. The drift signal is invisible.

### `_cache/judge_<provider>/<sha>.json`
- inputs: (canonical_zettel_id, atomic_facts_sha256, summary_sha256, rubric_sha256,
  per_source_criteria_sha256, prompt_version, judge_model_id, judge_decoding_params_sha,
  response_model)
- **Cascade**: when atomic_facts re-run, atomic_facts_sha256 changes -> all dependent
  judge_output cache rows invalidate automatically.

### `_cache/nli_outputs/<sha>.json`
- inputs: (canonical_zettel_id, summary_sha256, source_text_sha256, nli_model_revision,
  nli_device, nli_precision, max_premise_tokens, max_hypothesis_tokens)
- `nli_model_revision` MUST pin the HuggingFace revision hash, not just the model name.

## Drift signals the cache key carries

- `response_model` change between two consecutive runs with otherwise identical inputs ->
  silent vendor model update. Surface in the next-run report.
- `prompt_version` bumped without `rubric_sha256` change -> log-only; cache invalidates by design.
- Two cache hits sharing all keys EXCEPT `response_model` -> Gemini routed the same
  request to two different model revisions. Investigate.
