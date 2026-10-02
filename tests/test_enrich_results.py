"""The full and analytics enrichment tools return every section, compacted.

A whole report is several times what MCP clients let a model see, and most of it
is image links, internal IDs and the long tails of the audience lists. The tools
drop what a model cannot use, send lists of objects as tables, trim the longest
lists and name every cut in `notes`; detail="full" keeps every entry and
detail="raw" returns the API's JSON untouched.
"""

import asyncio
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session

from influencers_club_mcp import enrich_results, server
from influencers_club_mcp.enrich_results import (
    BRAND_LIMIT,
    CAPTION_LIMIT,
    ENRICH_ANALYTICS_SECTIONS,
    ENRICH_SECTIONS,
    LINK_LIMIT,
    shape_result,
    validate_sections,
)

LONG_CAPTION = "word " * 60


def brand(i: int) -> dict:
    return {
        "id": i,
        "name": f"Brand {i}",
        "interest": [{"id": 3, "name": "Music"}, {"id": 25, "name": "Electronics"}],
        "weight": round(0.01 + i / 1000, 6),
        "affinity": 1.090161,
    }


def person(i: int, verified: bool = True, **extra) -> dict:
    return {
        "user_id": str(1000 + i),
        "username": f"account{i}",
        "picture": f"https://img.example.com/{i}.jpg",
        "followers": 344306896 - i,
        "fullname": f"Account {i}",
        "url": f"https://www.instagram.com/account{i}",
        "is_verified": verified,
        "engagements": 1231033,
        "stats": [{"post_type": "all", "engagements": 1231033}],
        "geo": {"country": {"id": 1, "name": "Brazil", "code": "BR", "coords": {"lat": -15.7, "lon": -47.9}}},
        **extra,
    }


def post(i: int, caption: str = "hi") -> dict:
    return {
        "post_id": str(i),
        "created_at": "2026-09-23T19:33:27",
        "caption": caption,
        "post_url": f"https://instagram.com/p/{i}",
        "media": [{"media_id": "9", "type": "image", "url": "https://cdn.example.com/9.jpg"}],
        "engagement": {"likes": 3111179, "comments": 35600},
    }


def response() -> dict:
    """The shape of a full-tier response, with lists long enough to be trimmed."""
    return {
        "result": {
            "instagram": {
                "username": "creator",
                "userid": "173560420",
                "profile_picture": "https://pictures.example.com/img/a",
                "likes_median": 5471442.0,
                "engagement_percent": 0.8149999976158142,
                "posting_frequency_recent_months": 4.670000076293945,
                "income": {"min": 100, "max": 200, "currency": "USD"},
                "tagged": [{"username": "friend", "userid": "1"}],
                # The API derives this list from the followers' audience_brand_affinity below.
                "brand_affinity": [{"name": f"Brand {i}", "interest": ["Music", "Electronics"]} for i in range(40)],
                "audience": {
                    "audience_followers": {
                        "success": True,
                        "data": {
                            "audience_credibility": 0.749321,
                            "audience_geo": {
                                "countries": [
                                    {"id": n, "name": name, "code": code, "weight": w}
                                    for n, (name, code, w) in enumerate(
                                        [("Brazil", "BR", 0.125961), ("India", "IN", 0.086049),
                                         ("Italy", "IT", 0.04907), ("Spain", "ES", 0.0205)]
                                    )
                                ],
                                "cities": [{
                                    "id": 9, "name": "Sao Paulo", "coords": {"lat": -23.5, "lon": -46.6},
                                    "weight": 0.011717, "country": {"id": 1, "name": "Brazil", "code": "BR"},
                                }],
                            },
                            "audience_brand_affinity": [brand(i) for i in range(40)],
                            "notable_users": [person(i) for i in range(5)],
                            "audience_lookalikes": [person(i, score=0.144745) for i in range(4)],
                        },
                        "is_hidden": True,
                    },
                    "audience_likers": {
                        "success": True,
                        "data": {"notable_users": [person(0), person(1, False), person(2, False), person(3)]},
                    },
                    "audience_commenters": {"success": False, "error": "empty_audience"},
                },
                "sponsored_posts": [post(i, LONG_CAPTION) for i in range(4)],
                "past_sponsors": [{"handle": "brand_x", "post_count": 3, "post_ids": ["1", "2", "3"]}],
                "post_data": [post(i) for i in range(4)] + [post(9, LONG_CAPTION)],
            },
            "email": "a@b.c",
            "other_links": [f"https://example.com/{i}" for i in range(LINK_LIMIT + 5)],
            "lookalikes": [{
                "username": "similar", "profile_url": "https://www.instagram.com/similar",
                "engagement_percent": 0.9599999785423279, "follower_count": 5621158,
            }],
        },
        "credits_cost": 1.0,
    }


