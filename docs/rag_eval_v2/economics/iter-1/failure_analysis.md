# Failure analysis

- per-query exceptions: 0

## Gold-primary misses (4)

### q2 (lookup)
- expected: `['40e1a993-5d2c-4752-903f-a683d0b10bdb']`
- actual primary: `None`
- retrieved: `[]`
- verdict: supported  class: lookup

### q6 (multi_hop)
- expected: `['40e1a993-5d2c-4752-903f-a683d0b10bdb']`
- actual primary: `None`
- retrieved: `[]`
- verdict: supported  class: multi_hop

### q7 (thematic)
- expected: `['40e1a993-5d2c-4752-903f-a683d0b10bdb', 'fc376266-707f-42fb-9376-109d5071c722']`
- actual primary: `None`
- retrieved: `[]`
- verdict: supported  class: thematic

### q8 (step_back)
- expected: `['fc376266-707f-42fb-9376-109d5071c722']`
- actual primary: `None`
- retrieved: `[]`
- verdict: supported  class: multi_hop
