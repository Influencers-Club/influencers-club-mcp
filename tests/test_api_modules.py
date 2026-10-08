"""The endpoint groups on the API client send exactly the requests server.py used to
build itself: same verb, address, query, body and timeout for each operation."""

import asyncio
import csv
import io
import json

import httpx
import pytest

from influencers_club_mcp import csv_export
from influencers_club_mcp.api_account import AccountApi
from influencers_club_mcp.api_batch import BatchApi
from influencers_club_mcp.api_client import InfluencersApiClient
from influencers_club_mcp.api_content import ContentApi
from influencers_club_mcp.api_discovery import DiscoveryApi
from influencers_club_mcp.api_enrichment import EnrichmentApi

V1 = "/public/v1"


class Transport:
    """Records what each endpoint group asks the client to send."""

    def __init__(self):
        self.calls = []

    async def get(self, path, params=None, timeout=None):
        self.calls.append(("GET", path, params, None, timeout))
        return {}

    async def post(self, path, body, timeout=None):
        self.calls.append(("POST", path, None, body, timeout))
        return {}

    async def post_multipart(self, path, files, data, timeout=None):
        self.calls.append(("MULTIPART", path, data, files, timeout))
        return {}


def sent(coro, transport):
    asyncio.run(coro)
    assert len(transport.calls) == 1
    return transport.calls[0]


def test_discovery_search_and_similar():
    t = Transport()
    api = DiscoveryApi(t)
    f = {"number_of_followers": {"min": 1000}}
    assert sent(api.search("instagram", f, page=2, limit=20, sort_by="relevancy", sort_order="desc"), t) == (
        "POST", f"{V1}/discovery/", None,
        {"platform": "instagram", "paging": {"limit": 20, "page": 2}, "sort": {"sort_by": "relevancy", "sort_order": "desc"}, "filters": f},
        None,
    )
    t.calls.clear()
    assert sent(api.search("tiktok", {}, page=0, limit=5, sort_by="relevancy", sort_order="desc"), t)[3]["filters"] is None
    t.calls.clear()
    assert sent(api.similar("youtube", "username", "nike", {}, page=0, limit=10), t) == (
        "POST", f"{V1}/discovery/creators/similar/", None,
        {"platform": "youtube", "filter_key": "username", "filter_value": "nike", "paging": {"limit": 10, "page": 0}},
        None,
    )
    t.calls.clear()
    assert sent(api.similar("youtube", "url", "u", f, page=1, limit=1), t)[3]["filters"] == f


def test_discovery_overlap_and_lookups():
    t = Transport()
    api = DiscoveryApi(t)
    assert sent(api.audience_overlap("instagram", ["a", "b"]), t) == (
        "POST", f"{V1}/creators/audience/overlap/", None, {"platform": "instagram", "creators": ["a", "b"]}, None
    )
    expected = {
        api.languages(): "languages/",
        api.locations("twitch"): "locations/twitch/",
        api.youtube_topics(): "yt-topics/",
        api.games(): "games/",
        api.brands(): "brands/",
        api.audience_brand_categories(): "audience-brand-categories/",
        api.audience_brand_names(): "audience-brand-names/",
        api.audience_interests(): "audience-interests/",
        api.audience_locations(): "audience-locations/",
    }
    for coro, tail in expected.items():
        t.calls.clear()
        assert sent(coro, t) == ("GET", f"{V1}/discovery/classifier/{tail}", None, None, None)
    t.calls.clear()
    assert sent(api.brands(" nike ", 40), t)[2] == {"search": "nike", "offset": "40"}
    t.calls.clear()
    assert sent(api.audience_interests(offset=0), t)[2] == {"offset": "0"}
    t.calls.clear()
    assert sent(api.audience_locations(search=""), t)[2] is None


