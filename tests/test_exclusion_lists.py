"""Exclusion-list tools send what the API's serializers accept and return its bodies as is.

Shapes are the dashboard's (public_api/discovery_api/v1: ExclusionListSerializer,
ExclusionEntriesResponseSerializer, ExclusionEntriesInputSerializer, and the
exclude_list / exclude_default_list / exclude_all_lists filter keys), as published at
docs.influencers.club/openapi.yaml.
"""

import asyncio
import json

import httpx
import pytest

from influencers_club_mcp import server
from influencers_club_mcp.api_client import ApiError, InfluencersApiClient
from influencers_club_mcp.discovery_filters import coerce_filters

BASE = "/public/v1/discovery/exclusion-lists/"

LIST = {
    "id": 42,
    "name": "Competitors",
    "platform": "instagram",
    "is_default": False,
    "handle_count": 2,
    "created_at": "2026-01-15T09:30:00Z",
    "updated_at": "2026-01-20T14:05:00Z",
}
DEFAULT = {**LIST, "id": 7, "name": "Default", "is_default": True, "handle_count": 0}
TIKTOK = {**LIST, "id": 9, "name": "TikTok blocklist", "platform": "tiktok"}
PAGE = {"total": 2, "offset": 0, "limit": 1000, "handles": ["brand_x", "brand_y"]}
SEARCH = {"total": 0, "limit": 20, "credits_left": "10.00", "accounts": []}


class FakeClient:
    """Records every call and answers each from a queue of canned API bodies."""

    def __init__(self, *answers):
        self.answers = list(answers)
        self.calls = []

    async def _answer(self, method, path, body=None, params=None):
        self.calls.append((method, path, body, params))
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def get(self, path, params=None, timeout=None):
        return await self._answer("GET", path, params=params)

    async def post(self, path, body, timeout=None):
        return await self._answer("POST", path, body)

    async def patch(self, path, body, timeout=None):
        return await self._answer("PATCH", path, body)

    async def delete(self, path, body=None, timeout=None):
        return await self._answer("DELETE", path, body)


@pytest.fixture
def api(monkeypatch):
    def install(*answers):
        fake = FakeClient(*answers)
        monkeypatch.setattr(server, "client", fake)
        return fake

    return install


def run(coro):
    return json.loads(asyncio.run(coro))


# --- filters -----------------------------------------------------------------


def test_filters_accept_the_exclusion_list_keys():
    sent = {"exclude_list": [42, 7], "exclude_default_list": True, "exclude_all_lists": False}
    assert coerce_filters(sent) == sent


def test_filters_still_reject_unknown_keys():
    with pytest.raises(ValueError, match="exclude_lists"):
        coerce_filters({"exclude_lists": [42]})


# --- list / create / rename / delete ------------------------------------------


def test_list_returns_the_api_rows_as_is(api):
    fake = api([LIST, DEFAULT])
    assert run(server.list_exclusion_lists()) == [LIST, DEFAULT]
    assert fake.calls == [("GET", BASE, None, None)]


def test_list_filters_by_platform_on_the_client(api):
    fake = api([LIST, TIKTOK])
    assert run(server.list_exclusion_lists(platform=" TikTok ")) == [TIKTOK]
    assert fake.calls == [("GET", BASE, None, None)]


def test_list_rejects_an_unknown_platform_before_calling(api):
    fake = api()
    result = run(server.list_exclusion_lists(platform="snapchat"))
    assert result["error"] is True and "Invalid platform" in result["message"]
    assert fake.calls == []


def test_create_sends_name_and_platform(api):
    fake = api(LIST)
    assert run(server.create_exclusion_list(name=" Competitors ", platform="Instagram")) == LIST
    assert fake.calls == [("POST", BASE, {"name": "Competitors", "platform": "instagram"}, None)]


def test_rename_patches_the_list(api):
    fake = api({**LIST, "name": "after"})
    assert run(server.rename_exclusion_list(list_id=42, name="after"))["name"] == "after"
    assert fake.calls == [("PATCH", f"{BASE}42/", {"name": "after"}, None)]


