"""
Influencers Club MCP Server

MCP server exposing the Influencers Club public API for creator enrichment,
discovery, batch operations, content data, and account management.
"""

import os
import json
from typing import Annotated, Any, Literal

from pydantic import Field

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

BASE_URL = "https://api-dashboard.influencers.club"

mcp = FastMCP(
    "influencers-club",
    instructions="MCP server for the Influencers Club API - creator enrichment, discovery, content, and batch operations",
)


def _get_api_key() -> str:
    key = os.environ.get("INFLUENCERS_CLUB_API_KEY")
    if not key:
        raise ValueError("INFLUENCERS_CLUB_API_KEY environment variable is required")
    return key


def _auth_header() -> str:
    key = _get_api_key()
    return key if key.startswith("Bearer ") else f"Bearer {key}"

def _headers() -> dict[str, str]:
    return {
        "Authorization": _auth_header(),
        "Content-Type": "application/json",
    }


async def _api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE_URL}{path}", headers=_headers(), params=params)
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            return {"error": err, "status_code": resp.status_code}
        return resp.json()


async def _api_post(path: str, body: dict[str, Any]) -> Any:
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{BASE_URL}{path}", headers=_headers(), json=body)
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            return {"error": err, "status_code": resp.status_code}
        return resp.json()


# ─── Creator Discovery ────────────────────────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(title="Discover Creators", readOnlyHint=True, destructiveHint=False))
async def discover_creators(
    platform: Literal["instagram", "youtube", "tiktok", "twitch", "twitter", "onlyfans"],
    limit: Annotated[int, Field(ge=1, le=100)] = 10,
    page: Annotated[int, Field(ge=0)] = 0,
    sort_by: Literal["relevancy", "followers", "engagement"] | None = None,
    sort_order: Literal["asc", "desc"] = "desc",
    location: list[str] | None = None,
    gender: Literal["male", "female"] | None = None,
    profile_language: list[str] | None = None,
    min_followers: Annotated[int, Field(ge=0)] | None = None,
    max_followers: Annotated[int, Field(ge=0)] | None = None,
    min_engagement_percent: Annotated[float, Field(ge=0, le=100)] | None = None,
    max_engagement_percent: Annotated[float, Field(ge=0, le=100)] | None = None,
    keywords_in_bio: list[str] | None = None,
    exclude_keywords_in_bio: list[str] | None = None,
    hashtags: list[str] | None = None,
    brands: list[str] | None = None,
    has_done_brand_deals: bool | None = None,
    is_verified: bool | None = None,
    has_link_in_bio: bool | None = None,
    exclude_private_profile: bool = True,
    last_post: str | None = None,
) -> str:
    """Search and filter the influencers.club creator database.

    Platforms: instagram, youtube, tiktok, twitch, twitter, onlyfans.
    Returns paginated list of creator profiles with follower counts and engagement rates.
    Credits: 0.01 per creator returned. No charge if 0 results.

    Args:
        platform: Platform to search on (instagram, youtube, tiktok, twitch, twitter, onlyfans).
        limit: Number of results per page (1-100, default 10).
        page: Page number (0-indexed, default 0).
        sort_by: Sort results by "relevancy", "followers", or "engagement".
        sort_order: Sort direction "asc" or "desc" (default "desc").
        location: Filter by location codes.
        gender: Filter by gender e.g. "male", "female".
        profile_language: Filter by content language codes e.g. ["en", "es"].
        min_followers: Minimum follower count.
        max_followers: Maximum follower count.
        min_engagement_percent: Minimum engagement rate as a percentage.
        max_engagement_percent: Maximum engagement rate as a percentage.
        keywords_in_bio: Creators whose bio contains these keywords.
        exclude_keywords_in_bio: Exclude creators whose bio contains these keywords.
        hashtags: Creators who use these hashtags.
        brands: Creators who have done brand deals with these brands.
        has_done_brand_deals: Filter to creators who have done brand deals.
        is_verified: Filter to verified accounts only.
        has_link_in_bio: Filter to creators with a link in bio.
        exclude_private_profile: Exclude private profiles (default True).
        last_post: Filter by recency of last post e.g. "30d", "90d".
    """
    body: dict[str, Any] = {
        "platform": platform,
        "paging": {"limit": limit, "page": page},
    }

    if sort_by:
        body["sort"] = {"sort_by": sort_by, "sort_order": sort_order}

    filters: dict[str, Any] = {}
    if location:
        filters["location"] = location
    if gender:
        filters["gender"] = gender
    if profile_language:
        filters["profile_language"] = profile_language
    if min_followers is not None or max_followers is not None:
        followers: dict[str, Any] = {}
        if min_followers is not None:
            followers["min"] = min_followers
        if max_followers is not None:
            followers["max"] = max_followers
        filters["number_of_followers"] = followers
    if min_engagement_percent is not None or max_engagement_percent is not None:
        engagement: dict[str, Any] = {}
        if min_engagement_percent is not None:
            engagement["min"] = min_engagement_percent
        if max_engagement_percent is not None:
            engagement["max"] = max_engagement_percent
        filters["engagement_percent"] = engagement
    if keywords_in_bio:
        filters["keywords_in_bio"] = keywords_in_bio
    if exclude_keywords_in_bio:
        filters["exclude_keywords_in_bio"] = exclude_keywords_in_bio
    if hashtags:
        filters["hashtags"] = hashtags
    if brands:
        filters["brands"] = brands
    if has_done_brand_deals is not None:
        filters["has_done_brand_deals"] = has_done_brand_deals
    if is_verified is not None:
        filters["is_verified"] = is_verified
    if has_link_in_bio is not None:
        filters["has_link_in_bio"] = has_link_in_bio
    if exclude_private_profile is not None:
        filters["exclude_private_profile"] = exclude_private_profile
    if last_post:
        filters["last_post"] = last_post

    if filters:
        body["filters"] = filters

    result = await _api_post("/public/v1/discovery/", body)
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Find Similar Creators", readOnlyHint=True, destructiveHint=False))
async def find_similar_creators(
    platform: Literal["instagram", "youtube", "tiktok", "twitch", "twitter", "onlyfans"],
    filter_key: Literal["url", "username", "id"],
    filter_value: str,
    limit: Annotated[int, Field(ge=1, le=100)] = 10,
    page: Annotated[int, Field(ge=0)] = 0,
    min_followers: Annotated[int, Field(ge=0)] | None = None,
    max_followers: Annotated[int, Field(ge=0)] | None = None,
    location: list[str] | None = None,
    is_verified: bool | None = None,
    has_done_brand_deals: bool | None = None,
    keywords_in_bio: list[str] | None = None,
) -> str:
    """Find creators similar to a given seed creator.

    Ideal for scaling a campaign after finding one strong creator fit.
    Credits: 0.01 per creator returned. No charge if 0 results.

    Args:
        platform: Platform of the seed creator (instagram, youtube, tiktok, twitch, twitter, onlyfans).
        filter_key: How to identify the seed creator: "url", "username", or "id".
        filter_value: The profile URL, username, or platform ID of the seed creator.
        limit: Number of results per page (1-100, default 10).
        page: Page number (0-indexed, default 0).
        min_followers: Minimum follower count.
        max_followers: Maximum follower count.
        location: Filter by location codes.
        is_verified: Filter to verified accounts only.
        has_done_brand_deals: Filter to creators with brand deals.
        keywords_in_bio: Filter by keywords in bio.
    """
    body: dict[str, Any] = {
        "platform": platform,
        "filter_key": filter_key,
        "filter_value": filter_value,
        "paging": {"limit": limit, "page": page},
    }

    filters: dict[str, Any] = {}
    if min_followers is not None or max_followers is not None:
        followers: dict[str, Any] = {}
        if min_followers is not None:
            followers["min"] = min_followers
        if max_followers is not None:
            followers["max"] = max_followers
        filters["number_of_followers"] = followers
    if location:
        filters["location"] = location
    if is_verified is not None:
        filters["is_verified"] = is_verified
    if has_done_brand_deals is not None:
        filters["has_done_brand_deals"] = has_done_brand_deals
    if keywords_in_bio:
        filters["keywords_in_bio"] = keywords_in_bio

    if filters:
        body["filters"] = filters

    result = await _api_post("/public/v1/discovery/creators/similar/", body)
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Audience Overlap", readOnlyHint=True, destructiveHint=False))
async def audience_overlap(
    platform: Literal["instagram", "tiktok", "youtube"],
    creators: list[str],
) -> str:
    """Compare audience overlap between 2-10 creators on a given platform.

    Returns per-creator overlap percentages, unique audience data, and total followers.
    Useful for campaign planning to avoid audience duplication.
    Credits: 1 per request.

    Args:
        platform: Platform to compare on (instagram, tiktok, youtube).
        creators: List of 2-10 creator usernames or URLs to compare.
    """
    result = await _api_post("/public/v1/creators/audience/overlap/", {
        "platform": platform,
        "creators": creators,
    })
    return json.dumps(result, indent=2)


