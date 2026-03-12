"""
Influencers Club MCP Server

MCP server exposing the Influencers Club public API for creator enrichment,
discovery, batch operations, content data, and account management.
"""

import os
import re
import sys
import json
from typing import Annotated, Any, Literal

from pydantic import Field

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations

BASE_URL = "https://api-dashboard.influencers.club"

mcp = FastMCP(
    "influencers-club",
    instructions=(
        "MCP server for the Influencers Club API - creator enrichment, discovery, content, and batch operations.\n\n"
        "IMPORTANT: Do NOT guess or invent parameter names. If a tool's schema has not been loaded yet, "
        "use tool_search to load the correct parameter names BEFORE calling the tool. "
        "Never fabricate parameters like 'niche', 'max_results', or 'query' — they do not exist. "
        "Always use the exact parameter names from the loaded tool schema.\n\n"
        "Key tools:\n"
        "- discover_creators: Use 'ai_search' for niche/topic queries (e.g. 'retro videogames'). "
        "Pass the user's exact words as-is — do NOT add synonyms, expand, or rephrase the query. "
        "Only use 'hashtags' or 'keywords_in_bio' when the user explicitly specifies them.\n"
        "- enrich_by_email: Use for email lookups. Parameter is 'email'. Use tier='basic' (default) or tier='advanced'.\n"
        "- enrich_by_handle: Use for handle lookups. Parameters are 'handle' and 'platform'.\n"
        "- manage_batch: Use action='status' to check, action='results' to download, action='resume' to restart."
    ),
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


# ─── Input Validation ─────────────────────────────────────────────────────────

_SAFE_PATH_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
MAX_CSV_BYTES = 10 * 1024 * 1024
MAX_CSV_ROWS = 10_000

DISCOVERY_PLATFORMS = {"instagram", "youtube", "tiktok", "twitch", "twitter", "onlyfans"}
ENRICH_PLATFORMS = {"instagram", "youtube", "tiktok", "onlyfans", "twitter", "snapchat", "discord", "pinterest", "facebook", "linkedin", "twitch"}
CONTENT_PLATFORMS = {"instagram", "tiktok", "youtube"}
OVERLAP_PLATFORMS = {"instagram", "tiktok", "youtube"}


def _validate_handle(value: str) -> str:
    cleaned = value.lstrip("@").strip()
    if not cleaned or len(cleaned) > 500:
        return ""
    if "\x00" in cleaned or "\n" in cleaned:
        return ""
    return cleaned


def _validate_email(value: str) -> str:
    value = value.strip()
    if not value or len(value) > 320 or not _EMAIL_RE.match(value):
        return ""
    return value


def _validate_path_param(value: str) -> str:
    if not value or not _SAFE_PATH_RE.match(value):
        return ""
    return value


def _validate_csv(content: str) -> str | None:
    """Returns error message or None if valid."""
    if len(content.encode()) > MAX_CSV_BYTES:
        return "CSV exceeds 10 MB limit"
    if "\x00" in content:
        return "CSV contains binary/null bytes"
    lines = content.strip().splitlines()
    if not lines:
        return "CSV is empty"
    header = lines[0].strip().lower()
    if header not in ("handle", "email"):
        return "CSV header must be 'handle' or 'email'"
    if len(lines) - 1 > MAX_CSV_ROWS:
        return f"CSV exceeds {MAX_CSV_ROWS} row limit"
    return None


def _sanitize_error(err: Any) -> Any:
    if isinstance(err, str):
        return re.sub(r"Bearer\s+\S+", "Bearer [REDACTED]", err)
    if isinstance(err, dict):
        return {k: _sanitize_error(v) for k, v in err.items()}
    return err


# ─── API Helpers ──────────────────────────────────────────────────────────────


async def _api_get(path: str, params: dict[str, Any] | None = None) -> Any:
    print(f"[MCP] GET {path} params={params}", file=sys.stderr)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.get(f"{BASE_URL}{path}", headers=_headers(), params=params)
        print(f"[MCP] GET {path} → {resp.status_code}", file=sys.stderr)
        if resp.status_code >= 400:
            try:
                err = _sanitize_error(resp.json())
            except Exception:
                err = _sanitize_error(resp.text)
            return {"error": err, "status_code": resp.status_code}
        return resp.json()


async def _api_post(path: str, body: dict[str, Any]) -> Any:
    print(f"[MCP] POST {path} body={json.dumps(body, default=str)[:500]}", file=sys.stderr)
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{BASE_URL}{path}", headers=_headers(), json=body)
        print(f"[MCP] POST {path} → {resp.status_code}", file=sys.stderr)
        if resp.status_code >= 400:
            try:
                err = _sanitize_error(resp.json())
            except Exception:
                err = _sanitize_error(resp.text)
            return {"error": err, "status_code": resp.status_code}
        return resp.json()


# ─── Creator Discovery ────────────────────────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(title="Discover Creators", readOnlyHint=True, destructiveHint=False))
async def discover_creators(
    platform: Literal["instagram", "youtube", "tiktok", "twitch", "twitter", "onlyfans"],
    limit: Annotated[int, Field(ge=1, le=100)] = 10,
    page: Annotated[int, Field(ge=0)] = 0,
    ai_search: str | None = None,
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

    Use ai_search for niche/topic queries (e.g. "retro videogames", "vegan cooking").
    Only use hashtags or keywords_in_bio when the user explicitly specifies them.

    Platforms: instagram, youtube, tiktok, twitch, twitter, onlyfans.
    Returns paginated list of creator profiles with follower counts and engagement rates.
    Credits: 0.01 per creator returned. No charge if 0 results.

    Args:
        platform: Platform to search on (instagram, youtube, tiktok, twitch, twitter, onlyfans).
        limit: Number of results per page (1-100, default 10).
        page: Page number (0-indexed, default 0).
        ai_search: Natural language search for niche/topic-based discovery. Use this for ANY topic or niche query. The API uses AI to find matching creators. Pass the user's exact words — do not add synonyms or rephrase.
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
    # Pre-flight checks
    if platform not in DISCOVERY_PLATFORMS:
        return f"Error: invalid platform '{platform}'. Must be one of: {', '.join(sorted(DISCOVERY_PLATFORMS))}."
    if not 1 <= limit <= 100:
        return "Error: limit must be between 1 and 100."
    if page < 0:
        return "Error: page must be 0 or greater."

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
    if ai_search:
        filters["ai_search"] = ai_search

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
    # Pre-flight checks
    if platform not in DISCOVERY_PLATFORMS:
        return f"Error: invalid platform '{platform}'. Must be one of: {', '.join(sorted(DISCOVERY_PLATFORMS))}."
    if filter_key not in ("url", "username", "id"):
        return "Error: filter_key must be 'url', 'username', or 'id'."
    if not filter_value or not filter_value.strip():
        return "Error: filter_value is required. Please provide a username, URL, or platform ID."
    if not 1 <= limit <= 100:
        return "Error: limit must be between 1 and 100."

    body: dict[str, Any] = {
        "platform": platform,
        "filter_key": filter_key,
        "filter_value": filter_value.lstrip("@").strip(),
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
    # Pre-flight checks
    if platform not in OVERLAP_PLATFORMS:
        return f"Error: invalid platform '{platform}'. Audience overlap supports: {', '.join(sorted(OVERLAP_PLATFORMS))}."
    creators = [c.lstrip("@").strip() for c in creators if c and c.strip()]
    if len(creators) < 2:
        return "Error: audience_overlap requires at least 2 creator usernames. Please provide 2-10 creators."
    if len(creators) > 10:
        return "Error: audience_overlap supports a maximum of 10 creators."

    result = await _api_post("/public/v1/creators/audience/overlap/", {
        "platform": platform,
        "creators": creators,
    })
    return json.dumps(result, indent=2)


# ─── Discovery Reference Data ────────────────────────────────────────────────

_CLASSIFIER_ENDPOINTS = {
    "languages": "/public/v1/discovery/classifier/languages/",
    "brands": "/public/v1/discovery/classifier/brands/",
    "youtube_topics": "/public/v1/discovery/classifier/yt-topics/",
    "twitch_games": "/public/v1/discovery/classifier/games/",
    "audience_brand_categories": "/public/v1/discovery/classifier/audience-brand-categories/",
    "audience_brand_names": "/public/v1/discovery/classifier/audience-brand-names/",
    "audience_interests": "/public/v1/discovery/classifier/audience-interests/",
    "audience_locations": "/public/v1/discovery/classifier/audience-locations/",
}


@mcp.tool(annotations=ToolAnnotations(title="Get Discovery Options", readOnlyHint=True, destructiveHint=False))
async def get_discovery_options(
    data_type: Literal["languages", "locations", "brands", "youtube_topics", "twitch_games", "audience_brand_categories", "audience_brand_names", "audience_interests", "audience_locations"],
    platform: Literal["instagram", "youtube", "tiktok", "twitch", "twitter", "onlyfans"] | None = None,
    search: str | None = None,
    offset: Annotated[int, Field(ge=0)] | None = None,
) -> str:
    """Fetch available filter options for creator discovery.

    Returns reference data (languages, locations, brands, topics, audience filters) used
    as filter values in discover_creators. No credits consumed.

    Args:
        data_type: Type of reference data to fetch.
        platform: Required only for "locations". Platform to get locations for.
        search: Optional search string (only for audience_* types).
        offset: Optional pagination offset (only for audience_* types).
    """
    if data_type == "locations":
        if not platform:
            return "Error: platform is required for locations. Please specify instagram, youtube, tiktok, etc."
        if platform not in DISCOVERY_PLATFORMS:
            return f"Error: invalid platform '{platform}'. Must be one of: {', '.join(sorted(DISCOVERY_PLATFORMS))}."
        result = await _api_get(f"/public/v1/discovery/classifier/locations/{platform}/")
        return json.dumps(result, indent=2)

    endpoint = _CLASSIFIER_ENDPOINTS.get(data_type)
    if not endpoint:
        return f"Error: invalid data_type '{data_type}'."

    params: dict[str, Any] = {}
    if search and data_type.startswith("audience_"):
        params["search"] = search
    if offset is not None and data_type.startswith("audience_"):
        params["offset"] = offset

    result = await _api_get(endpoint, params or None)
    return json.dumps(result, indent=2)


# ─── Enrichment ───────────────────────────────────────────────────────────────


@mcp.tool(annotations=ToolAnnotations(title="Enrich by Email", readOnlyHint=True, destructiveHint=False))
async def enrich_by_email(
    email: str,
    tier: Literal["basic", "advanced"] = "basic",
    exclude_platforms: list[str] | None = None,
    min_followers: int | None = None,
) -> str:
    """Look up a creator's social profiles using their email address.

    tier="basic" (0.1 credits): Essential profile info, social presence, contact details.
    tier="advanced" (2 credits): Full cross-platform data, engagement, brand partnerships.

    Args:
        email: The creator's email address.
        tier: "basic" for quick lookup (default), "advanced" for full cross-platform data.
        exclude_platforms: Platforms to exclude (advanced only, e.g. ["tiktok", "youtube"]).
        min_followers: Min followers threshold (advanced only).
    """
    email = _validate_email(email)
    if not email:
        return "Error: invalid email format. Please provide a valid email address."

    if tier == "advanced":
        body: dict[str, Any] = {"email": email}
        if exclude_platforms:
            body["exclude_platforms"] = exclude_platforms
        if min_followers is not None:
            body["min_followers"] = min_followers
        result = await _api_post("/public/v1/creators/enrich/email/advanced/", body)
    else:
        result = await _api_post("/public/v1/creators/enrich/email/", {"email": email})

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
    handle = _validate_handle(handle)
    if not handle:
        return "Error: invalid handle. Please provide a valid creator username (without @)."
    if platform not in ENRICH_PLATFORMS:
        return f"Error: invalid platform '{platform}'. Must be one of: {', '.join(sorted(ENRICH_PLATFORMS))}."
    result = await _api_post("/public/v1/creators/enrich/handle/full/", {
        "handle": handle,
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
    handle = _validate_handle(handle)
    if not handle:
        return "Error: invalid handle. Please provide a valid creator username (without @)."
    if platform not in ENRICH_PLATFORMS:
        return f"Error: invalid platform '{platform}'. Must be one of: {', '.join(sorted(ENRICH_PLATFORMS))}."
    result = await _api_post("/public/v1/creators/enrich/handle/raw/", {
        "handle": handle,
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
    handle = _validate_handle(handle)
    if not handle:
        return "Error: invalid handle. Please provide a valid creator username (without @)."
    if platform not in ENRICH_PLATFORMS:
        return f"Error: invalid platform '{platform}'. Must be one of: {', '.join(sorted(ENRICH_PLATFORMS))}."
    result = await _api_post("/public/v1/creators/socials/", {
        "handle": handle,
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
    # Pre-flight checks
    csv_err = _validate_csv(csv_content)
    if csv_err:
        return f"Error: {csv_err}."
    if enrichment_mode not in ("raw", "full", "basic", "advanced"):
        return "Error: enrichment_mode must be 'raw', 'full', 'basic', or 'advanced'."
    if enrichment_mode in ("raw", "full") and not platform:
        return "Error: platform is required for handle-based batch enrichment. Please specify instagram, youtube, tiktok, etc."

    print(f"[MCP] POST /public/v1/enrichment/batch/ mode={enrichment_mode} platform={platform}", file=sys.stderr)
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


@mcp.tool(annotations=ToolAnnotations(title="Manage Batch", readOnlyHint=False, destructiveHint=False))
async def manage_batch(
    batch_id: str,
    action: Literal["status", "results", "resume"] = "status",
    format: Literal["csv", "json"] = "csv",
) -> str:
    """Manage a batch enrichment job: check status, download results, or resume.

    Args:
        batch_id: The batch_id returned by create_batch_enrichment.
        action: "status" to check progress, "results" to download (only when finished), "resume" to restart a paused batch.
        format: Output format for results - "csv" (default) or "json". Only used with action="results".
    """
    batch_id = _validate_path_param(batch_id)
    if not batch_id:
        return "Error: invalid batch_id. Must be alphanumeric with hyphens/underscores only."
    if action not in ("status", "results", "resume"):
        return "Error: action must be 'status', 'results', or 'resume'."

    if action == "status":
        result = await _api_get(f"/public/v1/enrichment/batch/{batch_id}/status/")
        return json.dumps(result, indent=2)

    if action == "resume":
        result = await _api_post(f"/public/v1/enrichment/batch/{batch_id}/resume/", {})
        return json.dumps(result, indent=2)

    # action == "results"
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
    handle = _validate_handle(handle)
    if not handle:
        return "Error: invalid handle. Please provide a valid creator username (without @)."
    if platform not in CONTENT_PLATFORMS:
        return f"Error: invalid platform '{platform}'. Content posts supports: {', '.join(sorted(CONTENT_PLATFORMS))}."

    body: dict[str, Any] = {
        "platform": platform,
        "handle": handle,
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
    # Pre-flight checks
    if not post_id or not post_id.strip():
        return "Error: post_id is required. Please provide the platform-specific post ID."
    if platform not in CONTENT_PLATFORMS:
        return f"Error: invalid platform '{platform}'. Post details supports: {', '.join(sorted(CONTENT_PLATFORMS))}."
    if content_type not in ("data", "comments", "transcript", "audio"):
        return "Error: content_type must be 'data', 'comments', 'transcript', or 'audio'."

    body: dict[str, Any] = {
        "platform": platform,
        "content_type": content_type,
        "post_id": post_id.strip(),
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
