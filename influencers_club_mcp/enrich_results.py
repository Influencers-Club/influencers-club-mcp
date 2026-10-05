"""Shapes the full, analytics and profile enrichment results before a model reads them.

A full report on a large creator runs to 400,000+ characters of JSON, several
times what MCP clients show a model (Claude Code parks anything over 25,000
tokens in a file), and most of it is image links, internal IDs and the long
tails of the audience lists.

What a shaped response looks like
---------------------------------
The API's response keeps its top-level fields and gains `notes`::

    {"result": {...}, "credits_cost": 1.0, "notes": ["Left out: ...", "<path>: top 30 of 142 brands by weight."]}

Inside `result` the keys and their nesting stay as the API sent them. Four
passes change what is under them, in this order (see `_shape`):

1. `_drop`: leave out, at any depth, image and media links, internal IDs,
   map coordinates and GraphQL plumbing.
2. `_trim` (detail="compact" only): cut the longest lists, one line per cut
   in `notes`: the top 30 audience brands, the verified accounts among
   notable likers and commenters, captions cut to 120 characters, the first
   30 other links.
3. `_round_numbers`: round decimals; counts stay exact.
4. `_tables`: a list of four or more objects becomes one table, so its keys
   are written once::

       [{"name": "Brazil", "code": "BR", "weight": 0.1193}, ...]
       -> {"columns": ["name", "code", "weight"], "rows": [["Brazil", "BR", 0.1193], ...]}

The three levels of `detail`:

- "compact" (default): all four passes.
- "full": passes 1, 3 and 4, so every entry stays.
- "raw": the API's JSON as it came.

`sections` narrows any of the three to the parts a question needs; a named
section that holds nothing is said so in `notes`.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from typing import Annotated, Any, Optional

from pydantic import WithJsonSchema

__all__ = [
    "AnalyticsSection",
    "DETAILS",
    "Detail",
    "ENRICH_ANALYTICS_SECTIONS",
    "ENRICH_SECTIONS",
    "EnrichSection",
    "shape_profile",
    "shape_result",
    "validate_detail",
    "validate_sections",
]

logger = logging.getLogger(__name__)

# ─── Names the tools accept ────────────────────────────────────────────

# "posts" exists on the full tier only. Two different "similar creator" lists:
# audience_lookalikes come with every audience report (creators whose audience
# resembles this one's), lookalikes are computed by the API on request
# (creators similar to this one).
ENRICH_SECTIONS: tuple[str, ...] = (
    "overview", "audience", "audience_brands", "audience_notable_users", "audience_lookalikes",
    "sponsors", "sponsored_posts", "lookalikes", "posts",
)
ENRICH_ANALYTICS_SECTIONS: tuple[str, ...] = tuple(s for s in ENRICH_SECTIONS if s != "posts")
DETAILS: tuple[str, ...] = ("compact", "full", "raw")

# Parameter types: a string whose schema lists the names. The tools check the
# value themselves, after tidying it, rather than the type: a value the type
# rejects comes back as plain text instead of the JSON error the server
# instructions promise, and `Audience` or `RAW` would be refused.
EnrichSection = Annotated[str, WithJsonSchema({"type": "string", "enum": list(ENRICH_SECTIONS)})]
AnalyticsSection = Annotated[str, WithJsonSchema({"type": "string", "enum": list(ENRICH_ANALYTICS_SECTIONS)})]
Detail = Annotated[str, WithJsonSchema({"type": "string", "enum": list(DETAILS)})]

# ─── Which section owns which key ──────────────────────────────────────

# Keys each section owns inside a platform block; "overview" owns the rest.
_SECTION_OF_PLATFORM_KEY = {
    "audience": "audience",
    "brand_affinity": "audience_brands",
    "past_sponsors": "sponsors",
    "brands_found": "sponsors",
    "sponsored_posts": "sponsored_posts",
    "post_data": "posts",
    "posts": "posts",
    "tweets": "posts",
    "user_media": "posts",
}
# Lists inside each audience slice's `data` that are sections of their own;
# the demographics around them belong to "audience".
_SECTION_OF_AUDIENCE_LIST = {
    "audience_brand_affinity": "audience_brands",
    "notable_users": "audience_notable_users",
    "audience_lookalikes": "audience_lookalikes",
}
# Keys each section owns at the top level of `result`; "overview" owns the rest.
_SECTION_OF_GENERAL_KEY = {
    "audience_interests": "audience",
    "lookalikes": "lookalikes",
}

# ─── Pass 1: what is left out ──────────────────────────────────────────

# Dropped at any depth: media links, internal IDs, map coordinates and
# GraphQL plumbing. Post IDs stay: they tie a sponsor's `post_ids` to its posts
# and are what get_post_details takes. The creator's own `id` stays (a YouTube
# channel ID is a valid handle for these tools); `id`s inside lists are dropped,
# except a Twitch video's, its only identifier (twitch.tv/videos/<id>).
_DROP_KEYS = frozenset({
    "coords", "embed_html", "sound_url", "profile_url",
    "user_id", "userid", "sec_user_id", "media_id", "media_key",
    "related_playlist_id", "unsubscribed_trailer_id", "last_broadcast_id",
    "retweet_users", "__typename", "extensions",
})
# Keys naming an image go too: profile_picture, thumbnailURL, boxArtURL, ...
_IMAGE_KEY = re.compile(r"picture|thumbnail|image|boxart", re.IGNORECASE)
# A field holding a link to an image, video or audio file goes whatever it is
# called: links to the API's image proxies and the platforms' media CDNs, and
# links ending in a media file extension. Links to posts, profiles and sites stay.
_MEDIA_LINK = re.compile(
    r"^https?://(?:[\w-]+\.)*(?:pictures\.influencersclub\.workers\.dev|img\.onsocial\.ai|ytimg\.com"
    r"|ggpht\.com|twimg\.com|jtvnw\.net|panels\.twitch\.tv|cdninstagram\.com|fbcdn\.net"
    r"|tiktokcdn(?:-\w+)?\.com)(?:[/?#:]|$)"
    r"|^https?://[^?#]+\.(?:jpe?g|png|webp|gif|avif|heic|mp4|mov|m3u8|mp3|m4a)(?:[?#]|$)",
    re.IGNORECASE,
)
# The account's own ID is part of an identity, so the profile tier keeps it.
_ACCOUNT_ID_KEYS = frozenset({"user_id", "userid", "sec_user_id"})

# ─── Pass 2: what detail="compact" trims ───────────────────────────────

CAPTION_LIMIT = 120
BRAND_LIMIT = 30
# Notable likers and commenters are mostly unverified fans; when none is verified,
# the biggest accounts stand in.
NOTABLE_LIMIT = 10
# Links found across a creator's content: 259 for one large YouTube channel.
LINK_LIMIT = 30
# Slices built from engagement, where the notable accounts are cut to the verified ones.
_ENGAGEMENT_SLICES = ("audience_likers", "audience_commenters")
# Lists of posts, and the fields of a post that hold its text.
_POST_LISTS = frozenset({"post_data", "sponsored_posts", "posts", "user_media"})
_CAPTION_KEYS = ("caption", "description", "text")

# ─── Pass 4: lists as tables ───────────────────────────────────────────

# Shorter lists of objects stay objects; a table only pays off from a few rows up.
_TABLE_MIN_ROWS = 4
# An object left with only one of these collapses to its value: an interest
# {"name": ...} becomes "Music", a tagged account {"username": ...} its username.
# The items of one list collapse together or not at all, so one sparse brand
# cannot turn the list's table back into objects.
_COLLAPSIBLE_KEYS = frozenset({"name", "username"})
# The two lists of accounts inside an audience slice. An account keeps every
# field the platform reports except these four; `stats` and `geo` come back as
# columns (reels_engagements, videos_avg_views, ..., country, city).
_ACCOUNT_LISTS = frozenset({"notable_users", "audience_lookalikes"})
_ACCOUNT_DROP = frozenset({"picture", "url", "geo", "stats"})

# ─── The first line of `notes` ─────────────────────────────────────────

_LEFT_OUT_NOTE = (
    "Left out: image and video links, profile links, internal IDs other than post IDs, map coordinates, "
    "and the state or region of notable users and lookalikes."
)
_PROFILE_NOTE = "Left out: image links and internal IDs other than the account's own."


# ─── Checking the names ────────────────────────────────────────────────


def _name(value: str) -> str:
    """A section or detail name as a model may write it: any case, padded, or still in its quotes."""
    return value.strip().strip("\"'").strip().lower()


def validate_sections(
    sections: Optional[list[str]], allowed: tuple[str, ...], include_lookalikes: Optional[bool]
) -> list[str]:
    """The sections to return, in `allowed` order. None or empty means all of them.

    Names are matched after `_name` tidies them; an unknown one raises before
    the call is billed. include_lookalikes is the older switch for the computed
    lookalikes: True adds that section, False removes it, None leaves `sections`
    to decide.
    """
    chosen = {_name(s) for s in sections} if sections else set(allowed)
    unknown = chosen - set(allowed)
    if unknown:
        raise ValueError(
            f"Unknown sections: {', '.join(sorted(unknown))}. "
            f"Must be one or more of: {', '.join(allowed)}"
        )
    if include_lookalikes:
        chosen.add("lookalikes")
    elif include_lookalikes is False:
        chosen.discard("lookalikes")
    if not chosen:
        raise ValueError(
            "No section left to return: `sections` names only lookalikes while include_lookalikes is false."
        )
    return [s for s in allowed if s in chosen]


def validate_detail(detail: str) -> str:
    """The detail level, matched after `_name` tidies it; an unknown one raises
    before the call is billed."""
    level = _name(detail) if isinstance(detail, str) else None
    if level not in DETAILS:
        raise ValueError(f"Unknown detail '{detail}'. Must be one of: {', '.join(DETAILS)}")
    return level


# ─── Sections ──────────────────────────────────────────────────────────


def _select_audience_sections(audience: dict, wanted: set[str]) -> dict:
    """A platform's `audience` object holding only the wanted sections.

    Each slice (followers, likers, commenters) keeps the lists whose section is
    wanted; its demographics, and the slices without `data` (a credibility
    histogram, a slice that failed), belong to the "audience" section.
    """
    out: dict[str, Any] = {}
    for key, value in audience.items():
        data = value.get("data") if isinstance(value, dict) else None
        if not isinstance(data, dict):
            # A credibility histogram, or a slice that failed ({"success": false, "error": ...}).
            if "audience" in wanted:
                out[key] = value
            continue
        kept = {k: v for k, v in data.items() if _SECTION_OF_AUDIENCE_LIST.get(k, "audience") in wanted}
        if "audience" in wanted:
            out[key] = {**value, "data": kept}
        elif kept:
            out[key] = {"data": kept}
    return out


def _select_platform_sections(block: dict, wanted: set[str]) -> dict:
    """A platform block (`result["instagram"]`) holding only the keys of the wanted sections."""
    out: dict[str, Any] = {}
    for key, value in block.items():
        if key == "audience" and isinstance(value, dict):
            audience = _select_audience_sections(value, wanted)
            if audience:
                out[key] = audience
        elif _SECTION_OF_PLATFORM_KEY.get(key, "overview") in wanted:
            out[key] = value
    return out


def _select_sections(result: dict, sections: list[str]) -> dict:
    """Copy of an enrichment `result` holding only the requested sections."""
    wanted = set(sections)
    out: dict[str, Any] = {}
    for key, value in result.items():
        if isinstance(value, dict):
            block = _select_platform_sections(value, wanted)
            if block:
                out[key] = block
        elif _SECTION_OF_GENERAL_KEY.get(key, "overview") in wanted:
            out[key] = value
    return out


def _holds_data(value: Any) -> bool:
    """Whether anything is in there: an empty list or object, or a null, is nothing."""
    if isinstance(value, dict):
        return any(_holds_data(v) for v in value.values())
    if isinstance(value, list):
        return any(_holds_data(v) for v in value)
    return value is not None


# ─── Small checks and conversions the passes share ─────────────────────


def _round(value: Any) -> Any:
    """Ratios keep 4 significant digits and other decimals 2; counts stay exact."""
    if not isinstance(value, float):
        return value
    if value.is_integer():
        return int(value)
    if abs(value) < 1:
        return float(f"{value:.4g}")
    return round(value, 2)


def _number(value: Any) -> float:
    """A field as a sort key; a string or a missing value ranks last."""
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else 0


def _is_url(value: Any) -> bool:
    """Whether the value is a web link."""
    return isinstance(value, str) and value.startswith(("http://", "https://"))


def _is_media_link(value: Any) -> bool:
    """Whether the value is a link to an image, video or audio file."""
    return _is_url(value) and bool(_MEDIA_LINK.match(value))


@lru_cache(maxsize=1024)
def _dropped(key: str, in_list: bool) -> bool:
    """Whether pass 1 leaves this key out; an `id` only goes inside a list.

    Cached: a report holds thousands of keys but only ~130 distinct names. Bounded,
    since a few keys come from the data (dates, handles) and would never repeat.
    """
    return key in _DROP_KEYS or bool(_IMAGE_KEY.search(key)) or (in_list and key == "id")


def _is_collapsible(value: Any) -> bool:
    """Whether an object is left with just a name or a username, so its value can stand for it."""
    return isinstance(value, dict) and len(value) == 1 and next(iter(value)) in _COLLAPSIBLE_KEYS


def _is_table(value: Any) -> bool:
    """Whether the value is a table this module made."""
    return isinstance(value, dict) and set(value) == {"columns", "rows"}


def _repeats(value: Any, main: Any) -> bool:
    """Whether a field only says again what the object's code or name already says."""
    return isinstance(value, str) and isinstance(main, str) and value.casefold() == main.casefold()