# ─── Discovery Reference Data ────────────────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(title="Get Languages", readOnlyHint=True, destructiveHint=False))
async def get_languages() -> str:
    """Fetch available languages for creator discovery filtering.

    Returns ISO 639-1 language codes supported by the discovery API.
    No credits consumed.
    """
    result = await _api_get("/public/v1/discovery/classifier/languages/")
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Get Locations", readOnlyHint=True, destructiveHint=False))
async def get_locations(platform: Literal["instagram", "youtube", "tiktok", "twitch", "twitter", "onlyfans"]) -> str:
    """Fetch available locations for creator discovery filtering.

    Returns country and city options for location-based discovery.
    No credits consumed.

    Args:
        platform: Platform to get locations for (instagram, youtube, tiktok, twitch, twitter, onlyfans).
    """
    result = await _api_get(f"/public/v1/discovery/classifier/locations/{platform}/")
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Get Brands", readOnlyHint=True, destructiveHint=False))
async def get_brands() -> str:
    """Fetch available brand identifiers for creator discovery filtering.

    Returns list of brands that can be used to filter creators by brand partnerships.
    No credits consumed.
    """
    result = await _api_get("/public/v1/discovery/classifier/brands/")
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Get YouTube Topics", readOnlyHint=True, destructiveHint=False))
async def get_youtube_topics() -> str:
    """Fetch available YouTube topics for creator discovery filtering.

    Returns list of supported YouTube topic categories.
    No credits consumed.
    """
    result = await _api_get("/public/v1/discovery/classifier/yt-topics/")
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Get Twitch Games", readOnlyHint=True, destructiveHint=False))
async def get_twitch_games() -> str:
    """Fetch available Twitch games for creator discovery filtering.

    Returns list of supported Twitch games.
    No credits consumed.
    """
    result = await _api_get("/public/v1/discovery/classifier/games/")
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Get Audience Brand Categories", readOnlyHint=True, destructiveHint=False))
async def get_audience_brand_categories(
    search: str | None = None,
    offset: Annotated[int, Field(ge=0)] | None = None,
) -> str:
    """Fetch available audience brand categories for discovery filtering.

    Returns brand categories that can be used to filter creators by their audience's brand affinities.
    No credits consumed.

    Args:
        search: Optional search string to filter results.
        offset: Optional pagination offset.
    """
    params: dict[str, Any] = {}
    if search:
        params["search"] = search
    if offset is not None:
        params["offset"] = offset
    result = await _api_get("/public/v1/discovery/classifier/audience-brand-categories/", params or None)
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Get Audience Brand Names", readOnlyHint=True, destructiveHint=False))
async def get_audience_brand_names(
    search: str | None = None,
    offset: Annotated[int, Field(ge=0)] | None = None,
) -> str:
    """Fetch available audience brand names for discovery filtering.

    Returns brand names that can be used to filter creators by their audience's brand preferences.
    No credits consumed.

    Args:
        search: Optional search string to filter results.
        offset: Optional pagination offset.
    """
    params: dict[str, Any] = {}
    if search:
        params["search"] = search
    if offset is not None:
        params["offset"] = offset
    result = await _api_get("/public/v1/discovery/classifier/audience-brand-names/", params or None)
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Get Audience Interests", readOnlyHint=True, destructiveHint=False))
async def get_audience_interests(
    search: str | None = None,
    offset: Annotated[int, Field(ge=0)] | None = None,
) -> str:
    """Fetch available audience interests for discovery filtering.

    Returns interest categories that can be used to filter creators by their audience's interests.
    No credits consumed.

    Args:
        search: Optional search string to filter results.
        offset: Optional pagination offset.
    """
    params: dict[str, Any] = {}
    if search:
        params["search"] = search
    if offset is not None:
        params["offset"] = offset
    result = await _api_get("/public/v1/discovery/classifier/audience-interests/", params or None)
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Get Audience Locations", readOnlyHint=True, destructiveHint=False))
async def get_audience_locations(
    search: str | None = None,
    offset: Annotated[int, Field(ge=0)] | None = None,
) -> str:
    """Fetch available audience locations for discovery filtering.

    Returns location options that can be used to filter creators by their audience's geographic distribution.
    No credits consumed.

    Args:
        search: Optional search string to filter results.
        offset: Optional pagination offset.
    """
    params: dict[str, Any] = {}
    if search:
        params["search"] = search
    if offset is not None:
        params["offset"] = offset
    result = await _api_get("/public/v1/discovery/classifier/audience-locations/", params or None)
    return json.dumps(result, indent=2)


