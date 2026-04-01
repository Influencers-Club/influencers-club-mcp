"""
Influencers Club MCP Server

MCP server exposing the Influencers Club public API for creator enrichment,
discovery, batch operations, content data, and account management.
"""

import asyncio
import json
import os
import re
import time as _time
from datetime import datetime, timezone
from pathlib import Path
from typing import Annotated, Any, Optional

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .api_client import ApiError, InfluencersApiClient
from .csv_export import creators_to_csv

# ─── Constants ─────────────────────────────────────────────────────────
API_V1 = "/public/v1"

OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "/exports")
IMPORTS_DIR = os.environ.get("IMPORTS_DIR", "/imports")
MAX_EXPORT_PAGES = 10
CONFIG_FILE = os.path.join(os.environ.get("OUTPUT_DIR", "/exports"), ".ic_config.json")
UPLOAD_PORT = int(os.environ.get("UPLOAD_PORT", "8090"))


def _get_export_host_dir() -> str:
    """Get the host export path — from saved config file, then env var fallback."""
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE) as f:
                cfg = json.load(f)
            if cfg.get("export_host_dir"):
                return cfg["export_host_dir"]
        except (json.JSONDecodeError, OSError):
            pass
    return os.environ.get("EXPORT_HOST_DIR", "")

DISCOVERY_PLATFORMS = ("instagram", "youtube", "tiktok", "twitch", "twitter", "onlyfans")
ENRICHMENT_PLATFORMS = (*DISCOVERY_PLATFORMS, "snapchat", "discord", "pinterest", "facebook", "linkedin")
CONTENT_PLATFORMS = ("instagram", "tiktok", "youtube")
OVERLAP_PLATFORMS = ("instagram", "tiktok", "youtube")
VALID_SORT_BY = ("relevancy", "engagement_rate", "number_of_followers", "growth_rate", "cqi", "creator_quality_index")

CREDIT_COSTS = {
    "discovery": 0.01, "similar": 0.01, "overlap": 1, "socials": 0.5,
    "handle_raw": 0.03, "handle_full": 1, "email_basic": 0.05,
    "posts": 0.15, "post_detail": 0.03,
}

# ─── Initialize ────────────────────────────────────────────────────────
mcp = FastMCP(
    "influencers-club",
    instructions=(
        "MCP server for the Influencers Club API - creator enrichment, discovery, content, and batch operations.\n\n"
        "FILE HANDLING (critical — read this FIRST):\n"
        "- You CANNOT read CSV files from the user's filesystem. Do NOT use bash, cat, head, or any shell command to read files.\n"
        "- When a user drops/attaches/mentions a CSV file for enrichment, ALWAYS use the UPLOAD FLOW:\n"
        "  1. Call get_upload_url → show the URL to the user\n"
        "  2. IMMEDIATELY call wait_for_upload\n"
        "  3. The user uploads the file via browser → wait_for_upload detects it\n"
        "  4. Proceed with create_batch_enrichment using csv_file_path\n"
        "- NEVER try to read, parse, or inspect uploaded files yourself. The upload server handles everything.\n\n"
        "IMPORTANT: Do NOT guess or invent parameter names. Always use the exact parameter names from the tool schema.\n\n"
        "SORTING RULES (critical — let the API sort, never re-sort client-side):\n"
        "- sort_by options: relevancy, engagement_rate, number_of_followers, growth_rate, cqi, creator_quality_index\n"
        "- If the user asks for 'top by followers' or 'most followed' → use sort_by='number_of_followers'\n"
        "- If the user asks for 'best engagement' → use sort_by='engagement_rate'\n"
        "- If the user asks for 'fastest growing' → use sort_by='growth_rate' (only works on instagram, tiktok, youtube)\n"
        "- If the user asks for 'best quality' or 'highest quality' → use sort_by='cqi' (Creator Quality Index)\n"
        "- sort_by='number_of_followers' is NOT available on OnlyFans\n"
        "- sort_by='relevancy' only supports sort_order='desc' (asc will error)\n"
        "- ai_search CAN be combined with any sort_by — use both when the user wants a topic + specific sort\n"
        "- If sorting is not mentioned by the user, default to sort_by='relevancy'\n"
        "- NEVER re-sort or reorder results — always present them in the exact order the API returns them\n\n"
        "PAGINATION: Pages are 0-indexed (first page = 0, second page = 1, etc.)\n\n"
        "LIMIT RULES (critical — every result costs credits, never fetch more than needed):\n"
        "- Set limit to EXACTLY the number the user asks for. '1 creator' = limit=1, '3 creators' = limit=3.\n"
        "- If the user doesn't specify a number, default to limit=5 (not 10, not 50).\n"
        "- Maximum limit per request is 50. If the user wants more than 50, make multiple calls:\n"
        "  e.g. 60 creators = first call limit=50 page=0, second call limit=10 page=1.\n"
        "- Each discovery result costs 0.01 credits. Fetching 50 when user wants 1 wastes 0.49 credits.\n\n"
        "DISCOVERY RULES (critical — ask before spending credits):\n"
        "- ALWAYS ask the user which PLATFORM they want BEFORE running discover_creators. Never assume or search all platforms.\n"
        "- ALWAYS ask how many results they want BEFORE searching. Default suggestion: 5.\n"
        "- Each discovery result costs 0.01 credits. Do NOT run multiple platform searches unless explicitly asked.\n"
        "- If the user says 'find AI marketing creators', ask: 'Which platform? (Instagram, TikTok, YouTube, Twitter, Twitch, OnlyFans)'\n"
        "- Only after the user answers, run ONE discover_creators call with that platform.\n\n"
        "Key tools:\n"
        "- discover_creators: Use 'ai_search' for niche/topic queries (e.g. 'retro videogames'). "
        "Pass the user's exact words as-is — do NOT add synonyms, expand, or rephrase the query. "
        "ai_search can be combined with any sort_by value. "
        "Only use 'hashtags' or 'keywords_in_bio' when the user explicitly specifies them.\n"
        "- discover_creators_to_file: Same as discover_creators but saves results to CSV on disk. "
        "Use when the user wants to save, export, or download a list.\n"
        "- find_similar_creators: Find creators similar to a given creator. Present results in a table. Do NOT offer CSV/file export — it does not exist.\n"
        "- enrich_by_handle: Use for handle lookups. Parameters are 'handle' and 'platform'.\n"
        "- enrich_by_email: Basic email lookup (0.05 credits).\n"
        "- create_batch_enrichment: For bulk processing. CSV must have 'handle' or 'email' header, one value per line.\n\n"
        "EMAIL ENRICHMENT ROUTING (critical — choose the right method based on count):\n"
        "- 1-5 emails: Use enrich_by_email ONE BY ONE for each email. Do NOT use batch. Call the tool once per email.\n"
        "- 6-20 emails: Use create_batch_enrichment with csv_content (inline in chat). Newline-separated with 'email' header.\n"
        "- 21+ emails OR dropped/attached files: Use the UPLOAD FLOW (see below).\n"
        "- If the user says 'enrich emails' but hasn't provided any yet, just say 'Send me the emails' and wait. Do NOT ask multiple questions.\n\n"
        "BATCH RULES (critical):\n"
        "- You are a MESSENGER. Pass CSV content to the API as-is. Do NOT clean, repair, deduplicate, or filter CSVs.\n"
        "- Do NOT run bash, cat, head, wc, or ANY shell command to read, inspect, or count CSV files. You have NO filesystem access to user files.\n"
        "- When a user drops or attaches a file: ALWAYS go straight to the UPLOAD FLOW. Do NOT try to read the file first.\n"
        "- UPLOAD FLOW for 21+ emails / dropped files / attached files:\n"
        "  1. Call get_upload_url → show URL to user\n"
        "  2. IMMEDIATELY call wait_for_upload (do NOT wait for user to respond — call it right away)\n"
        "  3. wait_for_upload auto-detects the file → returns filename and host_path\n"
        "  4. Call create_batch_enrichment with csv_file_path from wait_for_upload (leave enrichment_mode empty)\n"
        "  5. Server returns mode menu → present to user → user picks\n"
        "  6. Call create_batch_enrichment AGAIN with same csv_file_path + chosen enrichment_mode\n"
        "  NEVER skip steps. NEVER pass file contents as csv_content. NEVER run scripts.\n"
        "- For email-based modes (basic): exclude_platforms and min_followers are optional extras.\n"
        "  Only ask about them if the user mentions filtering. Do NOT proactively ask about them every time.\n"
        "  Just ask for the mode. If the user volunteers filters, apply them.\n"
        "- For handle-based modes (raw/full): platform IS required — ask the user.\n"
        "- AUTOMATIC POLLING: After batch submission, IMMEDIATELY start polling get_batch_status every 35s.\n"
        "  Do NOT ask the user 'want me to keep polling?' — just keep polling automatically until finished.\n"
        "  When finished, IMMEDIATELY call download_batch_results. The entire flow after mode selection is hands-free.\n"
        "- download_batch_results: ALWAYS use format='csv'. Only call it ONCE. Report the file path and STOP.\n"
    ),
)
client = InfluencersApiClient()


