"""Discovery endpoints of the Influencers.club API: creator search, similar
creators, audience overlap and the classifier lookups. Reached as ``client.discovery``.
Methods return the API's JSON body unchanged; filters arrive already validated."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .api_paths import ROOT, segment

if TYPE_CHECKING:
    from .api_client import InfluencersApiClient

DISCOVERY = f"{ROOT}/discovery/"
CLASSIFIER = f"{DISCOVERY}classifier/"


def _search_params(search: Optional[str], offset: Optional[int]) -> dict[str, str] | None:
    """Query parameters of a classifier lookup; None when there are none."""
    params: dict[str, str] = {}
    if search:
        params["search"] = search.strip()
    if offset is not None:
        params["offset"] = str(offset)
    return params or None


class DiscoveryApi:
    """Discovery operations, sent through the client that owns this object."""

    def __init__(self, client: InfluencersApiClient) -> None:
        self._client = client

    async def search(
        self, platform: str, filters: dict[str, Any], *, page: int, limit: int, sort_by: str, sort_order: str
    ) -> Any:
        """POST /discovery/ - one page of creators; costs credits per creator returned."""
        body = {
            "platform": platform,
            "paging": {"limit": limit, "page": page},
            "sort": {"sort_by": sort_by, "sort_order": sort_order},
            "filters": filters if filters else None,
        }
        return await self._client.post(DISCOVERY, body)

    async def similar(
        self, platform: str, filter_key: str, filter_value: str, filters: dict[str, Any], *, page: int, limit: int
    ) -> Any:
        """POST /discovery/creators/similar/ - creators similar to one reference creator."""
        body: dict[str, Any] = {
            "platform": platform,
            "filter_key": filter_key,
            "filter_value": filter_value,
            "paging": {"limit": limit, "page": page},
        }
        if filters:
            body["filters"] = filters
        return await self._client.post(f"{DISCOVERY}creators/similar/", body)

    async def audience_overlap(self, platform: str, creators: list[str]) -> Any:
        """POST /creators/audience/overlap/ - shared audience of 2-10 creators."""
        return await self._client.post(f"{ROOT}/creators/audience/overlap/", {"platform": platform, "creators": creators})

    # -- classifier lookups (free) --------------------------------------------

    async def languages(self) -> Any:
        """GET /discovery/classifier/languages/"""
        return await self._client.get(f"{CLASSIFIER}languages/")

    async def locations(self, platform: str) -> Any:
        """GET /discovery/classifier/locations/{platform}/"""
        return await self._client.get(f"{CLASSIFIER}locations/{segment(platform, 'platform')}/")

    async def brands(self, search: Optional[str] = None, offset: Optional[int] = None) -> Any:
        """GET /discovery/classifier/brands/"""
        return await self._client.get(f"{CLASSIFIER}brands/", _search_params(search, offset))

    async def youtube_topics(self) -> Any:
        """GET /discovery/classifier/yt-topics/"""
        return await self._client.get(f"{CLASSIFIER}yt-topics/")

    async def games(self) -> Any:
        """GET /discovery/classifier/games/"""
        return await self._client.get(f"{CLASSIFIER}games/")

    async def audience_brand_categories(self, search: Optional[str] = None, offset: Optional[int] = None) -> Any:
        """GET /discovery/classifier/audience-brand-categories/"""
        return await self._client.get(f"{CLASSIFIER}audience-brand-categories/", _search_params(search, offset))

    async def audience_brand_names(self, search: Optional[str] = None, offset: Optional[int] = None) -> Any:
        """GET /discovery/classifier/audience-brand-names/"""
        return await self._client.get(f"{CLASSIFIER}audience-brand-names/", _search_params(search, offset))

    async def audience_interests(self, search: Optional[str] = None, offset: Optional[int] = None) -> Any:
        """GET /discovery/classifier/audience-interests/"""
        return await self._client.get(f"{CLASSIFIER}audience-interests/", _search_params(search, offset))

    async def audience_locations(self, search: Optional[str] = None, offset: Optional[int] = None) -> Any:
        """GET /discovery/classifier/audience-locations/"""
        return await self._client.get(f"{CLASSIFIER}audience-locations/", _search_params(search, offset))
