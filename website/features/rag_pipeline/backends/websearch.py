"""PARKED: future web-search popup feature.

Spec section 9 reserves this namespace for a later web-search-backed escape hatch.
"""


class WebSearchBackend:
    async def search(self, query: str) -> str:
        raise NotImplementedError(
            "WebSearchBackend is parked for v2. See spec section 9."
        )