def test_enrichment():
    t = Transport()
    api = EnrichmentApi(t)
    assert sent(api.connected_socials("instagram", "nike"), t) == (
        "POST", f"{V1}/creators/socials/", None, {"platform": "instagram", "handle": "nike"}, None
    )
    t.calls.clear()
    assert sent(api.by_handle_full("nike", "instagram", email_required="preferred", include_lookalikes=False, include_audience_data=True), t) == (
        "POST", f"{V1}/creators/enrich/handle/full/", None,
        {"handle": "nike", "platform": "instagram", "email_required": "preferred", "include_lookalikes": False, "include_audience_data": True},
        None,
    )
    t.calls.clear()
    assert sent(api.by_handle_raw("nike", "linkedin"), t) == (
        "POST", f"{V1}/creators/enrich/handle/raw/", None, {"handle": "nike", "platform": "linkedin"}, None
    )
    t.calls.clear()
    assert sent(api.by_email("a@b.c"), t) == ("POST", f"{V1}/creators/enrich/email/", None, {"email": "a@b.c"}, None)


def test_batch():
    t = Transport()
    api = BatchApi(t)
    assert sent(api.create(b"handle\nnike\n", "full", platform="instagram", email_required="preferred", include_lookalikes=False, include_audience_data=True, metadata={"k": 1}), t) == (
        "MULTIPART", f"{V1}/enrichment/batch/",
        {"enrichment_mode": "full", "platform": "instagram", "email_required": "preferred", "include_lookalikes": "false", "include_audience_data": "true", "metadata": '{"k": 1}'},
        {"file": ("batch.csv", b"handle\nnike\n", "text/csv")},
        None,
    )
    t.calls.clear()
    assert sent(api.create(b"email\na@b.c\n", "basic"), t)[2] == {"enrichment_mode": "basic"}
    t.calls.clear()
    assert sent(api.status("abc-123"), t) == ("GET", f"{V1}/enrichment/batch/abc-123/status/", None, None, None)
    t.calls.clear()
    assert sent(api.results("abc-123"), t) == ("GET", f"{V1}/enrichment/batch/abc-123/", {"format": "json"}, None, 120.0)
    t.calls.clear()
    assert sent(api.resume("abc-123"), t) == ("POST", f"{V1}/enrichment/batch/abc-123/resume/", None, {}, None)


def test_content_and_account():
    t = Transport()
    content, account = ContentApi(t), AccountApi(t)
    assert sent(content.posts("tiktok", "nike"), t) == (
        "POST", f"{V1}/creators/content/posts/", None, {"platform": "tiktok", "handle": "nike"}, None
    )
    t.calls.clear()
    assert sent(content.posts("tiktok", "nike", count=12, pagination_token="tok"), t)[3] == {"platform": "tiktok", "handle": "nike", "count": 12, "pagination_token": "tok"}
    t.calls.clear()
    assert sent(content.post_details("youtube", "id1", "transcript"), t) == (
        "POST", f"{V1}/creators/content/details/", None, {"platform": "youtube", "post_id": "id1", "content_type": "transcript"}, None
    )
    t.calls.clear()
    assert sent(content.post_details("youtube", "id1", "comments", pagination_token="n"), t)[3]["pagination_token"] == "n"
    t.calls.clear()
    assert sent(account.credits(), t) == ("GET", f"{V1}/accounts/credits/", None, None, None)


@pytest.mark.parametrize(
    "call",
    [
        lambda: DiscoveryApi(Transport()).locations("instagram/../../accounts/credits"),
        lambda: BatchApi(Transport()).status("1/../../accounts/credits"),
        lambda: BatchApi(Transport()).results("abc?format=csv"),
        lambda: BatchApi(Transport()).resume(""),
        lambda: BatchApi(Transport()).status(".."),
        lambda: DiscoveryApi(Transport()).locations("."),
    ],
)
def test_values_that_become_a_path_segment_are_checked(call):
    with pytest.raises(ValueError):
        asyncio.run(call())