def _media_summary(media: Any) -> Any:
    """What a post's media is, without its links: a YouTube video's duration and
    definition, a carousel's item types."""
    if isinstance(media, dict):
        return {
            k: v for k, v in media.items()
            if not isinstance(v, (dict, list)) and not _is_url(v) and not _dropped(k, True)
        }
    if isinstance(media, list):
        return [m["type"] for m in media if isinstance(m, dict) and m.get("type")]
    return media


def _graphql_nodes(value: dict) -> Optional[list]:
    """The nodes of a GraphQL connection ({"edges": [{"node": ...}]}), else None."""
    edges = value.get("edges")
    if not isinstance(edges, list) or set(value) - {"__typename"} != {"edges"}:
        return None
    if not all(isinstance(e, dict) and "node" in e for e in edges):
        return None
    return [e["node"] for e in edges]


def _brand_key(brand: Any) -> Any:
    """A brand as its name and interest names, whichever of the two lists it comes from."""
    if not isinstance(brand, dict):
        return brand
    interests = brand.get("interest") or []
    return brand.get("name"), [i.get("name") if isinstance(i, dict) else i for i in interests]


def _repeats_follower_brands(block: dict) -> bool:
    """Whether a platform block's brand_affinity only repeats its followers'
    audience_brand_affinity: the API derives it from that list, without the weights."""
    brands = block.get("brand_affinity")
    audience = block.get("audience")
    followers = audience.get("audience_followers") if isinstance(audience, dict) else None
    data = followers.get("data") if isinstance(followers, dict) else None
    theirs = data.get("audience_brand_affinity") if isinstance(data, dict) else None
    if not isinstance(brands, list) or not isinstance(theirs, list) or not brands:
        return False
    return [_brand_key(b) for b in brands] == [_brand_key(b) for b in theirs]