# ─── Helpers ───────────────────────────────────────────────────────────
def _validate_platform(platform: str, allowed: tuple) -> str:
    p = platform.strip().lower()
    if p not in allowed:
        raise ValueError(f"Invalid platform '{p}'. Must be one of: {', '.join(allowed)}")
    return p


def _validate_ai_search(query: str) -> str:
    q = query.strip()
    if len(q) < 3 or len(q) > 150:
        raise ValueError("ai_search must be 3-150 characters")
    return q


def _validate_sort(sort_by: str, sort_order: str, platform: str) -> None:
    if sort_order not in ("asc", "desc"):
        raise ValueError(f"Invalid sort_order '{sort_order}'. Must be 'asc' or 'desc'")
    if sort_by not in VALID_SORT_BY:
        raise ValueError(f"Invalid sort_by '{sort_by}'. Must be one of: {', '.join(VALID_SORT_BY)}")
    if sort_by == "relevancy" and sort_order == "asc":
        raise ValueError("sort_by='relevancy' only supports sort_order='desc'")
    if platform == "onlyfans" and sort_by == "number_of_followers":
        raise ValueError("OnlyFans does not support sorting by number_of_followers. Use relevancy, engagement_rate, or growth_rate.")
    if sort_by == "growth_rate" and platform not in ("instagram", "tiktok", "youtube"):
        raise ValueError(f"growth_rate sorting is only available on instagram, tiktok, youtube — not {platform}")


def _parse_filters(filters_input: dict | str | None) -> dict[str, Any]:
    if not filters_input:
        return {}
    if isinstance(filters_input, dict):
        return filters_input
    try:
        return json.loads(filters_input)
    except (json.JSONDecodeError, TypeError):
        raise ValueError("filters must be a valid JSON object or JSON string")


def _validate_handle(handle: str) -> str:
    h = handle.strip()
    if not h or len(h) > 200:
        raise ValueError("Handle must be 1-200 characters")
    return h



def _flatten(obj: Any, prefix: str = "") -> dict[str, str]:
    """Flatten a nested dict into dot-separated keys for CSV columns."""
    out: dict[str, str] = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}{k}" if not prefix else f"{prefix}.{k}"
            if isinstance(v, dict):
                out.update(_flatten(v, key))
            elif isinstance(v, (list, tuple)):
                out[key] = json.dumps(v) if v else ""
            else:
                out[key] = "" if v is None else str(v)
    return out


def _preview_rows(data: list[dict], max_rows: int = 10) -> list[dict[str, str]]:
    """Build a preview of the first N rows with key columns for UI display.

    Dynamically selects platform-specific columns based on what's actually
    present in the data, so previews work for any enrichment mode/platform.
    """
    # Always-show columns first, then platform-specific candidates in priority order
    always_keys = ["handle", "status"]
    common_keys = ["first_name", "gender", "location", "is_creator", "has_brand_deals"]
    platform_keys_by_prefix = {
        "instagram": ["instagram.username", "instagram.follower_count", "instagram.engagement_percent"],
        "tiktok": ["tiktok.username", "tiktok.follower_count", "tiktok.engagement_percent"],
        "youtube": ["youtube.username", "youtube.subscriber_count", "youtube.engagement_percent"],
        "twitter": ["twitter.username", "twitter.follower_count"],
        "twitch": ["twitch.username", "twitch.follower_count"],
    }

    # Flatten a sample of rows to discover which keys exist
    sample_flats = []
    for item in data[:max_rows]:
        flat: dict[str, str] = {}
        for k, v in item.items():
            if k == "result" and isinstance(v, dict):
                flat.update(_flatten(v))
            elif isinstance(v, dict):
                flat.update(_flatten(v, k))
            elif isinstance(v, (list, tuple)):
                flat[k] = json.dumps(v) if v else ""
            else:
                flat[k] = "" if v is None else str(v)
        if "handle" not in flat and "input_value" in flat:
            flat["handle"] = flat.pop("input_value")
        elif "handle" in flat and "input_value" in flat:
            flat.pop("input_value")
        sample_flats.append(flat)

    # Detect which platform columns are present
    all_sample_keys = set()
    for f in sample_flats:
        all_sample_keys.update(f.keys())

    platform_cols: list[str] = []
    for prefix, cols in platform_keys_by_prefix.items():
        if any(k in all_sample_keys for k in cols):
            platform_cols.extend(c for c in cols if c in all_sample_keys)

    preview_keys = always_keys + [k for k in common_keys if k in all_sample_keys] + platform_cols

    rows = []
    for flat in sample_flats:
        row = {k: flat[k] for k in preview_keys if k in flat}
        rows.append(row)
    return rows


def _json_batch_to_csv(data: Any) -> str:
    """Convert batch JSON response (list of objects) to CSV string."""
    import csv
    import io

    if isinstance(data, dict):
        # Sometimes API wraps in a dict
        data = data.get("results", data.get("data", [data]))
    if not isinstance(data, list) or not data:
        return ""

    # Flatten all rows and collect all column names
    rows: list[dict[str, str]] = []
    all_keys: list[str] = []
    seen_keys: set[str] = set()

    for item in data:
        flat: dict[str, str] = {}
        # Flatten all top-level fields (input_value, status, handle, email, etc.)
        for k, v in item.items():
            if k == "result" and isinstance(v, dict):
                # Promote result contents to top-level (no "result." prefix)
                flat.update(_flatten(v))
            elif isinstance(v, dict):
                flat.update(_flatten(v, k))
            elif isinstance(v, (list, tuple)):
                flat[k] = json.dumps(v) if v else ""
            else:
                flat[k] = "" if v is None else str(v)
        # Ensure handle column: use input_value as fallback
        if "handle" not in flat and "input_value" in flat:
            flat["handle"] = flat.pop("input_value")
        elif "handle" in flat and "input_value" in flat:
            flat.pop("input_value")  # avoid duplicate
        rows.append(flat)
        for k in flat:
            if k not in seen_keys:
                seen_keys.add(k)
                all_keys.append(k)

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=all_keys, extrasaction="ignore")
    writer.writeheader()
    writer.writerows(rows)
    return buf.getvalue()


