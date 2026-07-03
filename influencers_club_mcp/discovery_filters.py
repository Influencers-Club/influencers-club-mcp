"""Typed discovery-filter schema shared by discover_creators / discover_creators_to_file /
find_similar_creators.

Mirrors the dashboard's ``DiscoveryFiltersSerializer`` (public_api/discovery_api/serializers.py)
— that serializer is the source of truth; keep the two in sync when filters are added there.

Why a model instead of a free-form dict: the upstream API silently ignores unknown filter
keys, so a misplaced or misspelled key used to return unfiltered results with no error.
``extra="forbid"`` turns that into an immediate, named validation error, and every legal
filter becomes a visible property in the tool's JSON schema instead of prose.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

__all__ = ["DiscoveryFilters", "coerce_filters"]


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


# Common range sub-key aliases → the API's canonical {min, max}. Folded in before
# extra="forbid" runs, so a client sending {"gte": 50000} is remapped, not rejected.
_RANGE_ALIASES = {
    "min": "min", "gte": "min", "gt": "min", "minimum": "min",
    "max": "max", "lte": "max", "lt": "max", "maximum": "max",
}


class Range(_Base):
    min: Optional[float] = None
    max: Optional[float] = None

    @model_validator(mode="before")
    @classmethod
    def _fold_range_aliases(cls, data: Any) -> Any:
        """Accept gte/lte/gt/lt/minimum/maximum as aliases for min/max.

        Runs before field validation and extra='forbid', so aliased bounds are
        normalized rather than rejected. Truly unknown keys still fall through to
        extra='forbid'. Two aliases mapping to the same bound with different values
        is a caller error, raised with the offending keys named.
        """
        if not isinstance(data, dict):
            return data
        out: dict[str, Any] = {}
        for key, value in data.items():
            canon = _RANGE_ALIASES.get(key.lower(), key) if isinstance(key, str) else key
            if canon in out and out[canon] != value:
                raise ValueError(
                    f"range got conflicting bounds for '{canon}' via multiple aliases; "
                    f"use only 'min'/'max'."
                )
            out[canon] = value
        return out


class Growth(_Base):
    growth_percentage: Optional[float] = None
    time_range_months: Optional[int] = None


class AudienceGender(_Base):
    type: Optional[str] = None
    min_pct: Optional[float] = None


class AudienceLocation(_Base):
    name: Optional[str] = None
    type: Optional[str] = None
    min_pct: Optional[float] = None


class AudienceAge(_Base):
    range_: Optional[str] = Field(default=None, alias="range")
    min_pct: Optional[float] = None


class AudienceLanguage(_Base):
    language_abbr: Optional[str] = None
    min_pct: Optional[float] = None


class AudienceInterest(_Base):
    name: Optional[str] = None
    min_pct: Optional[float] = None


class Audience(_Base):
    location: Optional[list[AudienceLocation]] = None
    gender: Optional[AudienceGender] = None
    language: Optional[list[AudienceLanguage]] = None
    age: Optional[list[AudienceAge]] = None
    interests: Optional[list[AudienceInterest]] = None
    brands: Optional[list[str]] = None
    brand_categories: Optional[list[str]] = None
    credibility: Optional[Literal["bad", "low", "normal", "good", "high", "best"]] = None


# Keys accepted inside creator_has (kept as a mapping so the schema stays compact;
# unknown keys are rejected by the validator below with the valid set in the message).
CREATOR_HAS_KEYS = frozenset({
    "has_amazonaffiliates", "has_anchor", "has_applemusic", "has_bandcamp", "has_behance",
    "has_buymeacoffee", "has_cameo", "has_canva", "has_clubhouse", "has_community",
    "has_discord", "has_dribbble", "has_etsy", "has_facebook", "has_fiverr", "has_github",
    "has_gofundme", "has_goodreads", "has_instagram", "has_kakao", "has_kickstarter",
    "has_kofi", "has_linkedin", "has_linktree", "has_medium", "has_onlyfans", "has_patreon",
    "has_phone", "has_pinterest", "has_podcast", "has_redbubble", "has_shopify",
    "has_shopltk", "has_snapchat", "has_soundcloud", "has_spotify", "has_spring",
    "has_streamlabs", "has_substack", "has_telegram", "has_tiktok", "has_tumblr",
    "has_twitch", "has_twitter", "has_udemy", "has_viber", "has_vimeo", "has_vk",
    "has_weebly", "has_whatsApp", "has_wix", "has_youtube",
})


class DiscoveryFilters(_Base):
    """Every legal discovery filter. Some fields only apply to certain platforms
    (e.g. number_of_subscribers/topics → YouTube, tweets → Twitter/X, games_played →
    Twitch, reels/posts → Instagram); the API ignores filters that don't apply."""

    # Profile
    location: Optional[list[str]] = None
    type: Optional[str] = None
    gender: Optional[str] = None
    profile_language: Optional[list[str]] = None
    is_verified: Optional[bool] = None
    exclude_private_profile: Optional[bool] = None

    # Semantic search (prefer the top-level ai_search parameter; accepted here too)
    ai_search: Optional[str] = Field(default=None, min_length=3, max_length=150)

    # Reach / engagement
    number_of_followers: Optional[Range] = None
    number_of_subscribers: Optional[Range] = None
    followers: Optional[Range] = Field(default=None, description="Twitch follower range")
    engagement_percent: Optional[Range] = None
    follower_growth: Optional[Growth] = None
    subscriber_growth: Optional[Growth] = None
    income: Optional[Range] = None
    posting_frequency: Optional[float] = None

    # Averages
    average_likes: Optional[Range] = None
    average_comments: Optional[Range] = None
    average_views: Optional[Range] = None
    average_video_downloads: Optional[Range] = None
    average_views_on_long_videos: Optional[Range] = None
    median_views_long: Optional[Range] = None
    average_views_on_shorts: Optional[Range] = None
    average_views_for_reels: Optional[Range] = None
    average_stream_views: Optional[Range] = None
    average_stream_duration: Optional[Range] = None
    avg_views_last_30_days: Optional[Range] = None
    maximum_views_count: Optional[Range] = None

    # Content volume
    number_of_videos: Optional[Range] = None
    video_count: Optional[Range] = None
    number_of_posts: Optional[Range] = None
    number_of_photos: Optional[Range] = None
    number_of_likes: Optional[Range] = None
    number_of_tweets: Optional[Range] = None
    tweets_count: Optional[Range] = None
    shorts_percentage: Optional[Range] = None
    reels_percent: Optional[Range] = None
    long_video_duration: Optional[Range] = None
    streamed_hours_last_30_days: Optional[Range] = None
    streams_count_last_30_days: Optional[Range] = None
    subscription_price: Optional[Range] = None

    # Keywords / content matching
    keywords_in_bio: Optional[list[str]] = None
    exclude_keywords_in_bio: Optional[list[str]] = None
    keywords_in_captions: Optional[list[str]] = None
    keywords_not_in_captions: Optional[list[str]] = None
    keywords_in_description: Optional[list[str]] = None
    keywords_not_in_description: Optional[list[str]] = None
    keywords_in_video_description: Optional[list[str]] = None
    keywords_not_in_video_description: Optional[list[str]] = None
    keywords_in_video_titles: Optional[list[str]] = None
    keywords_not_in_video_titles: Optional[list[str]] = None
    keywords_in_tweets: Optional[list[str]] = None
    keywords_not_in_tweets: Optional[list[str]] = None
    video_description: Optional[list[str]] = None
    not_video_description: Optional[list[str]] = None
    tweets: Optional[list[str]] = None
    hashtags: Optional[list[str]] = None
    not_hashtags: Optional[list[str]] = None
    topics: Optional[list[str]] = None
    games_played: Optional[list[str]] = None
    brands: Optional[list[str]] = None

    # Links
    link_in_bio: Optional[list[str]] = None
    not_link_in_bio: Optional[list[str]] = None
    links_from_description: Optional[list[str]] = None
    links_from_video_description: Optional[list[str]] = None
    has_link_in_bio: Optional[bool] = None

    # Platform flags
    has_shorts: Optional[bool] = None
    has_podcast: Optional[bool] = None
    has_videos: Optional[bool] = None
    has_live_videos: Optional[bool] = None
    has_live_streams: Optional[bool] = None
    has_community_posts: Optional[bool] = None
    has_free_account: Optional[bool] = None
    has_courses: Optional[bool] = None
    has_membership: Optional[bool] = None
    has_merch: Optional[bool] = None
    has_tik_tok_shop: Optional[bool] = None
    has_done_brand_deals: Optional[bool] = None
    promotes_affiliate_links: Optional[bool] = None
    does_live_streaming: Optional[bool] = None
    streams_live: Optional[bool] = None
    is_monetizing: Optional[bool] = None
    is_twitch_partner: Optional[bool] = None

    # Cross-platform presence, e.g. {"has_linkedin": true}
    creator_has: Optional[dict[str, bool]] = None

    # Audience demographics
    audience: Optional[Audience] = None

    # Housekeeping
    exclude_handles: Optional[list[str]] = Field(default=None, max_length=10_000)
    exclude_role_based_emails: Optional[bool] = None

    @field_validator("creator_has")
    @classmethod
    def _known_creator_has_keys(cls, v: dict[str, bool] | None) -> dict[str, bool] | None:
        if v:
            unknown = set(v) - CREATOR_HAS_KEYS
            if unknown:
                raise ValueError(
                    f"unknown creator_has key(s): {', '.join(sorted(unknown))}. "
                    f"Valid keys: {', '.join(sorted(CREATOR_HAS_KEYS))}"
                )
        return v


def coerce_filters(value: DiscoveryFilters | dict | str | None) -> dict[str, Any]:
    """Normalize the filters argument to a plain dict for the API.

    Accepts the validated model (normal path), a raw dict or JSON string (defensive —
    some clients stringify nested objects), or None. Unknown keys raise with the key
    named, never pass through silently.
    """
    if value is None:
        return {}
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            raise ValueError("filters must be a JSON object, e.g. {\"number_of_followers\": {\"min\": 50000}}")
        if value is None:  # the literal JSON string "null"
            return {}
    if isinstance(value, dict):
        value = DiscoveryFilters.model_validate(value)
    if not isinstance(value, DiscoveryFilters):
        # a JSON array/scalar, or any other non-object — never a valid filter set
        raise ValueError("filters must be a JSON object, e.g. {\"number_of_followers\": {\"min\": 50000}}")
    return value.model_dump(exclude_none=True, by_alias=True)