# ─── Pass 1: drop ──────────────────────────────────────────────────────


def _drop(value: Any, in_list: bool, keep_account_id: bool) -> Any:
    """The value without the keys and media links of pass 1, at any depth.

    A GraphQL connection becomes its list of nodes. A post's `media` is reduced
    to what it is (types, duration) without its links. `in_list` says the value
    sits inside a list, where an `id` is internal; `keep_account_id` keeps the
    creator's own account ID (the profile tier).
    """
    if isinstance(value, dict):
        nodes = _graphql_nodes(value)
        if nodes is not None:
            return [_drop(node, True, keep_account_id) for node in nodes]
        # A Twitch video's id is its only identifier; other ids inside lists are internal.
        keep_id = in_list and value.get("__typename") == "Video"
        out: dict[str, Any] = {}
        for k, item in value.items():
            kept = (keep_id and k == "id") or (keep_account_id and not in_list and k in _ACCOUNT_ID_KEYS)
            if (_dropped(k, in_list) and not kept) or _is_media_link(item):
                continue
            if k != "media":
                out[k] = _drop(item, in_list, keep_account_id)
            elif not _is_url(item):
                out[k] = _media_summary(item)
        return out
    if isinstance(value, list):
        return [_drop(item, True, keep_account_id) for item in value]
    return value