def test_delete_reports_the_bodiless_204(api):
    fake = api(None)
    assert run(server.delete_exclusion_list(list_id=42)) == {"deleted": True, "id": 42}
    assert fake.calls == [("DELETE", f"{BASE}42/", None, None)]


# --- one tool per route: a specific list by id, a default list by platform ----------


def test_get_reads_one_list_by_id_or_the_default_by_platform(api):
    fake = api(LIST, DEFAULT)
    assert run(server.get_exclusion_list(list_id=42)) == LIST
    assert run(server.get_default_exclusion_list(platform=" Instagram ")) == DEFAULT
    assert fake.calls == [
        ("GET", f"{BASE}42/", None, None),
        ("GET", f"{BASE}default/instagram/", None, None),
    ]


def test_handles_are_paged_by_id_or_by_default_platform(api):
    fake = api(PAGE, PAGE)
    assert run(server.get_exclusion_list_handles(list_id=42, offset=10, limit=5)) == PAGE
    assert run(server.get_default_exclusion_list_handles(platform="instagram")) == PAGE
    assert fake.calls == [
        ("GET", f"{BASE}42/entries/", None, {"offset": "10", "limit": "5"}),
        ("GET", f"{BASE}default/instagram/entries/", None, {"offset": "0", "limit": "1000"}),
    ]


def test_add_posts_the_handles_the_user_gave(api):
    """Blanks are dropped here; lowercasing, '@' and URL reduction are the API's job."""
    fake = api(LIST, DEFAULT)
    handles = ["@Brand_X", "  ", "https://instagram.com/brand_y"]
    sent = {"handles": ["@Brand_X", "https://instagram.com/brand_y"]}
    assert run(server.add_to_exclusion_list(list_id=42, handles=handles)) == LIST
    assert run(server.add_to_default_exclusion_list(platform="instagram", handles=handles)) == DEFAULT
    assert fake.calls == [
        ("POST", f"{BASE}42/entries/", sent, None),
        ("POST", f"{BASE}default/instagram/entries/", sent, None),
    ]


def test_remove_sends_a_delete_with_a_body(api):
    fake = api(LIST, DEFAULT)
    assert run(server.remove_from_exclusion_list(list_id=42, handles=["brand_x"])) == LIST
    assert run(server.remove_from_default_exclusion_list(platform="instagram", handles=["brand_x"])) == DEFAULT
    assert fake.calls == [
        ("DELETE", f"{BASE}42/entries/", {"handles": ["brand_x"]}, None),
        ("DELETE", f"{BASE}default/instagram/entries/", {"handles": ["brand_x"]}, None),
    ]


def test_a_long_profile_url_is_passed_on_for_the_api_to_reduce(api):
    fake = api(LIST)
    url = "https://www.instagram.com/some.creator/?igsh=" + "a" * 200
    assert run(server.add_to_exclusion_list(list_id=42, handles=["ok", url])) == LIST
    assert fake.calls[0][2] == {"handles": ["ok", url]}


@pytest.mark.parametrize(
    "call",
    [
        lambda: server.get_default_exclusion_list(platform="snapchat"),
        lambda: server.get_default_exclusion_list_handles(platform=""),
        lambda: server.add_to_default_exclusion_list(platform="snapchat", handles=["x"]),
        lambda: server.remove_from_default_exclusion_list(platform="snapchat", handles=["x"]),
    ],
)
def test_default_list_tools_reject_an_unknown_platform_before_calling(api, call):
    fake = api()
    result = run(call())
    assert result["error"] is True and "Invalid platform" in result["message"]
    assert fake.calls == []


def test_only_blank_handles_is_an_error(api):
    fake = api()
    result = run(server.remove_from_exclusion_list(list_id=1, handles=["  ", ""]))
    assert result["error"] is True and "non-empty" in result["message"]
    assert fake.calls == []