def compact(sections=ENRICH_SECTIONS) -> dict:
    return shape_result(response(), list(sections), ENRICH_SECTIONS, "compact")


def text_of(value) -> str:
    return json.dumps(value)


def test_every_section_comes_by_default():
    assert validate_sections(None, ENRICH_SECTIONS, None) == list(ENRICH_SECTIONS)
    assert validate_sections(None, ENRICH_ANALYTICS_SECTIONS, None) == list(ENRICH_ANALYTICS_SECTIONS)

    result = compact()["result"]
    instagram = result["instagram"]
    for key in ("audience", "sponsored_posts", "past_sponsors", "post_data", "income"):
        assert key in instagram
    assert result["email"] == "a@b.c"
    assert result["lookalikes"] == [{"username": "similar", "engagement_percent": 0.96, "follower_count": 5621158}]


def test_compact_leaves_out_what_a_model_cannot_use():
    out = compact()
    text = text_of(out["result"])

    for gone in ("profile_picture", "userid", "user_id", "picture", "coords", "stats",
                 "profile_url", "cdn.example.com", "img.example.com", "media_id"):
        assert gone not in text
    assert "brand_affinity" not in out["result"]["instagram"]
    assert out["result"]["instagram"]["tagged"] == ["friend"]
    assert out["notes"][0].startswith("Left out: image and video links, profile links, internal IDs other than post IDs")
    assert any(n.startswith("instagram.brand_affinity left out") for n in out["notes"])


