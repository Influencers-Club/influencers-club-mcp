"""Creator content endpoints of the Influencers.club API: recent posts and the
details of one post. Reached as ``client.content``. Methods return the API's JSON
body unchanged."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Optional

from .api_paths import ROOT

if TYPE_CHECKING:
    from .api_client import InfluencersApiClient

CONTENT = f"{ROOT}/creators/content/"


class ContentApi:
    """Content operations, sent through the client that owns this object."""

    def __init__(self, client: InfluencersApiClient) -> None:
        self._client = client

    async def posts(
        self, platform: str, handle: str, *, count: Optional[int] = None, pagination_token: Optional[str] = None
    ) -> Any:
        """POST /creators/content/posts/ - one page of a creator's recent posts."""
        body: dict[str, Any] = {"platform": platform, "handle": handle}
        if count is not None:
            body["count"] = count
        if pagination_token:
            body["pagination_token"] = pagination_token
        return await self._client.post(f"{CONTENT}posts/", body)

    async def post_details(
        self, platform: str, post_id: str, content_type: str, *, pagination_token: Optional[str] = None
    ) -> Any:
        """POST /creators/content/details/ - data, comments, transcript or audio of one post."""
        body: dict[str, Any] = {"platform": platform, "post_id": post_id, "content_type": content_type}
        if pagination_token:
            body["pagination_token"] = pagination_token
        return await self._client.post(f"{CONTENT}details/", body)
