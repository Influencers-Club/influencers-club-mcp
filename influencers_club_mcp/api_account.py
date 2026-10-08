"""Account endpoints of the Influencers.club API. Reached as ``client.account``."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .api_paths import ROOT

if TYPE_CHECKING:
    from .api_client import InfluencersApiClient


class AccountApi:
    """Account operations, sent through the client that owns this object."""

    def __init__(self, client: InfluencersApiClient) -> None:
        self._client = client

    async def credits(self) -> Any:
        """GET /accounts/credits/ - the credit balance and usage."""
        return await self._client.get(f"{ROOT}/accounts/credits/")