def test_api_errors_keep_their_status_and_message(api):
    api(ApiError(404, "Exclusion list not found."))
    result = run(server.get_exclusion_list_handles(list_id=99))
    assert result == {"error": True, "status": 404, "message": "Exclusion list not found.", "retryable": False}


# --- discovery wiring ---------------------------------------------------------


def test_discovery_refuses_list_ids_the_api_would_silently_ignore(api):
    fake = api([LIST, TIKTOK])
    result = run(server.discover_creators(platform="instagram", filters={"exclude_list": [42, 9, 100]}))
    assert result["error"] is True
    assert "[100]" in result["message"] and "9 (tiktok)" in result["message"]
    assert [c[0] for c in fake.calls] == ["GET"]  # no search, no credits spent


def test_discovery_sends_the_exclusion_filters_once_the_ids_check_out(api):
    fake = api([LIST], SEARCH)
    filters = {"exclude_list": [42], "exclude_default_list": True}
    assert run(server.discover_creators(platform="instagram", filters=filters)) == SEARCH
    method, path, body, _ = fake.calls[1]
    assert (method, path) == ("POST", "/public/v1/discovery/")
    assert body["filters"]["exclude_list"] == [42]
    assert body["filters"]["exclude_default_list"] is True


def test_default_and_all_list_flags_need_no_lookup(api):
    fake = api(SEARCH)
    filters = {"exclude_default_list": True, "exclude_all_lists": True}
    assert run(server.discover_creators(platform="tiktok", filters=filters)) == SEARCH
    assert [c[0] for c in fake.calls] == ["POST"]


def test_exclude_all_lists_makes_the_ids_irrelevant(api):
    """The API applies every list for the platform then, so a stray id blocks nothing."""
    fake = api(SEARCH)
    filters = {"exclude_all_lists": True, "exclude_list": [9]}
    assert run(server.discover_creators(platform="instagram", filters=filters)) == SEARCH
    assert [c[0] for c in fake.calls] == ["POST"]


def test_a_failed_lists_lookup_is_reported_as_itself_and_no_search_runs(api):
    """Unverified ids could mean paying for unfiltered results, so nothing is searched."""
    fake = api(ApiError(503, "Service Unavailable", retryable=True))
    result = run(server.discover_creators(platform="instagram", filters={"exclude_list": [42]}))
    assert result == {"error": True, "status": 503, "message": "Service Unavailable", "retryable": True}
    assert [c[0] for c in fake.calls] == ["GET"]


@pytest.mark.parametrize("body", ["<html>proxy</html>", {"data": [LIST]}, [{"name": "no id"}]])
def test_an_unreadable_lists_answer_stops_the_search_without_blaming_the_ids(api, body):
    fake = api(body)
    result = run(server.discover_creators(platform="instagram", filters={"exclude_list": [42]}))
    assert result["error"] is True and "could not be verified" in result["message"]
    assert "not found in your team" not in result["message"]
    assert [c[0] for c in fake.calls] == ["GET"]


def test_tool_descriptions_name_the_platforms_validation_accepts():
    assert server._PLATFORMS_DESC == ", ".join(server.DISCOVERY_PLATFORMS)


def test_file_export_checks_the_ids_before_fetching_anything(api):
    fake = api([LIST])
    result = run(server.discover_creators_to_file(platform="tiktok", filters={"exclude_list": [42]}))
    assert result["error"] is True and "42 (instagram)" in result["message"]
    assert [c[0] for c in fake.calls] == ["GET"]


def test_similar_creators_check_the_ids_too(api):
    fake = api([LIST])
    result = run(
        server.find_similar_creators(platform="tiktok", filter_value="someone", filters={"exclude_list": [42]})
    )
    assert result["error"] is True and "42 (instagram)" in result["message"]
    assert [c[0] for c in fake.calls] == ["GET"]


# --- registration ---------------------------------------------------------------


