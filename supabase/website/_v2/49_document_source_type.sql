-- Add uploaded documents as a first-class v2 content source.

ALTER TABLE content.canonical_zettels
    DROP CONSTRAINT IF EXISTS canonical_zettels_source_type_check;

ALTER TABLE content.canonical_zettels
    ADD CONSTRAINT canonical_zettels_source_type_check
    CHECK (
        source_type IN (
            'youtube',
            'reddit',
            'github',
            'twitter',
            'substack',
            'newsletter',
            'medium',
            'hackernews',
            'linkedin',
            'arxiv',
            'podcast',
            'document',
            'web',
            'generic'
        )
    );