# ─── Pass 2: trim ──────────────────────────────────────────────────────


def _trim(value: Any, key: str, path: str, notes: list[str]) -> Any:
    """The value with the trims of pass 2 applied to the lists under it, each
    cut written to `notes` with its `path`."""
    if isinstance(value, dict):
        return {k: _trim(v, k, f"{path}.{k}", notes) for k, v in value.items()}
    if not isinstance(value, list):
        return value
    if key in _ACCOUNT_LISTS:
        accounts = [u for u in value if isinstance(u, dict)]
        if any(f".{s}." in path for s in _ENGAGEMENT_SLICES):
            accounts = _keep_notable(accounts, path, notes)
        return accounts
    items = _keep_top_brands(value, path, notes) if key == "audience_brand_affinity" else value
    items = [_trim(item, key, path, notes) for item in items]
    if key in _POST_LISTS:
        _cut_captions(items, path, notes)
    elif key == "other_links" and len(items) > LINK_LIMIT:
        notes.append(f"{path}: the first {LINK_LIMIT} of {len(items)} links.")
        items = items[:LINK_LIMIT]
    elif key == "tweets" and all(isinstance(t, str) for t in items):
        items = _cut_texts(items, path, "tweets", notes)
    return items


def _keep_notable(accounts: list[dict], path: str, notes: list[str]) -> list[dict]:
    """The notable likers or commenters worth keeping: the verified ones, or the
    NOTABLE_LIMIT largest when none is verified."""
    total = len(accounts)
    verified = [u for u in accounts if u.get("is_verified")]
    if verified:
        if len(verified) < total:
            notes.append(f"{path}: the {len(verified)} verified of {total} accounts.")
        return verified
    if total > NOTABLE_LIMIT:
        notes.append(f"{path}: none verified; the {NOTABLE_LIMIT} largest of {total} accounts.")
        return sorted(accounts, key=lambda u: _number(u.get("followers")), reverse=True)[:NOTABLE_LIMIT]
    return accounts


