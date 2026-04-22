eval_json_hash_at_review: "NOT_CONSULTED"

# Manual Review - YouTube iter-02

## brief_summary (/25)
The brief summary is badly malformed because it is just a transcript fragment rendered as markdown-like bullets rather than a 5-7 sentence synthesis. It does surface that the video concerns the historical discovery of ayahuasca and the Banisteria caapi vine, so there is a small amount of topic signal. However, it never states the actual thesis of the video, does not identify the format, and does not name the host, channel, or expert speakers. It also does not surface durable takeaways a viewer would remember after watching. This fails most of the brief-summary contract and reads like a broken extraction rather than a summary.

Score: 4/25

## detailed_summary (/45)
The detailed summary has collapsed into schema fallback, so there is only one synthetic heading and one duplicated transcript fragment instead of a chronological walkthrough. That means the summary does not cover the historical arc, the chemistry and pharmacology explanation, the expert commentary, the warnings about use, or the clinical-study material visible in the source text. There is no proper chapter progression, no preservation of demonstrations or topic turns, and no real closing takeaway. Because the content is mostly a raw excerpt, it also reproduces phrasing too literally rather than summarizing purpose. This is the clearest failure in the output.

Score: 5/45

## tags (/15)
The tag set has the right count, but most of the tags are generic system boilerplate rather than source-grounded topical tags. `_schema_fallback_` is an implementation artifact, and `knowledge`, `notes`, `research`, `zettelkasten`, and `capture` are not useful topical descriptors for this video. There is no format tag, no mention of DMT, ayahuasca, psychedelics, neuroscience, or related entities actually present in the source. This tag set would be weak for retrieval and weak for human scanning.

Score: 2/15

## label (/15)
The label is concise and matches the source title shape, but that is also the main problem: it retains the original clickbait framing instead of converting the title into a content-first declarative label. It does not make the primary topic explicit enough for a knowledge note, since the key subject is DMT rather than a vague "strangest drug" hook. The wording is readable, but it does not meet the rubric's anti-clickbait intent.

Score: 6/15

## Anti-patterns
Triggered: `speakers_absent` yes, because no host/channel/expert names are captured in the summary. `clickbait_label_retention` yes, because the label repeats the hook phrasing from the source title. A schema-fallback artifact is also visible in both the tags and detailed summary. `invented_chapter` does not appear to be the core problem in this run; structural collapse is.

## Most impactful improvement for iter-03
The next fix should target the YouTube structured-extraction contract directly. The ingest layer now includes timestamp markers, but the summarizer is failing to turn that text into valid `YouTubeStructuredPayload`, so the whole run degrades into fallback garbage. The production-grade fix is to make the YouTube extraction path robust to timestamp-rich transcripts by tightening prompt/schema handling and adding a regression test that proves timestamped input still yields a valid structured payload instead of `_schema_fallback_`.

estimated_composite: 24.0
