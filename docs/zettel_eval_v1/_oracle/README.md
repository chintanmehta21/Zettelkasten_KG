# `_oracle/` — answer keys, NEVER read by the LLM judge at runtime

This directory holds **ground-truth answer keys** for calibration / evaluation
items. They are deliberately separated from the prompt-side artefacts in
`_config/` and `_data/` so that:

1. **The judge prompt construction code (`02_run_judge.py`,
   `10_judge_calibration.py`) MUST NOT read from this directory.**
   Use `Grep "_oracle"` in any judge-prompt code path as a CI guard.
2. **The runner (`10_judge_calibration.py`) loads the oracle only AFTER
   the judge has returned its verdict**, for the sole purpose of
   computing per-class detection rate.
3. **The oracle is operator-curated**, with no LLM-side dependency —
   ground truth comes from human authoring.

## Files

| File | Purpose | Joined to |
|------|---------|-----------|
| `judge_calibration_oracle.json` | Per-item answer key: FRANK class label, error span in summary, source evidence, brief rationale. | `_config/judge_calibration_set.json::items[]` by `id` |

## Schema for `judge_calibration_oracle.json`

```json
{
  "version": "calibration_oracle.v1",
  "answers": {
    "calib_01_EntE_worked_example": {
      "frank_class": "EntE",
      "error_span_in_summary": "published in 2018",
      "source_evidence": "Published 2020",
      "ground_truth_label": "EntE",
      "brief_rationale": "Year attribute swapped 2020 -> 2018."
    },
    "calib_NN_<class>_<slug>": { ... }
  }
}
```

## Defense-in-depth check

Before any iter runs, the harness should assert:

```python
assert "_oracle" not in str(prompt_template), \
    "Judge prompt must not reference the oracle directory."
```

This is a one-line defense embedded in the runner; the file-system
separation here is the other half of the protection.