def _keep_top_brands(brands: list, path: str, notes: list[str]) -> list:
    """The BRAND_LIMIT heaviest audience brands; a brand without a weight, or
    with one that is not a number, ranks last."""
    if len(brands) <= BRAND_LIMIT:
        return brands
    top = sorted(
        brands, key=lambda b: _number(b.get("weight")) if isinstance(b, dict) else 0, reverse=True
    )[:BRAND_LIMIT]
    notes.append(f"{path}: top {len(top)} of {len(brands)} brands by weight.")
    return top


def _cut_texts(texts: list[str], path: str, label: str, notes: list[str]) -> list[str]:
    """The texts cut to CAPTION_LIMIT, with one note saying how many were."""
    cuts = [_cut(t) for t in texts]
    changed = sum(was_cut for _, was_cut in cuts)
    if changed:
        notes.append(f"{path}: {changed} of {len(texts)} {label} cut to {CAPTION_LIMIT} characters.")
    return [text for text, _ in cuts]


def _cut(text: str) -> tuple[str, bool]:
    """The text cut to CAPTION_LIMIT characters, untouched when it fits; and whether it was cut."""
    if len(text) <= CAPTION_LIMIT:
        return text, False
    return text[: CAPTION_LIMIT - 1].rstrip() + "…", True