def test_tools_are_registered_with_honest_annotations():
    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    # read-only, destructive. Reading a default list is not read-only: the API creates it on first use.
    expected = {
        "list_exclusion_lists": (True, False),
        "create_exclusion_list": (False, False),
        "get_exclusion_list": (True, False),
        "rename_exclusion_list": (False, False),
        "delete_exclusion_list": (False, True),
        "get_exclusion_list_handles": (True, False),
        "add_to_exclusion_list": (False, False),
        "remove_from_exclusion_list": (False, True),
        "get_default_exclusion_list": (False, False),
        "get_default_exclusion_list_handles": (False, False),
        "add_to_default_exclusion_list": (False, False),
        "remove_from_default_exclusion_list": (False, True),
    }
    assert {n for n in tools if "exclusion" in n} == set(expected)
    for name, (read_only, destructive) in expected.items():
        assert tools[name].annotations.readOnlyHint is read_only, name
        assert tools[name].annotations.destructiveHint is destructive, name
    filters_schema = json.dumps(tools["discover_creators"].inputSchema)
    for key in ("exclude_list", "exclude_default_list", "exclude_all_lists"):
        assert key in filters_schema


# --- HTTP verbs ---------------------------------------------------------------------


def test_patch_and_delete_over_http(monkeypatch):
    monkeypatch.setenv("INFLUENCERS_CLUB_API_KEY", "key")
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append((request.method, request.url.path, request.content, request.headers.get("content-type")))
        if request.method == "DELETE" and request.url.path == f"{BASE}42/":
            return httpx.Response(204)
        if request.method == "DELETE" and request.url.path == f"{BASE}43/":
            return httpx.Response(404, json={"error": "Exclusion list not found."})
        if request.url.path == f"{BASE}44/":
            return httpx.Response(400, json={"error": ["The default exclusion list cannot be renamed."]})
        if request.url.path == f"{BASE}45/":
            return httpx.Response(400, json={"error": {"name": ["A list with this name already exists for this platform."]}})
        if request.url.path == "/empty":
            return httpx.Response(200)
        if request.url.path == "/nested":
            return httpx.Response(400, json={"error": {"filters": {"engagement_percent": ["A valid number is required."]}}})
        return httpx.Response(200, json={"id": 42})

    client = InfluencersApiClient()
    client._client = httpx.AsyncClient(base_url="https://api.test", transport=httpx.MockTransport(handler))

    async def scenario():
        removed = await client.delete(f"{BASE}42/entries/", {"handles": ["a"]})
        deleted = await client.delete(f"{BASE}42/")
        renamed = await client.patch(f"{BASE}42/", {"name": "n"})
        errors = []
        for call in (
            client.delete(f"{BASE}43/"),
            client.patch(f"{BASE}44/", {"name": "n"}),
            client.patch(f"{BASE}45/", {"name": "n"}),
            client.post("/nested", {}),
        ):
            try:
                await call
            except ApiError as e:
                errors.append((e.status, e.message))
        # Only a 204 may come back empty; an empty 200 is still an error, as before.
        with pytest.raises(ApiError):
            await client.post("/empty", {})
        await client._client.aclose()
        return removed, deleted, renamed, errors

    removed, deleted, renamed, errors = asyncio.run(scenario())
    assert removed == {"id": 42} and renamed == {"id": 42}
    assert deleted is None  # 204, no body
    assert seen[0][:2] == ("DELETE", f"{BASE}42/entries/")
    assert json.loads(seen[0][2]) == {"handles": ["a"]} and seen[0][3] == "application/json"
    assert seen[1][2] == b"" and seen[1][3] is None  # a bare DELETE carries neither body nor content-type
    assert seen[2][:2] == ("PATCH", f"{BASE}42/") and json.loads(seen[2][2]) == {"name": "n"}
    assert errors == [
        (404, "Exclusion list not found."),
        (400, "The default exclusion list cannot be renamed."),
        (400, "name: A list with this name already exists for this platform."),
        (400, "filters: engagement_percent: A valid number is required."),
    ]
