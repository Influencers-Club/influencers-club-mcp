"""Single-creator enrichment endpoints of the Influencers.club API. Reached as
``client.enrichment``. Methods return the API's JSON body unchanged."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .api_paths import ROOT

if TYPE_CHECKING:
    from .api_client import InfluencersApiClient

CREATORS = f"{ROOT}/creators/"


class EnrichmentApi:
    """Enrichment operations, sent through the client that owns this object."""

    def __init__(self, client: InfluencersApiClient) -> None:
        self._client = client

    async def connected_socials(self, platform: str, handle: str) -> Any:
        """POST /creators/socials/ - the creator's accounts on other platforms."""
        return await self._client.post(f"{CREATORS}socials/", {"platform": platform, "handle": handle})

    async def by_handle_full(
        self, handle: str, platform: str, *, email_required: str, include_lookalikes: bool, include_audience_data: bool
    ) -> Any:
        """POST /creators/enrich/handle/full/ - the full profile of one creator."""
        body = {
            "handle": handle,
            "platform": platform,
            "email_required": email_required,
            "include_lookalikes": include_lookalikes,
            "include_audience_data": include_audience_data,
        }
        return await self._client.post(f"{CREATORS}enrich/handle/full/", body)

    async def by_handle_raw(self, handle: str, platform: str) -> Any:
        """POST /creators/enrich/handle/raw/ - the basic profile of one creator."""
        return await self._client.post(f"{CREATORS}enrich/handle/raw/", {"handle": handle, "platform": platform})

    async def by_email(self, email: str) -> Any:
        """POST /creators/enrich/email/ - the creator behind one email address."""
        return await self._client.post(f"{CREATORS}enrich/email/", {"email": email})