def test_the_creator_level_brand_list_stays_when_it_is_the_only_one():
    failed = response()
    failed["result"]["instagram"]["audience"]["audience_followers"] = {"success": False, "error": "empty_audience"}

    out = shape_result(failed, list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact")
    brands = out["result"]["instagram"]["brand_affinity"]
    assert brands["columns"] == ["name", "interest"] and len(brands["rows"]) == 40
    assert not any("brand_affinity left out" in n for n in out["notes"])


def test_the_creator_level_brand_list_stays_when_it_differs_from_the_followers():
    """Only an exact repeat of the followers' brands is left out; anything else is data."""
    differs = response()
    differs["result"]["instagram"]["brand_affinity"][1]["interest"] = ["Music"]

    for detail in ("compact", "full"):
        out = shape_result(differs, list(ENRICH_SECTIONS), ENRICH_SECTIONS, detail)
        assert out["result"]["instagram"]["brand_affinity"]["rows"][1] == ["Brand 1", ["Music"]]
        assert not any("brand_affinity left out" in n for n in out["notes"])


def test_counts_stay_exact_and_only_decimals_are_rounded():
    instagram = compact()["result"]["instagram"]

    assert instagram["likes_median"] == 5471442 and isinstance(instagram["likes_median"], int)
    assert instagram["engagement_percent"] == 0.815
    assert instagram["posting_frequency_recent_months"] == 4.67
    assert instagram["income"] == {"min": 100, "max": 200, "currency": "USD"}
    followers = instagram["audience"]["audience_followers"]
    assert followers["data"]["audience_credibility"] == 0.7493
    assert followers["is_hidden"] is True


def test_lists_of_objects_become_tables():
    instagram = compact()["result"]["instagram"]
    geo = instagram["audience"]["audience_followers"]["data"]["audience_geo"]

    assert geo["countries"] == {
        "columns": ["name", "code", "weight"],
        "rows": [["Brazil", "BR", 0.126], ["India", "IN", 0.08605], ["Italy", "IT", 0.04907], ["Spain", "ES", 0.0205]],
    }
    # Fewer than four objects stay objects; a nested country becomes its code only in a table row.
    assert geo["cities"] == [{"name": "Sao Paulo", "weight": 0.01172, "country": {"name": "Brazil", "code": "BR"}}]

    posts = instagram["post_data"]
    assert posts["columns"] == [
        "post_id", "created_at", "caption", "post_url", "media", "engagement.likes", "engagement.comments",
    ]
    assert posts["rows"][0] == ["0", "2026-09-23T19:33:27", "hi", "https://instagram.com/p/0", ["image"], 3111179, 35600]

    notable = instagram["audience"]["audience_followers"]["data"]["notable_users"]
    assert notable["columns"] == ["username", "followers", "fullname", "is_verified", "engagements", "country"]
    assert notable["rows"][0] == ["account0", 344306896, "Account 0", True, 1231033, "BR"]
    lookalikes = instagram["audience"]["audience_followers"]["data"]["audience_lookalikes"]
    assert lookalikes["columns"] == ["username", "followers", "fullname", "is_verified", "engagements", "score", "country"]


def test_people_keep_every_metric_their_platform_reports():
    """A YouTube-shaped account: its own metric names, stats per post type, city."""
    geo = {"city": {"id": 7, "name": "Mexico City", "coords": {"lat": 19.4, "lon": -99.1}},
           "country": {"id": 1, "name": "Mexico", "code": "MX", "coords": {"lat": 19.4, "lon": -99.1}}}
    stats = [{"post_type": "all", "engagements": 669701, "avg_likes": 604210, "avg_views": 18989600},
             {"post_type": "shorts", "engagements": 88000, "avg_likes": 80000, "avg_views": 2500000}]
    accounts = [
        person(i, handle=f"channel{i}", custom_name=f"Channel{i}", avg_likes=604210, avg_views=18989600, geo=geo, stats=stats)
        for i in range(4)
    ]
    shaped = shape_result(
        {"result": {"youtube": {"audience": {"audience_followers": {"data": {"notable_users": accounts}}}}}},
        list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact",
    )

    table = shaped["result"]["youtube"]["audience"]["audience_followers"]["data"]["notable_users"]
    assert table["columns"] == [
        "username", "followers", "fullname", "is_verified", "engagements", "handle", "custom_name",
        "avg_likes", "avg_views", "shorts_engagements", "shorts_avg_likes", "shorts_avg_views", "country", "city",
    ]
    assert table["rows"][0] == [
        "account0", 344306896, "Account 0", True, 1231033, "channel0", "Channel0",
        604210, 18989600, 88000, 80000, 2500000, "MX", "Mexico City",
    ]


def test_post_ids_stay_so_sponsors_link_to_posts():
    instagram = compact()["result"]["instagram"]

    assert instagram["past_sponsors"] == [{"handle": "brand_x", "post_count": 3, "post_ids": ["1", "2", "3"]}]
    assert instagram["sponsored_posts"]["columns"][0] == "post_id"
    assert [row[0] for row in instagram["sponsored_posts"]["rows"]] == ["0", "1", "2", "3"]


def test_the_largest_notable_likers_stand_in_when_none_is_verified():
    fans = [person(i, verified=False) for i in range(12)]  # followers fall with i
    shaped = shape_result(
        {"result": {"instagram": {"audience": {"audience_likers": {"data": {"notable_users": fans}}}}}},
        list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact",
    )

    table = shaped["result"]["instagram"]["audience"]["audience_likers"]["data"]["notable_users"]
    assert [row[0] for row in table["rows"]] == [f"account{i}" for i in range(10)]
    assert shaped["notes"][1:] == [
        "instagram.audience.audience_likers.data.notable_users: none verified; the 10 largest of 12 accounts.",
    ]


def test_sections_that_cancel_out_are_refused_before_the_call():
    with pytest.raises(ValueError, match="No section left"):
        validate_sections(["lookalikes"], ENRICH_SECTIONS, include_lookalikes=False)


def test_a_nested_object_in_a_table_keeps_its_other_fields():
    states = [
        {"id": i, "name": name, "weight": 0.01, "country": {"id": 1, "name": "United States", "code": "US"}}
        for i, name in enumerate(["New York", "California", "Texas", "Florida"])
    ]
    shaped = shape_result(
        {"result": {"instagram": {"audience": {"audience_followers": {"data": {"audience_geo": {"states": states}}}}}}},
        list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact",
    )
    table = shaped["result"]["instagram"]["audience"]["audience_followers"]["data"]["audience_geo"]["states"]
    assert table["columns"] == ["name", "weight", "country"]
    assert table["rows"][0] == ["New York", 0.01, "US"]


def test_a_nested_table_stays_one_cell():
    """A post with several coauthors: their list becomes a table inside the coauthors
    cell, not stray `columns` and `rows` columns on the posts table."""
    coauthors = [{"username": f"friend{i}", "full_name": f"Friend {i}", "is_verified": True} for i in range(4)]
    posts = [post(i) for i in range(3)] + [{**post(3), "coauthors": coauthors}]
    shaped = shape_result({"result": {"instagram": {"post_data": posts}}}, list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact")

    table = shaped["result"]["instagram"]["post_data"]
    assert table["columns"] == [
        "post_id", "created_at", "caption", "post_url", "media", "engagement.likes", "engagement.comments", "coauthors",
    ]
    assert table["rows"][3][-1] == {
        "columns": ["username", "full_name", "is_verified"],
        "rows": [[f"friend{i}", f"Friend {i}", True] for i in range(4)],
    }


def test_nested_fields_keep_their_parent_in_the_column_name():
    """Rows nesting different objects would otherwise feed one bare `count` column from both."""
    posts = [{"engagement": {"count": i}, "views": {"count": 10 * i}} for i in range(3)] + [{"views": {"count": 503}}]
    shaped = shape_result({"result": {"instagram": {"post_data": posts}}}, list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact")

    table = shaped["result"]["instagram"]["post_data"]
    assert table["columns"] == ["engagement.count", "views.count"]
    assert table["rows"][3] == [None, 503]


def test_a_twitch_video_keeps_its_id():
    """Ids inside lists are internal, except a Twitch video's: twitch.tv/videos/<id> is its only link."""
    videos = [
        {"__typename": "Video", "id": str(100 + i), "videoTitle": f"stream {i}", "videoViewCount": i,
         "game": {"__typename": "Game", "id": "5", "name": "Just Chatting"}}
        for i in range(4)
    ]
    shaped = shape_result({"result": {"twitch": {"post_data": [{"data": {"channel": {"videos": videos}}}]}}},
                          list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact")

    table = shaped["result"]["twitch"]["post_data"][0]["data"]["channel"]["videos"]
    assert table["columns"] == ["id", "videoTitle", "videoViewCount", "game"]
    assert table["rows"][0] == ["100", "stream 0", 0, "Just Chatting"]


def test_one_sparse_brand_keeps_the_brand_table():
    """Only a list whose every item collapses to a name becomes a list of names."""
    brands = [brand(i) for i in range(20)]
    brands[3] = {"id": 3, "name": "Brand 3"}
    shaped = shape_result(
        {"result": {"instagram": {"audience": {"audience_followers": {"data": {"audience_brand_affinity": brands}}}}}},
        list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact",
    )

    table = shaped["result"]["instagram"]["audience"]["audience_followers"]["data"]["audience_brand_affinity"]
    assert table["columns"] == ["name", "interest", "weight", "affinity"]
    assert len(table["rows"]) == 20
    assert table["rows"][3] == ["Brand 3", None, None, None]


def test_one_sparse_brand_does_not_disable_the_trim():
    sample = response()
    brands = sample["result"]["instagram"]["audience"]["audience_followers"]["data"]["audience_brand_affinity"]
    brands[0] = {"id": 0, "name": "Brand 0"}  # no weight, and it shapes to a bare string
    brands[1]["weight"] = "0.9"  # a string among the floats

    out = shape_result(sample, list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact")
    table = out["result"]["instagram"]["audience"]["audience_followers"]["data"]["audience_brand_affinity"]
    assert len(table["rows"]) == BRAND_LIMIT
    assert {"Brand 0", "Brand 1"}.isdisjoint(row[0] for row in table["rows"])
    assert any(n.endswith("top 30 of 40 brands by weight.") for n in out["notes"])


def test_a_narrowed_result_says_which_parts_held_nothing():
    twitch = {"result": {"twitch": {"avg_views": 10.0, "has_merch": False}}, "credits_cost": 0.8}
    out = shape_result(twitch, ["audience", "sponsors"], ENRICH_ANALYTICS_SECTIONS, "compact")

    assert out["result"] == {}
    assert out["notes"][1:] == ["audience, sponsors: no data for this creator."]

    # The same on the raw level, which otherwise carries no notes.
    raw = shape_result(twitch, ["audience"], ENRICH_ANALYTICS_SECTIONS, "raw")
    assert raw == {"result": {}, "credits_cost": 0.8, "notes": ["audience: no data for this creator."]}

    # A section that came back as an empty list holds nothing either.
    listed = {"result": {"twitch": {"avg_views": 10.0, "sponsored_posts": []}, "lookalikes": []}, "credits_cost": 0.8}
    out = shape_result(listed, ["sponsored_posts", "lookalikes"], ENRICH_ANALYTICS_SECTIONS, "compact")
    assert out["result"] == {"twitch": {"sponsored_posts": []}, "lookalikes": []}
    assert out["notes"][1:] == ["sponsored_posts, lookalikes: no data for this creator."]

    # Leaving the lookalikes out is not narrowing: nothing was asked for by name.
    without = validate_sections(None, ENRICH_ANALYTICS_SECTIONS, include_lookalikes=False)
    assert shape_result(twitch, without, ENRICH_ANALYTICS_SECTIONS, "compact")["notes"][1:] == []


def test_odd_types_in_the_api_response_do_not_fail_the_shaping():
    odd = response()
    instagram = odd["result"]["instagram"]
    instagram["audience"]["audience_followers"]["data"]["notable_users"][0]["geo"] = "Brazil"
    instagram["audience"]["audience_likers"]["data"]["notable_users"] = [
        person(i, verified=False, followers="many") for i in range(12)
    ]
    odd["result"]["youtube"] = {"audience": ["unexpected"], "brand_affinity": [{"name": "Brand 1"}]}

    out = shape_result(odd, list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact")
    notable = out["result"]["instagram"]["audience"]["audience_followers"]["data"]["notable_users"]
    assert notable["rows"][0][notable["columns"].index("country")] is None
    assert len(out["result"]["instagram"]["audience"]["audience_likers"]["data"]["notable_users"]["rows"]) == 10
    assert out["result"]["youtube"] == {"audience": ["unexpected"], "brand_affinity": ["Brand 1"]}


def test_a_shaping_bug_returns_the_data_as_it_came(monkeypatch):
    """The credit is spent by the time the result is shaped, so a bug must not cost it."""
    monkeypatch.setattr(enrich_results._Shaper, "result", lambda self, result: 1 / 0)

    out = shape_result(response(), list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact")
    assert out["result"] == response()["result"]
    assert out["notes"] == ["Returned as it came: shaping it failed."]


def test_shape_result_checks_the_detail_itself():
    assert shape_result(response(), list(ENRICH_SECTIONS), ENRICH_SECTIONS, "RAW") == response()
    with pytest.raises(ValueError, match="Unknown detail 'compat'"):
        shape_result(response(), list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compat")
    with pytest.raises(ValueError, match="Unknown detail 'None'"):
        shape_result(response(), list(ENRICH_SECTIONS), ENRICH_SECTIONS, None)


def test_text_the_wire_cannot_carry_goes_out_escaped(monkeypatch):
    """A lone UTF-16 surrogate (a caption cut mid-emoji upstream) is not UTF-8; the
    transport would fail to send it as a character, so that result goes out escaped."""
    sample = response()
    sample["result"]["instagram"]["post_data"][0]["caption"] = "cut emoji \ud83d"

    async def post(path: str, body: dict, timeout: float | None = None):
        return sample

    monkeypatch.setattr(server.client, "post", post)
    text = asyncio.run(server.enrich_by_handle(handle="creator", platform="instagram"))

    text.encode("utf-8")  # what the transport does
    assert json.loads(text)["result"]["instagram"]["post_data"]["rows"][0][2] == "cut emoji \ud83d"


def test_a_section_on_its_own_keeps_the_path_down_to_its_lists():
    out = compact(["audience_brands"])

    instagram = out["result"]["instagram"]
    assert set(instagram) == {"audience"}  # the creator-level copy of the brands goes, with its note
    assert set(instagram["audience"]) == {"audience_followers"}  # the likers' slice holds no brands here
    followers = instagram["audience"]["audience_followers"]
    assert set(followers) == {"data"} and set(followers["data"]) == {"audience_brand_affinity"}
    assert len(followers["data"]["audience_brand_affinity"]["rows"]) == BRAND_LIMIT
    assert "email" not in out["result"]
    assert any(n.startswith("instagram.brand_affinity left out") for n in out["notes"])


def test_the_audience_lookalikes_section_stands_alone():
    out = compact(["audience_lookalikes"])

    assert set(out["result"]) == {"instagram"}
    followers = out["result"]["instagram"]["audience"]["audience_followers"]
    assert set(followers) == {"data"} and set(followers["data"]) == {"audience_lookalikes"}
    table = followers["data"]["audience_lookalikes"]
    assert table["columns"] == ["username", "followers", "fullname", "is_verified", "engagements", "score", "country"]
    assert len(table["rows"]) == 4
    assert out["notes"] == [out["notes"][0]]


def test_links_to_media_files_go_whatever_the_field_is_called():
    shaped = shape_result({"result": {"youtube": {
        "link": "https://www.youtube.com/@creator",
        "banner_url": "https://yt3.ggpht.com/abc=w1060",
        "cover": "https://example.com/files/cover.webp?v=2",
        "trailer": "https://cdn.example.com/trailer.mp4",
        "post_data": [{"post_url": "https://www.youtube.com/watch?v=1", "media": "https://i.ytimg.com/vi/1/hq.jpg"},
                      {"post_url": "https://www.youtube.com/watch?v=2", "media": "https://example.com/media/2"}],
    }}}, list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact")

    assert shaped["result"]["youtube"] == {
        "link": "https://www.youtube.com/@creator",
        "post_data": [{"post_url": "https://www.youtube.com/watch?v=1"}, {"post_url": "https://www.youtube.com/watch?v=2"}],
    }


def test_captions_that_fit_are_left_as_they_are():
    short = "line one\n\nline two  #tag"
    shaped = shape_result({"result": {"instagram": {"post_data": [{"caption": short}, {"caption": LONG_CAPTION}]}}},
                          list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact")

    posts = shaped["result"]["instagram"]["post_data"]
    assert posts[0]["caption"] == short
    assert posts[1]["caption"] == LONG_CAPTION[: CAPTION_LIMIT - 1].rstrip() + "…"
    assert shaped["notes"][1:] == ["instagram.post_data: 1 of 2 captions cut to 120 characters."]


def test_compact_trims_the_long_tails_and_notes_each_cut():
    out = compact()
    instagram = out["result"]["instagram"]
    data = instagram["audience"]["audience_followers"]["data"]

    brands = data["audience_brand_affinity"]
    assert brands["columns"] == ["name", "interest", "weight", "affinity"]
    assert len(brands["rows"]) == BRAND_LIMIT
    assert brands["rows"][0] == ["Brand 39", ["Music", "Electronics"], 0.049, 1.09]
    assert [r[0] for r in brands["rows"]][-1] == "Brand 10"

    likers = instagram["audience"]["audience_likers"]["data"]["notable_users"]
    assert likers == [
        {"username": "account0", "fullname": "Account 0", "followers": 344306896, "engagements": 1231033,
         "is_verified": True, "country": "BR"},
        {"username": "account3", "fullname": "Account 3", "followers": 344306893, "engagements": 1231033,
         "is_verified": True, "country": "BR"},
    ]

    captions = [row[2] for row in instagram["sponsored_posts"]["rows"]]
    assert all(len(c) == CAPTION_LIMIT and c.endswith("…") for c in captions)
    assert len(out["result"]["other_links"]) == LINK_LIMIT

    assert out["notes"][1:] == [
        "instagram.brand_affinity left out: the same brands as the followers' audience_brand_affinity, without the weights.",
        "instagram.audience.audience_followers.data.audience_brand_affinity: top 30 of 40 brands by weight.",
        "instagram.audience.audience_likers.data.notable_users: the 2 verified of 4 accounts.",
        "instagram.sponsored_posts: 4 of 4 captions cut to 120 characters.",
        "instagram.post_data: 1 of 5 captions cut to 120 characters.",
        "other_links: the first 30 of 35 links.",
    ]


def test_notes_never_ask_for_another_call():
    """The old "omitted sections held data, name them to get them" note is what made a
    model call again, paying a second time for the same report."""
    notes = " ".join(compact()["notes"]).lower()
    for word in ("detail", "sections", "call", "ask", "request"):
        assert word not in notes


def test_full_keeps_every_entry():
    out = shape_result(response(), list(ENRICH_SECTIONS), ENRICH_SECTIONS, "full")
    instagram = out["result"]["instagram"]

    assert len(instagram["audience"]["audience_followers"]["data"]["audience_brand_affinity"]["rows"]) == 40
    assert len(instagram["audience"]["audience_likers"]["data"]["notable_users"]["rows"]) == 4
    assert instagram["sponsored_posts"]["rows"][0][2] == LONG_CAPTION
    assert len(out["result"]["other_links"]) == LINK_LIMIT + 5
    assert "profile_picture" not in text_of(out)
    assert [n.split(":")[0] for n in out["notes"]] == ["Left out", "instagram.brand_affinity left out"]


def test_raw_returns_the_api_response_untouched():
    assert shape_result(response(), list(ENRICH_SECTIONS), ENRICH_SECTIONS, "raw") == response()


def test_sections_narrow_any_detail():
    sections = validate_sections(["audience"], ENRICH_SECTIONS, None)
    assert sections == ["audience"]

    raw = shape_result(response(), sections, ENRICH_SECTIONS, "raw")["result"]
    assert set(raw) == {"instagram"} and set(raw["instagram"]) == {"audience"}
    followers = raw["instagram"]["audience"]["audience_followers"]["data"]
    assert set(followers) == {"audience_credibility", "audience_geo"}

    out = shape_result(response(), sections, ENRICH_SECTIONS, "compact")
    assert set(out["result"]["instagram"]) == {"audience"}
    assert out["notes"] == [out["notes"][0]]


def test_graphql_connections_and_media_are_flattened():
    twitch = {"result": {"twitch": {"post_data": [{
        "data": {"channel": {"id": "1", "login": "streamer", "videoShelves": {"__typename": "Connection", "edges": [
            {"node": {"id": "s1", "title": "Featured Clips", "items": [
                {"__typename": "Clip", "id": str(i), "clipTitle": f"clip {i}", "clipViewCount": i,
                 "thumbnailURL": "https://static.example.com/t.jpg",
                 "game": {"id": "5", "slug": "just-chatting", "displayName": "Just Chatting",
                          "name": "Just Chatting", "boxArtURL": "https://static.example.com/b.jpg"}}
                for i in range(4)
            ]}},
        ]}}},
        "extensions": {"requestID": "abc"},
    }]}}, "credits_cost": 1.0}
    youtube = {"result": {"youtube": {"id": "UC123", "post_data": [
        {"video_id": "v", "title": "t", "media": {"thumbnails": {"high": "https://i.example.com/h.jpg"},
                                                   "duration": "PT40S", "definition": "hd"}}
    ]}}, "credits_cost": 1.0}

    shaped = shape_result(twitch, list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact")["result"]["twitch"]
    shelf = shaped["post_data"][0]["data"]["channel"]["videoShelves"][0]
    assert shelf["title"] == "Featured Clips"
    # The game becomes its name; displayName only repeats it, the slug does not.
    assert shelf["items"] == {
        "columns": ["clipTitle", "clipViewCount", "game", "game.slug"],
        "rows": [[f"clip {i}", i, "Just Chatting", "just-chatting"] for i in range(4)],
    }
    assert "extensions" not in shaped["post_data"][0]

    shaped = shape_result(youtube, list(ENRICH_SECTIONS), ENRICH_SECTIONS, "compact")["result"]["youtube"]
    assert shaped == {
        "id": "UC123",
        "post_data": [{"video_id": "v", "title": "t", "media": {"duration": "PT40S", "definition": "hd"}}],
    }


def test_section_names_are_checked():
    assert validate_sections(["sponsors", "audience"], ENRICH_SECTIONS, None) == ["audience", "sponsors"]
    assert validate_sections(["audience"], ENRICH_SECTIONS, True) == ["audience", "lookalikes"]
    assert "lookalikes" not in validate_sections(None, ENRICH_SECTIONS, False)

    with pytest.raises(ValueError, match="Unknown sections: nope, posts"):
        validate_sections(["posts", "nope"], ENRICH_ANALYTICS_SECTIONS, None)


@pytest.fixture
def api(monkeypatch):
    """The dashboard API answering every enrichment with the sample; records the calls."""
    calls: list[tuple[str, dict]] = []

    async def post(path: str, body: dict, timeout: float | None = None):
        calls.append((path, body))
        return response()

    monkeypatch.setattr(server.client, "post", post)
    return calls


def test_the_analytics_tool_returns_compact_json(api):
    text = asyncio.run(server.enrich_by_handle_analytics(handle="creator", platform="instagram"))

    out = json.loads(text)
    assert text == json.dumps(out, separators=(",", ":"), ensure_ascii=False)
    assert "…" in text  # a cut caption's ellipsis as one character, not a six-character escape
    assert "sponsored_posts" in out["result"]["instagram"]
    assert out["notes"][0].startswith("Left out")
    assert api == [(
        f"{server.API_V1}/creators/enrich/handle/analytics/",
        {"handle": "creator", "platform": "instagram", "include_lookalikes": True},
    )]


def test_the_full_tool_can_return_the_raw_response(api):
    text = asyncio.run(server.enrich_by_handle(handle="creator", platform="instagram", detail="raw"))

    assert json.loads(text) == response()
    assert api[0][0] == f"{server.API_V1}/creators/enrich/handle/full/"


def test_the_profile_tool_leaves_out_image_links(api):
    text = asyncio.run(server.enrich_by_handle_profile(handle="creator", platform="instagram"))

    out = json.loads(text)
    instagram = out["result"]["instagram"]
    assert "\n" not in text and "profile_picture" not in text
    assert instagram["username"] == "creator"
    assert instagram["userid"] == "173560420"  # the account's own ID is part of an identity
    assert instagram["tagged"] == ["friend"]  # other accounts' IDs still go
    assert len(out["result"]["other_links"]) == LINK_LIMIT
    assert out["notes"] == [
        "Left out: image links and internal IDs other than the account's own.",
        "instagram.brand_affinity left out: the same brands as the followers' audience_brand_affinity, without the weights.",
        "instagram.audience.audience_followers.data.audience_brand_affinity: top 30 of 40 brands by weight.",
        "instagram.audience.audience_likers.data.notable_users: the 2 verified of 4 accounts.",
        "instagram.sponsored_posts: 4 of 4 captions cut to 120 characters.",
        "instagram.post_data: 1 of 5 captions cut to 120 characters.",
        "other_links: the first 30 of 35 links.",
    ]
    assert api[0][0] == f"{server.API_V1}/creators/enrich/handle/profile/"


def test_the_profile_tool_returns_every_link_on_request(api):
    full = json.loads(asyncio.run(server.enrich_by_handle_profile(handle="creator", platform="instagram", detail="full")))
    assert len(full["result"]["other_links"]) == LINK_LIMIT + 5
    assert "profile_picture" not in json.dumps(full)
    assert not any("other_links" in n for n in full["notes"])

    raw = json.loads(asyncio.run(server.enrich_by_handle_profile(handle="creator", platform="instagram", detail="raw")))
    assert raw == response()


def test_the_full_tool_can_return_posts_alone(api):
    text = asyncio.run(server.enrich_by_handle(handle="creator", platform="instagram", sections=["posts"]))

    out = json.loads(text)
    assert set(out["result"]) == {"instagram"} and set(out["result"]["instagram"]) == {"post_data"}
    assert len(out["result"]["instagram"]["post_data"]["rows"]) == 5
    assert api[0][1]["include_lookalikes"] is False


@pytest.mark.parametrize(
    "tool", [server.enrich_by_handle_analytics, server.enrich_by_handle], ids=["analytics", "full"]
)
@pytest.mark.parametrize(
    ("arguments", "computed"),
    [
        ({}, True),
        ({"include_lookalikes": False}, False),
        ({"sections": ["audience_lookalikes"]}, False),
        ({"sections": ["lookalikes"]}, True),
        ({"sections": ["audience"], "include_lookalikes": True}, True),
    ],
    ids=["default", "switched-off", "audience-lookalikes", "lookalikes-section", "include-flag"],
)
def test_the_api_computes_lookalikes_only_when_that_section_is_wanted(api, tool, arguments, computed):
    asyncio.run(tool(handle="creator", platform="instagram", **arguments))

    assert api[0][1]["include_lookalikes"] is computed


def list_tools() -> dict:
    async def scenario():
        async with create_connected_server_and_client_session(server.mcp) as client:
            return {tool.name: tool for tool in (await client.list_tools()).tools}

    return asyncio.run(scenario())


def test_the_two_large_result_tools_list_their_sections_and_raise_their_client_ceiling():
    tools = list_tools()
    for name, sections in (("enrich_by_handle", ENRICH_SECTIONS), ("enrich_by_handle_analytics", ENRICH_ANALYTICS_SECTIONS)):
        properties = tools[name].inputSchema["properties"]
        items = properties["sections"]["anyOf"][0]["items"]
        assert items["enum"] == list(sections)
        assert properties["detail"]["enum"] == ["compact", "full", "raw"]
        assert properties["detail"]["default"] == "compact"
        assert tools[name].meta == {"anthropic/maxResultSizeChars": 500_000}
    assert tools["enrich_by_handle_profile"].meta is None


def call_analytics(**arguments) -> dict:
    """The analytics tool called through the protocol, as a client's text arrives."""
    async def scenario():
        async with create_connected_server_and_client_session(server.mcp) as client:
            return await client.call_tool(
                "enrich_by_handle_analytics", {"handle": "creator", "platform": "instagram", **arguments}
            )

    result = asyncio.run(scenario())
    assert result.isError is False  # errors travel as the JSON envelope, never as plain text
    return json.loads(result.content[0].text)


def test_a_wrong_section_or_detail_is_refused_as_json_before_the_api_is_billed(api):
    assert call_analytics(sections=["posts"])["error"] is True
    assert call_analytics(detail="compat")["error"] is True
    assert api == []


def test_section_and_detail_names_are_matched_regardless_of_case(api):
    out = call_analytics(sections=[" Audience "], detail="RAW")

    assert set(out["result"]["instagram"]) == {"audience"}
    assert "notes" not in out
    assert len(api) == 1


def test_names_still_in_their_quotes_are_accepted(api):
    out = call_analytics(sections='"audience"', detail="'Compact'")

    assert set(out["result"]["instagram"]) == {"audience"}
    assert len(api) == 1


def test_a_bare_section_name_and_a_null_detail_are_accepted(api):
    """Two common slips a model makes, taken as the one-item list and the default."""
    out = call_analytics(sections="audience", detail=None)

    assert set(out["result"]["instagram"]) == {"audience"}
    assert out["notes"] == [out["notes"][0]]
    assert len(api) == 1


def test_results_are_sent_once_as_plain_text(api):
    """No inferred output schema, no structuredContent wrapper around the JSON text."""
    async def scenario():
        async with create_connected_server_and_client_session(server.mcp) as client:
            tools = (await client.list_tools()).tools
            result = await client.call_tool(
                "enrich_by_handle_analytics", {"handle": "creator", "platform": "instagram"}
            )
            return tools, result

    tools, result = asyncio.run(scenario())
    assert tools and all(tool.outputSchema is None for tool in tools)
    assert result.structuredContent is None
    assert len(result.content) == 1
    assert "instagram" in json.loads(result.content[0].text)["result"]