def _cut_captions(posts: list, path: str, notes: list[str]) -> None:
    """Cuts each post's caption, description or text in place."""
    for field in _CAPTION_KEYS:
        with_field = [p for p in posts if isinstance(p, dict) and isinstance(p.get(field), str)]
        if not with_field:
            continue
        cut = _cut_texts([p[field] for p in with_field], path, f"{field}s", notes)
        for post, text in zip(with_field, cut):
            post[field] = text


# ─── Pass 3: round ─────────────────────────────────────────────────────


def _round_numbers(value: Any) -> Any:
    """The value with every decimal under it rounded by `_round`."""
    if isinstance(value, dict):
        return {k: _round_numbers(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_round_numbers(v) for v in value]
    return _round(value)


# ─── Pass 4: tables ────────────────────────────────────────────────────


def _tables(value: Any, key: str, in_list: bool, collapse: bool = True) -> Any:
    """The value with every list of four or more objects under it as a table.

    An object inside a list that is left with just a name collapses to it;
    the items of one list do so together or not at all (`collapse` is False
    for an item itself). The two account lists get their own rows.
    """
    if isinstance(value, dict):
        out = {k: _tables(v, k, in_list) for k, v in value.items()}
        if collapse and in_list and _is_collapsible(out):
            return next(iter(out.values()))
        return out
    if not isinstance(value, list):
        return value
    if key in _ACCOUNT_LISTS:
        return _table([_account_row(u) for u in value if isinstance(u, dict)])
    items = [_tables(item, key, True, collapse=False) for item in value]
    if items and all(_is_collapsible(item) for item in items):
        items = [next(iter(item.values())) for item in items]
    return _table(items)


def _account_row(account: dict) -> dict:
    """One account as a flat row: its own scalar fields, one column per number
    in `stats` (`<post_type>_<field>`, the "all" type under the bare field
    name), and its country code and city from `geo`."""
    row = {
        k: v for k, v in account.items()
        if k not in _ACCOUNT_DROP and not _dropped(k, True)
        and not isinstance(v, (dict, list)) and not _is_url(v)
    }
    for stat in account.get("stats") or []:
        if not isinstance(stat, dict):
            continue
        kind = stat.get("post_type")
        for field, value in stat.items():
            if field == "post_type" or isinstance(value, bool) or not isinstance(value, (int, float)):
                continue
            if kind == "all":
                row.setdefault(field, value)
            elif kind:
                row[f"{kind}_{field}"] = value
    geo = account.get("geo")
    country = geo.get("country") if isinstance(geo, dict) else None
    if isinstance(country, dict) and country.get("code"):
        row["country"] = country["code"]
    city = geo.get("city") if isinstance(geo, dict) else None
    if isinstance(city, dict) and city.get("name"):
        row["city"] = city["name"]
    return row


def _flatten_row(item: dict) -> dict:
    """One table row. A nested object with a code or name becomes that value, its
    other fields `key.field` columns unless they only repeat it (a code's name is
    spelled out by the code); any other nested object gives `key.field` columns,
    named after it even when nothing clashes, so every row feeds a column from
    the same object. A nested table stays one cell."""
    out: dict[str, Any] = {}
    for key, value in item.items():
        if not isinstance(value, dict) or _is_table(value):
            out[key] = value
            continue
        main = "code" if "code" in value else "name" if "name" in value else None
        if main is not None:
            out[key] = value[main]
        for sub, sub_value in value.items():
            if sub == main or (main == "code" and sub == "name"):
                continue
            if main is not None and _repeats(sub_value, value[main]):
                continue
            out[f"{key}.{sub}"] = sub_value
    return out


def _table(items: list) -> Any:
    """A list of objects as {"columns": [...], "rows": [[...]]}, so keys aren't
    repeated on every item. Shorter lists, and lists that are not all objects,
    come back as they are."""
    if len(items) < _TABLE_MIN_ROWS or not all(isinstance(x, dict) for x in items):
        return items
    rows = [_flatten_row(x) for x in items]
    columns: list[str] = []
    for row in rows:
        columns.extend(k for k in row if k not in columns)
    return {"columns": columns, "rows": [[row.get(c) for c in columns] for row in rows]}


# ─── The passes in order ───────────────────────────────────────────────


def _without_repeated_brands(result: dict, notes: list[str]) -> dict:
    """The result without a platform's brand_affinity when it only repeats the
    followers' brand list, which is how the API builds it."""
    out: dict[str, Any] = {}
    for key, value in result.items():
        if isinstance(value, dict) and _repeats_follower_brands(value):
            notes.append(
                f"{key}.brand_affinity left out: the same brands as the followers' "
                "audience_brand_affinity, without the weights."
            )
            value = {k: v for k, v in value.items() if k != "brand_affinity"}
        out[key] = value
    return out


def _shape(result: dict, *, trim: bool, keep_account_id: bool, notes: list[str]) -> dict:
    """The whole `result` through the passes described at the top of this module.

    The passes work on what is under each top-level field; the top-level
    fields themselves all stay.
    """
    shaped = _without_repeated_brands(result, notes)
    shaped = {key: _drop(value, False, keep_account_id) for key, value in shaped.items()}
    if trim:
        shaped = {key: _trim(value, key, key, notes) for key, value in shaped.items()}
    shaped = _round_numbers(shaped)
    return _tables(shaped, "", False)


def _shaped(
    response: dict, result: dict, *, trim: bool, keep_account_id: bool, first_note: str, notes: list[str]
) -> dict:
    """The response with its `result` shaped; as it came, with a note, if shaping fails."""
    cuts: list[str] = []
    try:
        shaped = _shape(result, trim=trim, keep_account_id=keep_account_id, notes=cuts)
    except Exception:
        # The credit is spent by now; the data as it came beats an error.
        logger.exception("Enrichment result returned as it came: shaping it failed")
        return {**response, "result": result, "notes": ["Returned as it came: shaping it failed.", *notes]}
    return {**response, "result": shaped, "notes": [first_note, *cuts, *notes]}


def shape_profile(response: Any, detail: str = "compact") -> Any:
    """A profile-tier response shaped like the larger tiers, keeping the account's own ID."""
    detail = validate_detail(detail)
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict) or detail == "raw":
        return response
    return _shaped(
        response, result, trim=detail == "compact", keep_account_id=True, first_note=_PROFILE_NOTE, notes=[]
    )


def shape_result(response: Any, sections: list[str], allowed: tuple[str, ...], detail: str) -> Any:
    """The API response trimmed to `sections` and shaped for `detail`."""
    detail = validate_detail(detail)
    result = response.get("result") if isinstance(response, dict) else None
    if not isinstance(result, dict):
        return response
    notes: list[str] = []
    # Naming sections is narrowing; switching the lookalikes off alone is not.
    if set(allowed) - set(sections) - {"lookalikes"}:
        empty = [s for s in sections if not _holds_data(_select_sections(result, [s]))]
        if empty:
            notes.append(f"{', '.join(empty)}: no data for this creator.")
    if len(sections) < len(allowed):
        result = _select_sections(result, sections)
    if detail == "raw":
        return {**response, "result": result, **({"notes": notes} if notes else {})}
    return _shaped(
        response, result, trim=detail == "compact", keep_account_id=False, first_note=_LEFT_OUT_NOTE, notes=notes
    )
