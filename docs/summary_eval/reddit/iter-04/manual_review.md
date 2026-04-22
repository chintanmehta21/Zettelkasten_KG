eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - Reddit iter-04

## URL 1: Rajkot / Hyundai IPO thread

### brief_summary (/25)
The brief still communicates the OP claim, major dissent, and removed-comment caveat, but it is clipped and under-expanded. It reads like a compressed template rather than a finished Reddit summary, and it still does not deliver a natural 5-7 sentence overview.

Score: 19/25

### detailed_summary (/45)
The detailed layer remains solid on this URL. It preserves the main dispute, records the plagiarism point, captures the stock-market-culture confirmation, and keeps the moderation context explicit. It is a little thinner than earlier training-loop versions because some reply diversity has been compressed away, but it is still broadly production-usable.

Score: 37/45

### tags (/15)
The tags are specific and useful. They still miss the more explicit Reddit thread-type framing the rubric wants.

Score: 12/15

### label (/15)
The label is structurally correct and neutral, but it is still a generic compression of the OP framing rather than the core debate the thread actually centers on.

Score: 12/15

### URL 1 subtotal
Score: 80/100

## URL 2: IAmA heroin thread

### brief_summary (/25)
This brief is not good enough for the complexity of the thread. It captures the OP frame and acknowledges replies plus minority dissent, but every sentence is clipped, the substance is incomplete, and the real warning/caveat structure of the discussion is under-explained. For a thread where the response range matters enormously, the brief feels too synthetic and too small.

Score: 10/25

### detailed_summary (/45)
The detailed summary is where the cross-URL regression becomes obvious. It reduces a large, emotionally varied, heavily moderated discussion into essentially one dominant addiction-warning cluster plus a short list of counterarguments. That misses the richer range of response types in the thread: experiential caution, harm-reduction framing, anti-moralizing comments, distinctions between one-time use and dependency, and strong personal testimonies from former users. The moderation note is present, which is good, but the underlying cluster coverage is too narrow for a thread this large and divergent.

Score: 18/45

### tags (/15)
The tags are specific and thread-appropriate. They do a good job of capturing the topic, risk frame, and subreddit context.

Score: 14/15

### label (/15)
The label is structurally valid and neutral, but it is generic and undersells the real issue the comments focus on: addiction risk and the OP's rationalization pattern.

Score: 11/15

### URL 2 subtotal
Score: 53/100

## Anti-patterns
The previous removed-comment omission problem looks fixed, because both URLs now acknowledge visible-versus-total comment divergence. The main cross-URL problem is not omission of moderation context but over-compression of experiential or morally contested reply structures into one dominant cluster. That is especially damaging on the heroin thread, where preserving the range of warnings, caveats, and dissent is the whole task.

## Most impactful improvement for iter-05
The next tune should broaden Reddit clustering for experiential threads without weakening the finance-thread wins. The safest path is to keep the moderation-context injection and label/subreddit fixes, but change the Reddit summary contract so high-divergence personal-experience threads must emit at least two or three materially different reply clusters and a fuller brief that distinguishes dominant warnings from minority normalization or legalization-style arguments.

estimated_composite: 66.5