def _error_response(e: Exception) -> str:
    if isinstance(e, ApiError):
        return json.dumps({"error": True, "status": e.status, "message": e.message, "retryable": e.retryable})
    if isinstance(e, ValueError):
        return json.dumps({"error": True, "message": str(e)})
    return json.dumps({"error": True, "message": f"Unexpected error: {type(e).__name__}: {e}"})


# ═══════════════════════════════════════════════════════════════════════
# 1. DISCOVER CREATORS
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="discover_creators",
    annotations={"title": "Discover Creators", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
)
async def discover_creators(
    platform: Annotated[str, Field(description="Social media platform to search (instagram, youtube, tiktok, twitch, twitter, onlyfans)")],
    page: Annotated[int, Field(description="Page number (0-indexed, first page = 0)", ge=0)] = 0,
    limit: Annotated[int, Field(description="Results per page (1-50)", ge=1, le=50)] = 20,
    sort_by: Annotated[str, Field(description="Sort field: relevancy, engagement_rate, number_of_followers, growth_rate, cqi, or creator_quality_index. Can be combined with ai_search. growth_rate only on instagram/tiktok/youtube. number_of_followers not on onlyfans. relevancy only supports desc")] = "relevancy",
    sort_order: Annotated[str, Field(description="Sort direction: asc or desc (relevancy only supports desc)")] = "desc",
    ai_search: Annotated[Optional[str], Field(description="AI-powered semantic search (3-150 chars). Can be combined with any sort_by. Keep queries SHORT (e.g., 'fitness', 'Claude AI'). Do NOT add extra words.")] = None,
    filters: Annotated[Optional[dict], Field(description="Optional filters object. Common: location (array), gender (string), number_of_followers ({min,max}), engagement_percent ({min,max}), keywords_in_bio (array of strings), is_verified (bool), keywords_in_captions (array), hashtags (array), brands (array), creator_has (object of booleans)")] = None,
) -> str:
    """Search the Influencers.club database to discover creators/influencers. Returns profiles with basic stats.
    Costs 0.01 credits per creator returned.
    IMPORTANT: Always present results in the exact order returned by the API — do NOT re-sort or reorder them."""
    try:
        platform = _validate_platform(platform, DISCOVERY_PLATFORMS)
        _validate_sort(sort_by, sort_order, platform)
        f = _parse_filters(filters)
        if ai_search:
            ai_search = _validate_ai_search(ai_search)
            f["ai_search"] = ai_search

        body = {
            "platform": platform,
            "paging": {"limit": limit, "page": page},
            "sort": {"sort_by": sort_by, "sort_order": sort_order},
            "filters": f if f else None,
        }
        result = await client.post(f"{API_V1}/discovery/", body)
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 1b. DISCOVER CREATORS TO FILE
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="discover_creators_to_file",
    annotations={"title": "Discover Creators to File", "readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
)
async def discover_creators_to_file(
    platform: Annotated[str, Field(description="Social media platform to search")],
    pages: Annotated[int, Field(description="Number of pages to fetch (1-10, 50 creators per page)", ge=1, le=10)] = 1,
    sort_by: Annotated[str, Field(description="Sort field: relevancy, engagement_rate, number_of_followers, growth_rate, cqi, or creator_quality_index. Can be combined with ai_search")] = "relevancy",
    sort_order: Annotated[str, Field(description="Sort direction: asc or desc (relevancy only supports desc)")] = "desc",
    ai_search: Annotated[Optional[str], Field(description="AI-powered semantic search (3-150 chars). Can be combined with any sort_by.")] = None,
    filters: Annotated[Optional[dict], Field(description="Optional filters object (same as discover_creators)")] = None,
    filename: Annotated[Optional[str], Field(description="Optional custom filename (without extension). Defaults to auto-generated.")] = None,
) -> str:
    """Search creators and save results directly to a CSV file on disk. Fetches multiple pages automatically
    (up to 10 pages / 500 creators). Returns the file path and summary stats instead of raw data.
    Costs 0.01 credits per creator returned.
    Use this when the user wants to save, export, or download a list of creators."""
    try:
        platform = _validate_platform(platform, DISCOVERY_PLATFORMS)
        _validate_sort(sort_by, sort_order, platform)
        total_pages = min(pages, MAX_EXPORT_PAGES)
        f = _parse_filters(filters)

        if ai_search:
            ai_search = _validate_ai_search(ai_search)
            f["ai_search"] = ai_search

        # Ensure output directory exists
        output_path = Path(OUTPUT_DIR)
        output_path.mkdir(parents=True, exist_ok=True)

        # Fetch all pages (0-indexed)
        all_creators: list[dict[str, Any]] = []
        total_available = 0

        for page in range(0, total_pages):
            body = {
                "platform": platform,
                "paging": {"limit": 50, "page": page},
                "sort": {"sort_by": sort_by, "sort_order": sort_order},
                "filters": f if f else None,
            }
            result = await client.post(f"{API_V1}/discovery/", body)

            accounts = result.get("accounts", [])
            if accounts:
                all_creators.extend(accounts)

            if page == 0:
                total_available = result.get("total", 0)

            # Stop if we've fetched all available results
            if not accounts or len(accounts) < 50:
                break

        # Generate CSV
        csv_content = creators_to_csv(all_creators)

        # Generate filename
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%S")
        if filename:
            safe_name = re.sub(r"[^a-zA-Z0-9_-]", "_", filename)[:100]
        else:
            safe_name = f"{platform}_discovery_{ts}"

        file_name = f"{safe_name}.csv"
        file_path = output_path / file_name
        file_path.write_text(csv_content, encoding="utf-8")

        # Build host path for user display
        export_dir = _get_export_host_dir()
        if export_dir:
            host_path = os.path.join(export_dir, file_name).replace("/", "\\")
        else:
            host_path = str(file_path)

        return json.dumps({
            "success": True,
            "file": host_path,
            "container_path": str(file_path),
            "total_creators_exported": len(all_creators),
            "total_available": total_available,
            "pages_fetched": min(total_pages, max(1, (len(all_creators) + 49) // 50)),
            "platform": platform,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "filters_applied": bool(f),
            "ai_search": ai_search,
        }, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 2. FIND SIMILAR CREATORS
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="find_similar_creators",
    annotations={"title": "Find Similar Creators", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
)
async def find_similar_creators(
    platform: Annotated[str, Field(description="Platform of the reference creator (instagram, youtube, tiktok, twitch, twitter, onlyfans). ALWAYS ask the user — do not assume.")],
    filter_key: Annotated[str, Field(description='How to identify the creator: "url", "username", or "id"')] = "username",
    filter_value: Annotated[str, Field(description="The creator's URL, username, or platform ID")] = "",
    filters: Annotated[Optional[dict], Field(description="Optional filters object (same filters as discover_creators)")] = None,
    page: Annotated[int, Field(description="Page number (0-indexed, first page = 0)", ge=0)] = 0,
    limit: Annotated[int, Field(description="Results per page (1-50)", ge=1, le=50)] = 20,
) -> str:
    """Find creators similar to a specified creator. Always sorted by relevancy (no custom sort).
    Costs 0.01 credits per creator returned.
    IMPORTANT: Present results in a table (handle, followers, engagement rate, etc.) in the exact order returned by the API — do NOT re-sort or reorder. Do NOT offer CSV export — no export tool exists for similar creators."""
    try:
        if not filter_value or not filter_value.strip():
            raise ValueError("filter_value is required")
        platform = _validate_platform(platform, DISCOVERY_PLATFORMS)
        if filter_key not in ("url", "username", "id"):
            raise ValueError("filter_key must be 'url', 'username', or 'id'")
        filter_value = _validate_handle(filter_value)
        f = _parse_filters(filters)

        body: dict[str, Any] = {
            "platform": platform,
            "filter_key": filter_key,
            "filter_value": filter_value,
            "paging": {"limit": limit, "page": page},
        }
        if f:
            body["filters"] = f
        result = await client.post(f"{API_V1}/discovery/creators/similar/", body)
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 3. AUDIENCE OVERLAP
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="audience_overlap",
    annotations={"title": "Audience Overlap", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
)
async def audience_overlap(
    platform: Annotated[str, Field(description="Platform (instagram, tiktok, or youtube only)")],
    creators: Annotated[list[str], Field(description="List of 2-10 creator usernames or profile URLs", min_length=2, max_length=10)],
) -> str:
    """Analyze audience overlap between 2-10 creators on the same platform.
    Shows total followers, unique followers, and overlap percentages.
    Costs 1 credit per request.

    VISUALIZATION: After presenting the data, you MUST create a diagram:
    - 2-3 creators: Create an SVG Venn diagram. Each circle represents a creator's audience.
      Show the creator name and follower count on each circle. Show overlap counts/percentages
      in the intersection areas. Use distinct colors with transparency (e.g. rgba fills at 0.3 opacity)
      so overlapping regions are visible. Include a title and legend.
    - 4-10 creators: Create an HTML bar chart or matrix heatmap. For a bar chart, show each creator
      as a bar with total followers, and use grouped/stacked segments to show shared vs unique audience.
      For a heatmap, create a matrix where each cell shows the pairwise overlap percentage between
      two creators, color-coded from light (low overlap) to dark (high overlap).
      Include creator names as labels and overlap percentages in cells."""
    try:
        platform = _validate_platform(platform, OVERLAP_PLATFORMS)
        creators = [c.strip() for c in creators if c.strip()]
        if len(creators) < 2 or len(creators) > 10:
            raise ValueError("Must provide 2-10 creator usernames")

        result = await client.post(f"{API_V1}/creators/audience/overlap/", {"platform": platform, "creators": creators})

        # Add visualization hint based on creator count
        if isinstance(result, dict):
            num_creators = len(creators)
            if num_creators <= 3:
                result["_visualization"] = (
                    "Create an SVG Venn diagram for this overlap data. "
                    "Each circle = one creator's audience. Show follower counts on circles, "
                    "overlap counts/percentages in intersections. Use distinct colors with 0.3 opacity fills. "
                    "Make it visually clean and proportional to the data."
                )
            else:
                result["_visualization"] = (
                    "Create an HTML heatmap matrix for this overlap data. "
                    "Rows and columns = creator names. Each cell = pairwise overlap percentage. "
                    "Color-code cells from light (low overlap) to dark/saturated (high overlap). "
                    "Show percentage values inside each cell. Include a color scale legend."
                )

        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 4-12. DICTIONARY / LOOKUP ENDPOINTS (all free, 0 credits)
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="get_languages",
    annotations={"title": "Get Languages", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def get_languages() -> str:
    """Get the list of supported language codes for discovery filters. Free (0 credits)."""
    try:
        result = await client.get(f"{API_V1}/discovery/classifier/languages/")
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    name="get_locations",
    annotations={"title": "Get Locations", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def get_locations(
    platform: Annotated[str, Field(description="Platform to get locations for")],
) -> str:
    """Get available location codes for a specific platform's discovery filters. Free (0 credits)."""
    try:
        platform = _validate_platform(platform, DISCOVERY_PLATFORMS)
        result = await client.get(f"{API_V1}/discovery/classifier/locations/{platform}/")
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    name="get_brands",
    annotations={"title": "Get Brands", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def get_brands(
    search: Annotated[Optional[str], Field(description="Search term to filter brand names")] = None,
    offset: Annotated[Optional[int], Field(description="Pagination offset", ge=0)] = None,
) -> str:
    """Get available brand names for discovery filters (Instagram brand deal detection). Supports search and pagination. Free (0 credits)."""
    try:
        params: dict[str, str] = {}
        if search:
            params["search"] = search.strip()
        if offset is not None:
            params["offset"] = str(offset)
        result = await client.get(f"{API_V1}/discovery/classifier/brands/", params or None)
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    name="get_youtube_topics",
    annotations={"title": "Get YouTube Topics", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def get_youtube_topics() -> str:
    """Get available YouTube topic categories for discovery filters. Free (0 credits)."""
    try:
        result = await client.get(f"{API_V1}/discovery/classifier/yt-topics/")
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    name="get_games",
    annotations={"title": "Get Games", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def get_games() -> str:
    """Get available game names for Twitch discovery filters. Free (0 credits)."""
    try:
        result = await client.get(f"{API_V1}/discovery/classifier/games/")
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    name="get_audience_brand_categories",
    annotations={"title": "Get Audience Brand Categories", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def get_audience_brand_categories(
    search: Annotated[Optional[str], Field(description="Search term to filter categories")] = None,
    offset: Annotated[Optional[int], Field(description="Pagination offset", ge=0)] = None,
) -> str:
    """Search audience brand categories for Instagram audience filters. Supports pagination. Free (0 credits)."""
    try:
        params: dict[str, str] = {}
        if search:
            params["search"] = search.strip()
        if offset is not None:
            params["offset"] = str(offset)
        result = await client.get(f"{API_V1}/discovery/classifier/audience-brand-categories/", params or None)
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    name="get_audience_brand_names",
    annotations={"title": "Get Audience Brand Names", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def get_audience_brand_names(
    search: Annotated[Optional[str], Field(description="Search term to filter brand names")] = None,
    offset: Annotated[Optional[int], Field(description="Pagination offset", ge=0)] = None,
) -> str:
    """Search audience brand names for Instagram audience filters. Supports pagination. Free (0 credits)."""
    try:
        params: dict[str, str] = {}
        if search:
            params["search"] = search.strip()
        if offset is not None:
            params["offset"] = str(offset)
        result = await client.get(f"{API_V1}/discovery/classifier/audience-brand-names/", params or None)
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    name="get_audience_interests",
    annotations={"title": "Get Audience Interests", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def get_audience_interests(
    search: Annotated[Optional[str], Field(description="Search term to filter interests")] = None,
    offset: Annotated[Optional[int], Field(description="Pagination offset", ge=0)] = None,
) -> str:
    """Search audience interest categories for Instagram audience filters. Supports pagination. Free (0 credits)."""
    try:
        params: dict[str, str] = {}
        if search:
            params["search"] = search.strip()
        if offset is not None:
            params["offset"] = str(offset)
        result = await client.get(f"{API_V1}/discovery/classifier/audience-interests/", params or None)
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


@mcp.tool(
    name="get_audience_locations",
    annotations={"title": "Get Audience Locations", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def get_audience_locations(
    search: Annotated[Optional[str], Field(description="Search term to filter locations")] = None,
    offset: Annotated[Optional[int], Field(description="Pagination offset", ge=0)] = None,
) -> str:
    """Search audience locations for Instagram audience filters. Supports pagination. Free (0 credits)."""
    try:
        params: dict[str, str] = {}
        if search:
            params["search"] = search.strip()
        if offset is not None:
            params["offset"] = str(offset)
        result = await client.get(f"{API_V1}/discovery/classifier/audience-locations/", params or None)
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 13. CONNECTED SOCIALS
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="connected_socials",
    annotations={"title": "Connected Socials", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
)
async def connected_socials(
    platform: Annotated[str, Field(description="Platform of the known handle")],
    handle: Annotated[str, Field(description="Creator's username, profile URL, or YouTube channel ID")],
) -> str:
    """Find all social media profiles connected to a creator. Returns linked accounts across platforms.
    Costs 0.5 credits per successful request."""
    try:
        platform = _validate_platform(platform, ENRICHMENT_PLATFORMS)
        handle = _validate_handle(handle)
        result = await client.post(f"{API_V1}/creators/socials/", {"platform": platform, "handle": handle})
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 14. ENRICH BY HANDLE (FULL)
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="enrich_by_handle",
    annotations={"title": "Enrich by Handle (Full)", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
)
async def enrich_by_handle(
    handle: Annotated[str, Field(description="Creator's username, profile URL, or YouTube channel ID")],
    platform: Annotated[str, Field(description="Primary platform of the creator (NOT linkedin — use enrich_by_handle_raw for linkedin)")],
    email_required: Annotated[str, Field(description='"must_have" returns only if email found; "preferred" returns data even without email')] = "preferred",
    include_lookalikes: Annotated[bool, Field(description="Include similar creator suggestions")] = False,
    include_audience_data: Annotated[bool, Field(description="Include audience demographics (IG, TT, YT only)")] = True,
) -> str:
    """Get comprehensive creator data including email, demographics, platform stats, niche classification,
    income estimates, and audience demographics. Primary way to get a creator's email.
    LinkedIn is NOT supported — use enrich_by_handle_raw for linkedin profiles.
    Costs 1 credit per successful request.
    NOTE: This is the expensive option. Use enrich_by_handle_raw (0.03 credits) for basic lookups unless the user specifically asks for full/detailed/complete data."""
    try:
        platform = _validate_platform(platform, ENRICHMENT_PLATFORMS)
        if platform == "linkedin":
            raise ValueError("LinkedIn is not supported for full enrichment. Use enrich_by_handle_raw instead.")
        handle = _validate_handle(handle)
        if email_required not in ("must_have", "preferred"):
            raise ValueError("email_required must be 'must_have' or 'preferred'")

        result = await client.post(f"{API_V1}/creators/enrich/handle/full/", {
            "handle": handle,
            "platform": platform,
            "email_required": email_required,
            "include_lookalikes": include_lookalikes,
            "include_audience_data": include_audience_data,
        })
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 15. ENRICH BY HANDLE (RAW)
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="enrich_by_handle_raw",
    annotations={"title": "Enrich by Handle (Raw)", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
)
async def enrich_by_handle_raw(
    handle: Annotated[str, Field(description="Creator's username, profile URL, or YouTube channel ID")],
    platform: Annotated[str, Field(description="Platform to look up")],
) -> str:
    """Get raw profile data for a creator. Returns basic profile info, follower/following counts, bio,
    verification status. Lighter and cheaper than full enrichment.
    Costs 0.03 credits per successful request."""
    try:
        platform = _validate_platform(platform, ENRICHMENT_PLATFORMS)
        handle = _validate_handle(handle)
        result = await client.post(f"{API_V1}/creators/enrich/handle/raw/", {"handle": handle, "platform": platform})
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 16. ENRICH BY EMAIL (BASIC)
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="enrich_by_email",
    annotations={"title": "Enrich by Email (Basic)", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
)
async def enrich_by_email(
    email: Annotated[str, Field(description="Email address to look up")],
) -> str:
    """Find creator profiles associated with an email address. Costs 0.05 credits per successful request."""
    try:
        email = email.strip().lower()
        if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
            raise ValueError("Invalid email address format")
        result = await client.post(f"{API_V1}/creators/enrich/email/", {"email": email})
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 18. CREATE BATCH ENRICHMENT
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="create_batch_enrichment",
    annotations={"title": "Create Batch Enrichment", "readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
)
async def create_batch_enrichment(
    enrichment_mode: Annotated[str, Field(description="Leave EMPTY on first call — server returns mode menu. Options: basic (0.05/record, emails), raw (0.03/record, handles), full (1/record, handles).")] = "",
    csv_content: Annotated[str, Field(description='ONLY for small inline lists (under 20 entries). NEWLINE-separated with header. Example: "email\\nfoo@bar.com\\nbaz@qux.com".')] = "",
    csv_file_path: Annotated[Optional[str], Field(description="Path to CSV in the imports folder. Get from list_import_files after upload. NEVER construct paths yourself.")] = None,
    platform: Annotated[Optional[str], Field(description="Required for handle-based modes (raw, full). Allowed: instagram, youtube, tiktok, twitter, twitch, onlyfans")] = None,
    email_required: Annotated[Optional[str], Field(description="For handle modes only: must_have or preferred")] = None,
    include_lookalikes: Annotated[Optional[bool], Field(description="For handle full mode only")] = None,
    include_audience_data: Annotated[Optional[bool], Field(description="For handle full mode, IG/TT/YT only")] = None,
    exclude_platforms: Annotated[Optional[list[str]], Field(description="For email-based modes only")] = None,
    min_followers: Annotated[Optional[int], Field(description="For email-based modes only", ge=0)] = None,
    metadata: Annotated[Optional[Any], Field(description="Optional JSON metadata string (e.g., campaign name)")] = None,
) -> str:
    """Create a batch enrichment job. Upload CSV with up to 10,000 handles or emails.

    RULES:
    1. Leave enrichment_mode empty on first call — server returns mode menu for user to choose.
    2. Files >20 entries: get_upload_url → user uploads → list_import_files → csv_file_path.
    3. csv_content only for <20 entries typed in chat. NEVER for dropped/attached files."""
    try:
        if not enrichment_mode or enrichment_mode not in ("raw", "full", "basic"):
            # Detect input type from CSV header to show only relevant modes
            detected_input = None
            try:
                peek_text = None
                if csv_file_path:
                    p = csv_file_path.strip()
                    fname = os.path.basename(p)
                    for try_dir in [IMPORTS_DIR, OUTPUT_DIR]:
                        try_path = Path(try_dir) / fname
                        if try_path.exists():
                            peek_text = try_path.read_text(encoding="utf-8", errors="replace")
                            break
                elif csv_content and csv_content.strip():
                    peek_text = csv_content.strip()
                if peek_text:
                    first_line = peek_text.strip().split("\n")[0].strip().lower().replace('"', '').replace("'", "")
                    # Check header or first column headers for email/handle
                    cols = [c.strip() for c in first_line.split(",")]
                    if any(c in ("email", "emails") for c in cols):
                        detected_input = "email"
                    elif any(c in ("handle", "handles") for c in cols):
                        detected_input = "handle"
                    else:
                        # Scan first few data values
                        data_lines = [l.strip() for l in peek_text.strip().split("\n")[1:6] if l.strip()]
                        vals = [l.split(",")[0].strip().replace('"', '') for l in data_lines]
                        email_ct = sum(1 for v in vals if "@" in v and "." in v.split("@")[-1])
                        detected_input = "email" if vals and email_ct > len(vals) / 2 else "handle"
            except Exception:
                pass  # fall back to showing all options

            email_options = [
                {"mode": "basic", "input": "emails", "cost": "0.05 credits/record", "description": "Creator match with basic social stats. Optional: exclude_platforms, min_followers."},
            ]
            handle_options = [
                {"mode": "raw", "input": "handles", "cost": "0.03 credits/record", "description": "Basic profile info (bio, followers, verified). Requires platform."},
                {"mode": "full", "input": "handles", "cost": "1 credit/record", "description": "Everything: email, demographics, audience, income, brand deals. Requires platform."},
            ]

            if detected_input == "email":
                options = email_options
                hint = "Detected EMAIL column — showing email-based modes only."
            elif detected_input == "handle":
                options = handle_options
                hint = "Detected HANDLE column — showing handle-based modes only."
            else:
                options = email_options + handle_options
                hint = "Could not detect input type — showing all modes."

            return json.dumps({
                "error": True,
                "action_required": "ask_user",
                "detected_input_type": detected_input,
                "message": (
                    f"{hint} Ask the user which enrichment mode they want. Present these options. "
                    "Only ask for the mode. Do NOT proactively ask about exclude_platforms or min_followers "
                    "unless the user mentions wanting to filter."
                ),
                "options": options,
            }, indent=2)
        if enrichment_mode in ("raw", "full") and not platform:
            raise ValueError("platform is required for handle-based enrichment modes (raw, full)")
        if platform:
            platform = _validate_platform(platform, ENRICHMENT_PLATFORMS)

        # Get CSV bytes — from file path or inline string content
        csv_bytes: bytes | None = None

        # Priority 1: File path (checks /imports first, then /exports)
        if csv_file_path:
            host_path = csv_file_path.strip()
            container_path = None

            # Check imports directory first (uploaded files)
            import_host_dir = os.environ.get("IMPORT_HOST_DIR", "")
            if import_host_dir and host_path.replace("\\", "/").startswith(import_host_dir.replace("\\", "/")):
                relative = host_path.replace("\\", "/")[len(import_host_dir.replace("\\", "/")):].lstrip("/")
                container_path = Path(IMPORTS_DIR) / relative
            else:
                # Check exports directory (legacy support)
                export_dir = _get_export_host_dir()
                if export_dir and host_path.replace("\\", "/").startswith(export_dir.replace("\\", "/")):
                    relative = host_path.replace("\\", "/")[len(export_dir.replace("\\", "/")):].lstrip("/")
                    container_path = Path(OUTPUT_DIR) / relative

            # Also try just the filename in /imports (most common case)
            if container_path is None or not container_path.exists():
                fname = os.path.basename(host_path)
                imports_try = Path(IMPORTS_DIR) / fname
                exports_try = Path(OUTPUT_DIR) / fname
                if imports_try.exists():
                    container_path = imports_try
                elif exports_try.exists():
                    container_path = exports_try
                elif container_path is None:
                    container_path = Path(host_path)

            if container_path.exists():
                csv_bytes = container_path.read_bytes()
            else:
                raise ValueError(
                    f"File not found: {host_path}. "
                    f"Upload via the browser page at http://localhost:{UPLOAD_PORT} first, "
                    f"then call list_import_files to get the correct path."
                )

        # Priority 2: Inline CSV string (small lists only, <20 entries)
        if csv_bytes is None:
            csv_content = csv_content.strip()
            if csv_content:
                # Space-separated with no newlines → split into lines
                if "\n" not in csv_content and " " in csv_content:
                    parts = csv_content.split()
                    csv_content = "\n".join(parts)

                lines = [l.strip() for l in csv_content.strip().split("\n") if l.strip()]
                line_count = len(lines)
                if line_count > 25:
                    raise ValueError(
                        f"Too many rows ({line_count}) for inline csv_content. Maximum is 20. "
                        f"Upload via http://localhost:{UPLOAD_PORT} then use list_import_files."
                    )

                # Ensure proper single-column CSV with handle/email header
                # Check if first line is a valid header
                valid_headers = ("email", "handle", "emails", "handles")
                first_line = lines[0].strip().lower().replace('"', '').replace("'", "")

                # Multi-column detection: extract the right column
                if "," in lines[0]:
                    import csv as _csv
                    import io as _io
                    header_cols = [c.strip().lower().replace('"', '').replace("'", "") for c in lines[0].split(",")]
                    best_col = 0
                    col_type = "handle"
                    # Find column by header name
                    for i, col_name in enumerate(header_cols):
                        if col_name in valid_headers:
                            best_col = i
                            col_type = "email" if col_name in ("email", "emails") else "handle"
                            break
                    else:
                        # No valid header — scan data for emails
                        for ci in range(len(header_cols)):
                            vals = []
                            for row in lines[1:6]:
                                cols = row.split(",")
                                if ci < len(cols):
                                    v = cols[ci].strip().replace('"', '')
                                    if v:
                                        vals.append(v)
                            if vals and sum(1 for v in vals if "@" in v and "." in v.split("@")[-1]) > len(vals) / 2:
                                best_col = ci
                                col_type = "email"
                                break

                    # Extract single column
                    reader = _csv.reader(_io.StringIO("\n".join(lines)))
                    new_lines = [col_type]
                    for i, row in enumerate(reader):
                        if i == 0:
                            continue
                        if best_col < len(row):
                            val = row[best_col].strip()
                            if val:
                                new_lines.append(val)
                    lines = new_lines

                elif first_line not in valid_headers:
                    # Single column but no valid header — detect type and prepend header
                    sample = lines[:5] if first_line not in valid_headers else lines[1:6]
                    email_count = sum(1 for v in sample if "@" in v and "." in v.split("@")[-1])
                    col_type = "email" if email_count > len(sample) / 2 else "handle"
                    lines.insert(0, col_type)

                csv_content = "\n".join(lines)
                csv_bytes = csv_content.encode("utf-8")
            else:
                raise ValueError("Provide csv_file_path or csv_content.")

        # Detect duplicates and warn (each duplicate costs credits)
        duplicate_warning = ""
        try:
            text = csv_bytes.decode("utf-8", errors="replace")
            lines = [l.strip() for l in text.strip().split("\n") if l.strip()]
            if len(lines) > 1:  # header + data
                values = lines[1:]  # skip header
                total = len(values)
                unique = len(set(v.lower() for v in values))
                dupes = total - unique
                if dupes > 0:
                    duplicate_warning = (
                        f"⚠️ Found {dupes} duplicate entries out of {total} rows. "
                        f"Duplicates will be billed. Unique: {unique}, Total: {total}."
                    )
        except Exception:
            pass  # don't block submission over a warning

        files = {"file": ("batch.csv", csv_bytes, "text/csv")}
        data: dict[str, str] = {"enrichment_mode": enrichment_mode}
        if platform:
            data["platform"] = platform
        if email_required:
            data["email_required"] = email_required
        if include_lookalikes is not None:
            data["include_lookalikes"] = str(include_lookalikes).lower()
        if include_audience_data is not None:
            data["include_audience_data"] = str(include_audience_data).lower()
        if exclude_platforms:
            data["exclude_platforms"] = json.dumps(exclude_platforms)
        if min_followers is not None:
            data["min_followers"] = str(min_followers)
        if metadata:
            data["metadata"] = json.dumps(metadata) if isinstance(metadata, dict) else str(metadata)

        result = await client.post_multipart(f"{API_V1}/enrichment/batch/", files, data)
        if isinstance(result, dict):
            if duplicate_warning:
                result["duplicate_warning"] = duplicate_warning
            result["_auto_action"] = (
                "Batch submitted. Tell the user the batch_id and that you will monitor progress. "
                "If there is a 'duplicate_warning', show it to the user BEFORE polling. "
                "Then IMMEDIATELY call get_batch_status with this batch_id. Do NOT ask the user — just poll."
            )
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 19. BATCH STATUS (with server-side rate limiting)
# ═══════════════════════════════════════════════════════════════════════
_batch_poll_cache: dict[str, tuple[float, dict]] = {}  # batch_id -> (timestamp, result)
POLL_INTERVAL = 35  # seconds
POLL_CACHE_TTL = 600  # 10 minutes — evict stale entries from abandoned batches


def _evict_stale_polls() -> None:
    """Remove poll cache entries older than POLL_CACHE_TTL to prevent unbounded growth."""
    now = _time.time()
    stale = [bid for bid, (ts, _) in _batch_poll_cache.items() if now - ts > POLL_CACHE_TTL]
    for bid in stale:
        _batch_poll_cache.pop(bid, None)


@mcp.tool(
    name="get_batch_status",
    annotations={"title": "Get Batch Status", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
)
async def get_batch_status(
    batch_id: Annotated[str, Field(description="Batch job ID from create_batch_enrichment")],
) -> str:
    """Check the status of a batch enrichment job. Returns progress info. Free (0 credits).
    Server automatically waits 35s between polls — it blocks internally so you can call it in a loop.

    IMPORTANT AUTO-POLLING RULES:
    - If status is 'processing': Report progress to user, then call get_batch_status again immediately. The server handles the wait.
    - If status is 'finished': IMMEDIATELY call download_batch_results with the batch_id. Do NOT ask the user.
    - If status is 'paused_insufficient_credits': Tell the user they need more credits, offer to resume with resume_batch."""
    import time
    try:
        batch_id = batch_id.strip()
        if not batch_id:
            raise ValueError("batch_id is required")

        # Evict stale entries from abandoned batches (prevents unbounded growth)
        _evict_stale_polls()

        now = time.time()

        # Block until poll interval has passed — prevents Claude from spamming
        if batch_id in _batch_poll_cache:
            last_time, _last_result = _batch_poll_cache[batch_id]
            wait_remaining = POLL_INTERVAL - (now - last_time)
            if wait_remaining > 0:
                await asyncio.sleep(wait_remaining)

        result = await client.get(f"{API_V1}/enrichment/batch/{batch_id}/status/")

        # Cache with current time AFTER the API call (not before sleep)
        _batch_poll_cache[batch_id] = (time.time(), result)

        # Clean finished batches from cache and add auto-action hints
        if isinstance(result, dict):
            status = result.get("status", "")
            if status == "finished":
                _batch_poll_cache.pop(batch_id, None)
                result["_auto_action"] = (
                    "Batch finished! IMMEDIATELY call download_batch_results with this batch_id. "
                    "Do NOT ask the user — just download."
                )
            elif status == "processing":
                result["_auto_action"] = (
                    "Still processing. Report progress to user, then wait 35 seconds and "
                    "call get_batch_status again. Do NOT ask the user whether to continue polling."
                )
            elif status == "paused_insufficient_credits":
                _batch_poll_cache.pop(batch_id, None)
                result["_auto_action"] = (
                    "Batch paused — insufficient credits. Tell the user and ask if they want to "
                    "resume after adding credits (use resume_batch)."
                )

        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 20. BATCH DOWNLOAD
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="download_batch_results",
    annotations={"title": "Download Batch Results", "readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
)
async def download_batch_results(
    batch_id: Annotated[str, Field(description="Batch job ID")],
) -> str:
    """Download batch results as CSV and save to the user's influencer-exports folder on Desktop.
    Batch must have status "finished" or "paused_insufficient_credits". Free (0 credits).
    Always saves as CSV. Filename is auto-generated from batch_id — do NOT pass a custom name.
    Report the file path to the user and stop.
    Do NOT enrich results individually after downloading — that wastes credits.
    IMPORTANT: Display the 'preview' table to the user so they can see a summary of results."""
    try:
        batch_id = batch_id.strip()
        if not batch_id:
            raise ValueError("batch_id is required")

        export_dir = _get_export_host_dir()
        if not export_dir:
            raise ValueError(
                "Export path not configured. Ask the user where they want exported files saved, "
                "then call setup_export_path with their answer. This only needs to be done once."
            )

        # Build unique filename: short_batch_id + source CSV name (if known from imports)
        short_id = batch_id.replace("bch_", "")[:8]
        source_label = ""
        imports = Path(IMPORTS_DIR)
        if imports.exists():
            # Find most recently modified CSV in imports as likely source
            csv_files = sorted(imports.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)
            if csv_files:
                stem = csv_files[0].stem
                # Shorten to max 40 chars
                source_label = re.sub(r'[^\w\-]', '_', stem)[:40].rstrip('_')

        if source_label:
            base_name = f"{source_label}_{short_id}"
        else:
            base_name = f"batch_{short_id}"

        output_path = Path(OUTPUT_DIR)
        file_path = output_path / f"{base_name}.csv"

        # If file exists, add timestamp to avoid overwrite
        if file_path.exists():
            ts = int(_time.time())
            base_name = f"{base_name}_{ts}"
            file_path = output_path / f"{base_name}.csv"

        # Fetch as JSON from API (CSV format returns 404), then convert to CSV
        result = await client.get(
            f"{API_V1}/enrichment/batch/{batch_id}/", {"format": "json"}, timeout=120.0
        )

        # Extract the results list from the API response
        if isinstance(result, list):
            raw_data = result
        elif isinstance(result, dict):
            for key in ("results", "data"):
                if key in result and isinstance(result[key], list):
                    raw_data = result[key]
                    break
            else:
                raw_data = []
        else:
            raw_data = []

        # Build preview of top 10 rows for UI display
        preview = _preview_rows(raw_data) if raw_data else []
        total_records = len(raw_data)

        # Convert JSON to CSV
        csv_text = _json_batch_to_csv(result)

        # Save to file
        output_path.mkdir(parents=True, exist_ok=True)
        file_path.write_text(csv_text, encoding="utf-8")

        host_path = os.path.join(export_dir, f"{base_name}.csv")

        return json.dumps({
            "success": True,
            "file": host_path,
            "batch_id": batch_id,
            "total_records": total_records,
            "preview": preview,
            "message": f"Showing top {len(preview)} of {total_records} results. Full data saved to: {host_path}",
        }, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 21. RESUME BATCH
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="resume_batch",
    annotations={"title": "Resume Batch", "readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
)
async def resume_batch(
    batch_id: Annotated[str, Field(description="Batch job ID to resume")],
) -> str:
    """Resume a paused batch enrichment job. Use when status is "paused_insufficient_credits". Free (0 credits)."""
    try:
        batch_id = batch_id.strip()
        if not batch_id:
            raise ValueError("batch_id is required")
        result = await client.post(f"{API_V1}/enrichment/batch/{batch_id}/resume/", {})
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 22. CREATOR POSTS
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="get_creator_posts",
    annotations={"title": "Get Creator Posts", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
)
async def get_creator_posts(
    platform: Annotated[str, Field(description="Platform (instagram, tiktok, or youtube)")],
    handle: Annotated[str, Field(description="Creator's username or handle")],
    count: Annotated[Optional[int], Field(description="Number of posts to retrieve (platform limits apply)", ge=1, le=50)] = None,
    pagination_token: Annotated[Optional[str], Field(description="Cursor token from previous response for next page")] = None,
) -> str:
    """Get recent posts/content from a creator. Supports Instagram (12/page), TikTok (max 35), YouTube (max 50).
    Uses cursor-based pagination. Costs 0.15 credits per request."""
    try:
        platform = _validate_platform(platform, CONTENT_PLATFORMS)
        handle = _validate_handle(handle)
        body: dict[str, Any] = {"platform": platform, "handle": handle}
        if count is not None:
            body["count"] = count
        if pagination_token:
            body["pagination_token"] = pagination_token
        result = await client.post(f"{API_V1}/creators/content/posts/", body)
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 23. POST DETAILS
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="get_post_details",
    annotations={"title": "Get Post Details", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": True},
)
async def get_post_details(
    platform: Annotated[str, Field(description="Platform (instagram, tiktok, or youtube)")],
    post_id: Annotated[str, Field(description="Platform-specific post/video ID (NOT a URL)")],
    content_type: Annotated[str, Field(description="Type of content: data (post info), comments, transcript, audio (no audio for YouTube)")] = "data",
    pagination_token: Annotated[Optional[str], Field(description="Cursor token for paginating comments")] = None,
) -> str:
    """Get detailed information about a specific post. Can retrieve post data, comments, transcript, or audio.
    Costs 0.03 credits per request."""
    try:
        platform = _validate_platform(platform, CONTENT_PLATFORMS)
        if content_type not in ("data", "comments", "transcript", "audio"):
            raise ValueError("content_type must be data, comments, transcript, or audio")
        if platform == "youtube" and content_type == "audio":
            raise ValueError("YouTube does not support audio content type. Use data, comments, or transcript.")
        post_id = post_id.strip()
        if not post_id:
            raise ValueError("post_id is required")

        body: dict[str, Any] = {"platform": platform, "post_id": post_id, "content_type": content_type}
        if pagination_token:
            body["pagination_token"] = pagination_token
        result = await client.post(f"{API_V1}/creators/content/details/", body)
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 24. CHECK CREDITS
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="check_credits",
    annotations={"title": "Check Credits", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def check_credits() -> str:
    """Check your Influencers.club account credit balance and usage. Free (0 credits).
    Use this to verify you have enough credits before expensive operations."""
    try:
        result = await client.get(f"{API_V1}/accounts/credits/")
        return json.dumps(result, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 25. GET UPLOAD URL
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="get_upload_url",
    annotations={"title": "Get Upload URL", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def get_upload_url() -> str:
    """Get the upload page URL and then IMMEDIATELY call wait_for_upload in the SAME response.
    You MUST call wait_for_upload right after this — do NOT stop, do NOT ask the user anything,
    do NOT wait for confirmation. Show the URL and call wait_for_upload in ONE response.

    CRITICAL: Do NOT use browser automation, Chrome tools, or any other tool to upload the file.
    The USER uploads the file themselves in their browser. You just show the link and wait."""
    try:
        # Use UPLOAD_HOST env var if set (for remote/VM setups), otherwise localhost
        upload_host = os.environ.get("UPLOAD_HOST", "localhost")
        upload_url = f"http://{upload_host}:{UPLOAD_PORT}"

        response: dict[str, Any] = {
            "upload_url": upload_url,
            "_auto_action": (
                "You MUST do EXACTLY two things in your NEXT response — nothing else: "
                "1) Show the upload URL as a clickable link to the user. "
                "2) IMMEDIATELY call wait_for_upload in the SAME response. "
                "Do NOT ask the user anything. Do NOT say 'want me to wait?'. "
                "Do NOT use Claude in Chrome, browser automation, navigate, or any browser tools. "
                "The USER opens the link and uploads the file themselves. You just wait."
            ),
        }

        if upload_host == "localhost":
            response["note"] = (
                "URL uses 'localhost' — this only works if the browser is on the same machine as the server. "
                "If Docker runs on a remote host or VM, set UPLOAD_HOST env var to the host's IP/hostname."
            )

        return json.dumps(response, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 25b. WAIT FOR UPLOAD
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="wait_for_upload",
    annotations={"title": "Wait For Upload", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def wait_for_upload() -> str:
    """Wait for a file to be uploaded via the upload page. Polls every 2 seconds for up to 3 minutes.
    Call this IMMEDIATELY after showing the user the upload URL from get_upload_url.
    Returns the uploaded file details when detected. Free (0 credits)."""
    try:
        imports = Path(IMPORTS_DIR)
        import_host_dir = os.environ.get("IMPORT_HOST_DIR", "")

        # Snapshot existing files
        existing: set[str] = set()
        if imports.exists():
            existing = {f.name for f in imports.glob("*.csv")}

        # Poll for new file — 90 iterations × 2s = 3 minutes
        for _ in range(90):
            await asyncio.sleep(2)
            if imports.exists():
                current = {f.name for f in imports.glob("*.csv")}
                new_files = current - existing
                if new_files:
                    # Pick the newest new file
                    newest = max(new_files, key=lambda n: (imports / n).stat().st_mtime)
                    f = imports / newest
                    stat = f.stat()
                    host_path = os.path.join(import_host_dir, newest) if import_host_dir else newest

                    # Count rows
                    try:
                        text = f.read_text(encoding="utf-8", errors="replace")
                        lines = [l for l in text.strip().split("\n") if l.strip()]
                        row_count = max(0, len(lines) - 1)
                    except Exception:
                        row_count = 0

                    return json.dumps({
                        "detected": True,
                        "filename": newest,
                        "host_path": host_path,
                        "size_bytes": stat.st_size,
                        "rows": row_count,
                        "next_step": "Call create_batch_enrichment with csv_file_path set to host_path. Leave enrichment_mode empty.",
                    }, indent=2)

        return json.dumps({
            "detected": False,
            "message": "No upload detected after 3 minutes. Ask the user to try again or call get_upload_url.",
        }, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 26. LIST IMPORT FILES
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="list_import_files",
    annotations={"title": "List Import Files", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def list_import_files() -> str:
    """List uploaded CSV files ready for batch enrichment. Shows the 5 most recent uploads.
    Call this after the user uploads via the upload page, then use the host_path as
    csv_file_path in create_batch_enrichment. Free (0 credits)."""
    try:
        imports = Path(IMPORTS_DIR)
        import_host_dir = os.environ.get("IMPORT_HOST_DIR", "")
        files = []

        if imports.exists():
            for f in sorted(imports.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)[:5]:
                stat = f.stat()
                host_path = os.path.join(import_host_dir, f.name) if import_host_dir else f.name
                files.append({
                    "filename": f.name,
                    "host_path": host_path,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                })

        return json.dumps({
            "files": files,
            "total": len(files),
            "import_dir": import_host_dir or "not configured",
            "next_step": "Call create_batch_enrichment with csv_file_path set to host_path of the file. Leave enrichment_mode empty." if files else "No files found. Upload via the upload page first.",
        }, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 26b. LIST EXPORT FILES (results/output)
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="list_export_files",
    annotations={"title": "List Export Files", "readOnlyHint": True, "destructiveHint": False, "openWorldHint": False},
)
async def list_export_files() -> str:
    """List result/output CSV files (batch results, discovery exports). Shows 10 most recent. Free (0 credits)."""
    try:
        exports = Path(OUTPUT_DIR)
        export_dir = _get_export_host_dir()
        files = []

        if exports.exists():
            for f in sorted(exports.glob("*.csv"), key=lambda p: p.stat().st_mtime, reverse=True)[:10]:
                stat = f.stat()
                host_path = os.path.join(export_dir, f.name) if export_dir else f.name
                files.append({
                    "filename": f.name,
                    "host_path": host_path,
                    "size_bytes": stat.st_size,
                    "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
                })

        return json.dumps({
            "files": files,
            "total": len(files),
            "export_dir": export_dir or "not configured",
        }, indent=2)
    except Exception as e:
        return _error_response(e)


# ═══════════════════════════════════════════════════════════════════════
# 27. SETUP EXPORT PATH
# ═══════════════════════════════════════════════════════════════════════
@mcp.tool(
    name="setup_export_path",
    annotations={"title": "Setup Export Path", "readOnlyHint": False, "destructiveHint": False, "openWorldHint": False},
)
async def setup_export_path(
    export_path: Annotated[str, Field(description="Full path on the user's machine where exported files should be saved. Example: C:\\Users\\John\\Desktop\\influencer-exports")],
) -> str:
    """Set the folder path where exported CSV files will be saved on the user's machine.
    Ask the user where they want exports saved, then call this tool with their answer.
    This only needs to be done once — the setting persists across sessions."""
    try:
        export_path = export_path.strip()
        if not export_path:
            raise ValueError("export_path is required")

        # Save to config file in the mounted volume
        config = {}
        if os.path.exists(CONFIG_FILE):
            try:
                with open(CONFIG_FILE) as f:
                    config = json.load(f)
            except (json.JSONDecodeError, OSError):
                config = {}

        config["export_host_dir"] = export_path

        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        with open(CONFIG_FILE, "w") as f:
            json.dump(config, f, indent=2)

        return json.dumps({
            "success": True,
            "export_path": export_path,
            "message": f"Export path set to: {export_path}. All future downloads will be saved there.",
        }, indent=2)
    except Exception as e:
        return _error_response(e)
