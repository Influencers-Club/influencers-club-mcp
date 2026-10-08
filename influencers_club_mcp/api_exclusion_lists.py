"""Exclusion-list endpoints of the Influencers.club API.

One method per operation of ``/public/v1/discovery/exclusion-lists/``, reached as
``client.exclusion_lists``. A specific list is addressed by its id, a platform's
default list by platform. Every call is free and returns the API's JSON body
unchanged. Names and handles are sent as given; the id and the platform become
part of the address, so those two are checked here.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .api_client import InfluencersApiClient

ROOT = "/public/v1/discovery/exclusion-lists/"
# A platform is one path segment: no slash, dot, query or fragment can get in.
_PLATFORM = re.compile(r"[a-z0-9_-]+")


def _list_path(list_id: int) -> str:
    """Route of a specific list."""
    if isinstance(list_id, bool) or not isinstance(list_id, int) or list_id < 1:
        raise ValueError("list_id must be a positive integer")
    return f"{ROOT}{list_id}/"


def _default_path(platform: str) -> str:
    """Route of a platform's default list."""
    if not isinstance(platform, str) or not _PLATFORM.fullmatch(platform):
        raise ValueError(f"Invalid platform {platform!r}")
    return f"{ROOT}default/{platform}/"


def _page(offset: int, limit: int) -> dict[str, str]:
    """Query parameters of one page of handles."""
    return {"offset": str(offset), "limit": str(limit)}


class ExclusionListsApi:
    """The exclusion-list operations, sent through the client that owns this object."""

    def __init__(self, client: InfluencersApiClient) -> None:
        self._client = client

    # ── lists ────────────────────────────────────────────────────────────

    async def list_all(self) -> Any:
        """Every list of the team, across platforms: a JSON array of list objects."""
        return await self._client.get(ROOT)

    async def create(self, name: str, platform: str) -> Any:
        """Create a specific list and return it."""
        return await self._client.post(ROOT, {"name": name, "platform": platform})

    async def get(self, list_id: int) -> Any:
        """One specific list."""
        return await self._client.get(_list_path(list_id))

    async def get_default(self, platform: str) -> Any:
        """A platform's default list. The API creates it, empty, on first use."""
        return await self._client.get(_default_path(platform))

    async def rename(self, list_id: int, name: str) -> Any:
        """Rename a specific list and return it."""
        return await self._client.patch(_list_path(list_id), {"name": name})

    async def delete(self, list_id: int) -> None:
        """Delete a specific list. The API answers 204 with no body."""
        await self._client.delete(_list_path(list_id))

    # ── handles ──────────────────────────────────────────────────────────

    async def get_handles(self, list_id: int, offset: int = 0, limit: int = 1000) -> Any:
        """One page of a specific list's handles: {total, offset, limit, handles}."""
        return await self._client.get(_list_path(list_id) + "entries/", params=_page(offset, limit))

    async def get_default_handles(self, platform: str, offset: int = 0, limit: int = 1000) -> Any:
        """One page of a default list's handles: {total, offset, limit, handles}."""
        return await self._client.get(_default_path(platform) + "entries/", params=_page(offset, limit))

    async def add_handles(self, list_id: int, handles: list[str]) -> Any:
        """Add handles to a specific list and return the updated list."""
        return await self._client.post(_list_path(list_id) + "entries/", {"handles": handles})

    async def add_default_handles(self, platform: str, handles: list[str]) -> Any:
        """Add handles to a default list and return the updated list."""
        return await self._client.post(_default_path(platform) + "entries/", {"handles": handles})

    async def remove_handles(self, list_id: int, handles: list[str]) -> Any:
        """Remove handles from a specific list (DELETE with a body) and return the updated list."""
        return await self._client.delete(_list_path(list_id) + "entries/", {"handles": handles})

    async def remove_default_handles(self, platform: str, handles: list[str]) -> Any:
        """Remove handles from a default list (DELETE with a body) and return the updated list."""
        return await self._client.delete(_default_path(platform) + "entries/", {"handles": handles})