# ─── Enrichment ───────────────────────────────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(title="Enrich by Email (Basic)", readOnlyHint=True, destructiveHint=False))
async def enrich_by_email_basic(email: str) -> str:
    """Look up a creator's social profiles using their email address (basic tier).

    Returns essential profile info: social presence across platforms, contact details,
    and platform account identifiers.
    Credits: 0.1 per successful request.

    Args:
        email: The creator's email address.
    """
    result = await _api_post("/public/v1/creators/enrich/email/", {"email": email})
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Enrich by Email (Advanced)", readOnlyHint=True, destructiveHint=False))
async def enrich_by_email_advanced(
    email: str,
    exclude_platforms: list[str] | None = None,
    min_followers: int | None = None,
) -> str:
    """Look up a creator's social profiles using their email address (advanced tier).

    Returns detailed cross-platform data: follower counts, engagement metrics,
    content analytics, monetization indicators, and brand partnership history.
    Credits: 2 per successful request.

    Args:
        email: The creator's email address.
        exclude_platforms: Platforms to exclude from the response (e.g. ["tiktok", "youtube"]).
        min_followers: Only return data for platforms where the creator has at least this many followers.
    """
    body: dict[str, Any] = {"email": email}
    if exclude_platforms:
        body["exclude_platforms"] = exclude_platforms
    if min_followers is not None:
        body["min_followers"] = min_followers
    result = await _api_post("/public/v1/creators/enrich/email/advanced/", body)
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Enrich by Handle", readOnlyHint=True, destructiveHint=False))
async def enrich_by_handle(
    handle: str,
    platform: Literal["instagram", "youtube", "tiktok", "onlyfans", "twitter", "snapchat", "discord", "pinterest", "facebook", "linkedin", "twitch"],
    email_required: Literal["must_have", "preferred"] = "preferred",
    include_lookalikes: bool = True,
    include_audience_data: bool = False,
) -> str:
    """Get a full enriched profile for a creator using their social media handle.

    Returns comprehensive data: cross-platform presence, engagement analytics,
    follower growth, content performance, monetization indicators, niche classification,
    contact email (if available), and audience demographics.
    Credits: 1 per successful request.

    Args:
        handle: The creator's handle/username (without @ symbol).
        platform: Platform (instagram, youtube, tiktok, onlyfans, twitter, snapchat, discord, pinterest, facebook, linkedin, twitch).
        email_required: "must_have" (only return if email available) or "preferred" (return regardless).
        include_lookalikes: Include lookalike creator recommendations (default True).
        include_audience_data: Include audience demographics - age, gender, location (Instagram, TikTok, YouTube only).
    """
    result = await _api_post("/public/v1/creators/enrich/handle/full/", {
        "handle": handle.lstrip("@"),
        "platform": platform,
        "email_required": email_required,
        "include_lookalikes": include_lookalikes,
        "include_audience_data": include_audience_data,
    })
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Enrich by Handle (Raw)", readOnlyHint=True, destructiveHint=False))
async def enrich_by_handle_raw(
    handle: str,
    platform: Literal["instagram", "youtube", "tiktok", "onlyfans", "twitter", "snapchat", "discord", "pinterest", "facebook", "linkedin", "twitch"],
) -> str:
    """Get raw scraper data for a creator using their social media handle.

    Returns unprocessed scraper data directly from the platform. Cheaper than full enrichment.
    Credits: 0.03 per request.

    Args:
        handle: The creator's handle/username (without @ symbol).
        platform: Platform (instagram, youtube, tiktok, onlyfans, twitter, snapchat, discord, pinterest, facebook, linkedin, twitch).
    """
    result = await _api_post("/public/v1/creators/enrich/handle/raw/", {
        "handle": handle.lstrip("@"),
        "platform": platform,
    })
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Connected Socials", readOnlyHint=True, destructiveHint=False))
async def connected_socials(
    handle: str,
    platform: Literal["instagram", "youtube", "tiktok", "onlyfans", "twitter", "snapchat", "discord", "pinterest", "facebook", "linkedin", "twitch"],
) -> str:
    """Discover verified social accounts linked to a creator across platforms.

    Returns an array of connected accounts with platform, username, and follower count.
    Useful for finding a creator's full social presence from a single handle.
    Credits: 0.5 per successful request.

    Args:
        handle: The creator's handle/username (without @ symbol).
        platform: Seed platform (instagram, youtube, tiktok, onlyfans, twitter, snapchat, discord, pinterest, facebook, linkedin, twitch).
    """
    result = await _api_post("/public/v1/creators/socials/", {
        "handle": handle.lstrip("@"),
        "platform": platform,
    })
    return json.dumps(result, indent=2)