def test_the_real_client_carries_every_group(monkeypatch):
    monkeypatch.setenv("INFLUENCERS_CLUB_API_KEY", "key")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path))
        return httpx.Response(200, json={"ok": True})

    client = InfluencersApiClient()
    client._client = httpx.AsyncClient(base_url="https://api.test", transport=httpx.MockTransport(handler))

    async def scenario():
        await client.discovery.languages()
        await client.enrichment.by_email("a@b.c")
        await client.batch.status("b1")
        await client.content.posts("tiktok", "nike")
        await client.account.credits()
        await client._client.aclose()

    asyncio.run(scenario())
    assert seen == [
        ("GET", f"{V1}/discovery/classifier/languages/"),
        ("POST", f"{V1}/creators/enrich/email/"),
        ("GET", f"{V1}/enrichment/batch/b1/status/"),
        ("POST", f"{V1}/creators/content/posts/"),
        ("GET", f"{V1}/accounts/credits/"),
    ]


# --- the batch CSV helpers that moved here from server.py ---------------------


SAMPLE = [
    {"input_value": "a", "status": "ok", "result": {"email": "x@y", "tags": ["t1", "t2"], "stats": {"n": 1}, "none": None}},
    {"handle": "missing", "status": "not_found"},
    {"handle": "k", "status": "ok", "enrichment_data": {"first_name": "A", "instagram": {"username": "ig", "follower_count": 5}}},
]


def test_json_batch_to_csv_flattens_results_and_renames_input_value_to_handle():
    rows = list(csv.DictReader(io.StringIO(csv_export.json_batch_to_csv(SAMPLE))))
    assert rows[0] == {"status": "ok", "email": "x@y", "tags": '["t1", "t2"]', "stats.n": "1", "none": "", "handle": "a",
                       "first_name": "", "instagram.username": "", "instagram.follower_count": ""}
    assert rows[1]["handle"] == "missing" and rows[1]["status"] == "not_found"
    assert rows[2]["instagram.follower_count"] == "5"
    assert csv_export.json_batch_to_csv({"results": SAMPLE}) == csv_export.json_batch_to_csv(SAMPLE)
    assert csv_export.json_batch_to_csv([]) == "" and csv_export.json_batch_to_csv("nope") == ""


def test_preview_rows_skips_failed_rows_and_picks_platform_columns():
    assert csv_export.preview_rows(SAMPLE) == [
        {"handle": "a"},
        {"handle": "k", "first_name": "A", "instagram.username": "ig", "instagram.follower_count": "5"},
    ]


# --- the tools themselves still send the same requests ---------------------------


class FakeClient(Transport):
    """A client whose transport is recorded but whose endpoint groups are the real ones."""

    def __init__(self, *answers):
        super().__init__()
        self.answers = list(answers)
        self.discovery, self.enrichment, self.batch = DiscoveryApi(self), EnrichmentApi(self), BatchApi(self)
        self.content, self.account = ContentApi(self), AccountApi(self)

    async def get(self, path, params=None, timeout=None):
        await super().get(path, params, timeout)
        return self.answers.pop(0) if self.answers else {}

    async def post(self, path, body, timeout=None):
        await super().post(path, body, timeout)
        return self.answers.pop(0) if self.answers else {}


