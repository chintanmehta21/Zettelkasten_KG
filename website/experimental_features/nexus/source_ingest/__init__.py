from website.experimental_features.nexus.source_ingest.common.models import NexusProvider
from website.experimental_features.nexus.source_ingest.github import ingest as github_ingest
from website.experimental_features.nexus.source_ingest.github import oauth as github_oauth
from website.experimental_features.nexus.source_ingest.reddit import ingest as reddit_ingest
from website.experimental_features.nexus.source_ingest.reddit import oauth as reddit_oauth
from website.experimental_features.nexus.source_ingest.twitter import ingest as twitter_ingest
from website.experimental_features.nexus.source_ingest.twitter import oauth as twitter_oauth
from website.experimental_features.nexus.source_ingest.youtube import ingest as youtube_ingest
from website.experimental_features.nexus.source_ingest.youtube import oauth as youtube_oauth

OAUTH_HANDLERS = {
    NexusProvider.YOUTUBE: youtube_oauth,
    NexusProvider.GITHUB: github_oauth,
    NexusProvider.REDDIT: reddit_oauth,
    NexusProvider.TWITTER: twitter_oauth,
}

INGEST_HANDLERS = {
    NexusProvider.YOUTUBE: youtube_ingest.ingest_artifacts,
    NexusProvider.GITHUB: github_ingest.ingest_artifacts,
    NexusProvider.REDDIT: reddit_ingest.ingest_artifacts,
    NexusProvider.TWITTER: twitter_ingest.ingest_artifacts,
}

__all__ = ["INGEST_HANDLERS", "OAUTH_HANDLERS", "NexusProvider"]