# ─── Batch Enrichment ─────────────────────────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(title="Create Batch Enrichment", readOnlyHint=False, destructiveHint=False))
async def create_batch_enrichment(
    csv_content: str,
    enrichment_mode: Literal["raw", "full", "basic", "advanced"],
    platform: Literal["instagram", "youtube", "tiktok", "twitch", "twitter", "onlyfans"] | None = None,
    include_lookalikes: bool = False,
    include_audience_data: bool = False,
    email_required: Literal["must_have", "preferred"] | None = None,
    exclude_platforms: str | None = None,
    min_followers: Annotated[int, Field(ge=0)] | None = None,
) -> str:
    """Submit a batch enrichment job for a list of creators.

    Provide CSV content with a 'handle' or 'email' column header, one value per row.
    Use 'raw'/'full' for handle CSV; 'basic'/'advanced' for email CSV.
    Credits are deducted per successfully enriched record.

    Args:
        csv_content: CSV as a string. First line must be 'handle' or 'email' header.
        enrichment_mode: One of "raw", "full", "basic", "advanced".
        platform: Required for handle-based batches. Omit for email-based.
        include_lookalikes: Include lookalike recommendations (default False).
        include_audience_data: Include audience demographics (default False).
        email_required: "must_have" or "preferred" for handle-based enrichment.
        exclude_platforms: Comma-separated platforms to exclude for email-based enrichment.
        min_followers: Minimum follower threshold.
    """
    async with httpx.AsyncClient(timeout=60) as client:
        files = {"file": ("creators.csv", csv_content.encode(), "text/csv")}
        data: dict[str, str] = {
            "enrichment_mode": enrichment_mode,
            "include_lookalikes": str(include_lookalikes).lower(),
            "include_audience_data": str(include_audience_data).lower(),
        }
        if platform:
            data["platform"] = platform
        if email_required:
            data["email_required"] = email_required
        if exclude_platforms:
            data["exclude_platforms"] = exclude_platforms
        if min_followers is not None:
            data["min_followers"] = str(min_followers)
        resp = await client.post(
            f"{BASE_URL}/public/v1/enrichment/batch/",
            headers={"Authorization": _auth_header()},
            files=files,
            data=data,
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            return json.dumps({"error": err, "status_code": resp.status_code}, indent=2)
        return json.dumps(resp.json(), indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Get Batch Status", readOnlyHint=True, destructiveHint=False))
async def get_batch_status(batch_id: str) -> str:
    """Check the status of a batch enrichment job.

    Returns status, total/processed/success/failed row counts, credits used, and estimated completion.
    No credits consumed.

    Args:
        batch_id: The batch_id returned by create_batch_enrichment.
    """
    result = await _api_get(f"/public/v1/enrichment/batch/{batch_id}/status/")
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Get Batch Results", readOnlyHint=True, destructiveHint=False))
async def get_batch_results(
    batch_id: str,
    format: Literal["csv", "json"] = "csv",
) -> str:
    """Download results of a finished batch enrichment job.

    Only call after get_batch_status returns 'finished'.
    No credits consumed for download.

    Args:
        batch_id: The batch_id returned by create_batch_enrichment.
        format: Output format - "csv" (default) or "json".
    """
    async with httpx.AsyncClient(timeout=60) as client:
        resp = await client.get(
            f"{BASE_URL}/public/v1/enrichment/batch/{batch_id}/",
            headers={"Authorization": _auth_header()},
            params={"format": format},
        )
        if resp.status_code >= 400:
            try:
                err = resp.json()
            except Exception:
                err = resp.text
            return json.dumps({"error": err, "status_code": resp.status_code}, indent=2)
        if format == "json":
            return json.dumps(resp.json(), indent=2)
        return resp.text


@mcp.tool(annotations=ToolAnnotations(title="Resume Batch", readOnlyHint=False, destructiveHint=False))
async def resume_batch(batch_id: str) -> str:
    """Resume a paused batch enrichment job.

    Batches pause when account runs out of credits. Add credits then resume.
    No additional credits consumed for the resume call itself.

    Args:
        batch_id: The batch_id returned by create_batch_enrichment.
    """
    result = await _api_post(f"/public/v1/enrichment/batch/{batch_id}/resume/", {})
    return json.dumps(result, indent=2)


# ─── Content Data ──────────────────────────────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(title="Get Creator Posts", readOnlyHint=True, destructiveHint=False))
async def get_creator_posts(
    platform: Literal["instagram", "tiktok", "youtube"],
    handle: str,
    count: Annotated[int, Field(ge=1, le=50)] | None = None,
    pagination_token: str | None = None,
) -> str:
    """Fetch recent posts for a creator with engagement metrics.

    Returns posts with ID, URL, caption, media URLs, timestamps, and engagement data.
    Supports cursor-based pagination via next_token.
    Page sizes: Instagram (12 fixed), TikTok (default 30, max 35), YouTube (default 30, max 50).
    Credits: 0.03 per request.

    Args:
        platform: Platform to fetch posts from (instagram, tiktok, youtube).
        handle: The creator's handle/username or profile URL.
        count: Number of posts per page (platform-specific limits apply).
        pagination_token: Cursor token from previous response for next page.
    """
    body: dict[str, Any] = {
        "platform": platform,
        "handle": handle.lstrip("@"),
    }
    if count is not None:
        body["count"] = count
    if pagination_token:
        body["pagination_token"] = pagination_token
    result = await _api_post("/public/v1/creators/content/posts/", body)
    return json.dumps(result, indent=2)


@mcp.tool(annotations=ToolAnnotations(title="Get Post Details", readOnlyHint=True, destructiveHint=False))
async def get_post_details(
    platform: Literal["instagram", "tiktok", "youtube"],
    post_id: str,
    content_type: Literal["data", "comments", "transcript", "audio"] = "data",
    pagination_token: str | None = None,
) -> str:
    """Retrieve detailed data for a specific social media post.

    Supports Instagram, TikTok, and YouTube.
    Content types: "data" (metrics), "comments" (IG/TT only), "transcript" (IG/TT/YT), "audio" (IG/TT only).
    Credits: 0.03 per successful request.

    Args:
        platform: Platform the post is on (instagram, tiktok, youtube).
        post_id: The platform-specific post ID (not the URL).
        content_type: Type of content: "data", "comments", "transcript", or "audio" (default "data").
        pagination_token: Pagination token for fetching subsequent pages of comments.
    """
    body: dict[str, Any] = {
        "platform": platform,
        "content_type": content_type,
        "post_id": post_id,
    }
    if pagination_token:
        body["pagination_token"] = pagination_token
    result = await _api_post("/public/v1/creators/content/details/", body)
    return json.dumps(result, indent=2)


# ─── Account ───────────────────────────────────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(title="Check Credits", readOnlyHint=True, destructiveHint=False))
async def check_credits() -> str:
    """Check the current API credit balance for this account. No credits consumed."""
    result = await _api_get("/public/v1/accounts/credits/")
    return json.dumps(result, indent=2)
