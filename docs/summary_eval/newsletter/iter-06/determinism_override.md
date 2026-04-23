# Determinism Override - iter-06

Iter-06 was run with `--skip-determinism` after fixing evaluator parser bugs that were causing malformed JSON and 0-100 G-Eval scale outputs to crash or distort replay. The prior iter-05 stored score is therefore not directly comparable to the corrected evaluator implementation. This override is limited to the parser-fix boundary; later iterations should use the normal determinism gate again.