def test_tools_send_through_the_endpoint_groups(monkeypatch):
    """Every moved tool except the three that write files (to_file, batch create, batch download)."""
    from influencers_club_mcp import server

    fake = FakeClient()
    monkeypatch.setattr(server, "client", fake)

    async def scenario():
        await server.discover_creators(platform="Instagram", limit=3, filters={"number_of_followers": {"min": 10}})
        await server.find_similar_creators(platform="tiktok", filter_value="nike", limit=2)
        await server.get_brands(search="nike", offset=20)
        await server.get_locations(platform="twitch")
        await server.enrich_by_handle_raw(handle="nike", platform="instagram")
        await server.get_creator_posts(platform="youtube", handle="nike", count=5)
        await server.check_credits()
        await server.audience_overlap(platform="instagram", creators=["a", "b"])
        await server.get_languages()
        await server.get_youtube_topics()
        await server.get_games()
        await server.get_audience_brand_categories(search="sport")
        await server.get_audience_brand_names(offset=10)
        await server.get_audience_interests()
        await server.get_audience_locations(search="london", offset=5)
        await server.connected_socials(platform="instagram", handle="nike")
        await server.enrich_by_handle(handle="nike", platform="instagram", email_required="must_have")
        await server.enrich_by_email(email="A@B.co")
        await server.get_post_details(platform="youtube", post_id="vid1", content_type="transcript", pagination_token="t2")
        monkeypatch.setattr(server, "_get_mcp_client_name", lambda: "claude-code")
        await server.get_batch_status(batch_id=" bch_1 ")
        await server.resume_batch(batch_id="bch_1")

    asyncio.run(scenario())
    assert [(c[0], c[1]) for c in fake.calls] == [
        ("POST", f"{V1}/discovery/"),
        ("POST", f"{V1}/discovery/creators/similar/"),
        ("GET", f"{V1}/discovery/classifier/brands/"),
        ("GET", f"{V1}/discovery/classifier/locations/twitch/"),
        ("POST", f"{V1}/creators/enrich/handle/raw/"),
        ("POST", f"{V1}/creators/content/posts/"),
        ("GET", f"{V1}/accounts/credits/"),
        ("POST", f"{V1}/creators/audience/overlap/"),
        ("GET", f"{V1}/discovery/classifier/languages/"),
        ("GET", f"{V1}/discovery/classifier/yt-topics/"),
        ("GET", f"{V1}/discovery/classifier/games/"),
        ("GET", f"{V1}/discovery/classifier/audience-brand-categories/"),
        ("GET", f"{V1}/discovery/classifier/audience-brand-names/"),
        ("GET", f"{V1}/discovery/classifier/audience-interests/"),
        ("GET", f"{V1}/discovery/classifier/audience-locations/"),
        ("POST", f"{V1}/creators/socials/"),
        ("POST", f"{V1}/creators/enrich/handle/full/"),
        ("POST", f"{V1}/creators/enrich/email/"),
        ("POST", f"{V1}/creators/content/details/"),
        ("GET", f"{V1}/enrichment/batch/bch_1/status/"),
        ("POST", f"{V1}/enrichment/batch/bch_1/resume/"),
    ]
    by_path = {c[1]: c for c in fake.calls}
    assert by_path[f"{V1}/discovery/classifier/audience-brand-categories/"][2] == {"search": "sport"}
    assert by_path[f"{V1}/discovery/classifier/audience-brand-names/"][2] == {"offset": "10"}
    assert by_path[f"{V1}/discovery/classifier/audience-interests/"][2] is None
    assert by_path[f"{V1}/discovery/classifier/audience-locations/"][2] == {"search": "london", "offset": "5"}
    assert by_path[f"{V1}/creators/audience/overlap/"][3] == {"platform": "instagram", "creators": ["a", "b"]}
    assert by_path[f"{V1}/creators/socials/"][3] == {"platform": "instagram", "handle": "nike"}
    assert by_path[f"{V1}/creators/enrich/handle/full/"][3] == {
        "handle": "nike", "platform": "instagram", "email_required": "must_have",
        "include_lookalikes": False, "include_audience_data": True,
    }
    assert by_path[f"{V1}/creators/enrich/email/"][3] == {"email": "a@b.co"}
    assert by_path[f"{V1}/creators/content/details/"][3] == {
        "platform": "youtube", "post_id": "vid1", "content_type": "transcript", "pagination_token": "t2",
    }
    search = fake.calls[0][3]
    assert search["platform"] == "instagram" and search["paging"] == {"limit": 3, "page": 0}
    assert search["filters"] == {"number_of_followers": {"min": 10}}
    assert fake.calls[2][2] == {"search": "nike", "offset": "20"}
    assert fake.calls[5][3] == {"platform": "youtube", "handle": "nike", "count": 5}


def test_tools_still_reject_bad_input_before_any_request(monkeypatch):
    from influencers_club_mcp import server

    fake = FakeClient()
    monkeypatch.setattr(server, "client", fake)
    results = [
        json.loads(asyncio.run(server.get_locations(platform="snapchat"))),
        json.loads(asyncio.run(server.enrich_by_email(email="not-an-email"))),
        json.loads(asyncio.run(server.audience_overlap(platform="instagram", creators=["only_one"]))),
    ]
    assert all(r["error"] is True for r in results)
    assert fake.calls == []
