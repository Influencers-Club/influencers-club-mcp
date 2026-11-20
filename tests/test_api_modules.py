"""The endpoint groups on the API client send exactly the requests server.py used to
build itself: same verb, address, query, body and timeout for each operation."""

import asyncio
import json

import httpx
import pytest

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
    assert sent(api.by_handle_profile("nike", "linkedin", email_required="must_have"), t) == (
        "POST", f"{V1}/creators/enrich/handle/profile/", None,
        {"handle": "nike", "platform": "linkedin", "email_required": "must_have"}, None,
    )
    t.calls.clear()
    assert sent(api.by_handle_analytics("nike", "tiktok", include_lookalikes=False), t) == (
        "POST", f"{V1}/creators/enrich/handle/analytics/", None,
        {"handle": "nike", "platform": "tiktok", "include_lookalikes": False}, None,
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
    assert sent(api.download_link("abc-123"), t) == ("GET", f"{V1}/enrichment/batch/abc-123/download/", None, None, None)
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
        lambda: BatchApi(Transport()).download_link("abc?format=csv"),
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
        "include_lookalikes": True, "include_audience_data": True,
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


def test_download_batch_results_link_on_hosted_file_on_local(monkeypatch, tmp_path):
    from influencers_club_mcp import server
    from influencers_club_mcp.api_client import ApiError

    name, CSV = "batch_bch_1_enriched_results.csv", b"handle,status\r\nnike,ok\r\n"
    link = {"download_url": "https://s3.example/r.csv?sig=1", "filename": name, "expires_at": "2026-01-01T00:00:00Z",
            "total_results": 2, "invalid_records": 0}
    fake = FakeClient(*[link] * 4)
    monkeypatch.setattr(server, "client", fake)

    def call():  # no client name is set: the tool is open to every client
        return json.loads(asyncio.run(server.download_batch_results(batch_id=" bch_1 ")))

    monkeypatch.setattr(server, "HTTP_MODE", True)  # hosted: the link and the counts, no rows
    assert call() == link
    assert fake.calls[0][:2] == ("GET", f"{V1}/enrichment/batch/bch_1/download/")

    async def fetch(url, path):
        assert url == link["download_url"]
        path.write_bytes(CSV)

    chosen, mount = tmp_path / "chosen", tmp_path / "mount"
    monkeypatch.setattr(server, "HTTP_MODE", False)  # local: the server's CSV lands in the folder the user chose
    monkeypatch.setattr(server, "OUTPUT_DIR", str(mount))
    monkeypatch.setattr(server, "_get_export_host_dir", lambda: str(chosen))
    monkeypatch.setattr(server, "_is_docker", lambda: False)
    monkeypatch.setattr(fake, "download_file", fetch, raising=False)
    out = call()
    assert out["file"] == str(chosen / name) and out["total_results"] == 2 and "preview" not in out
    assert (chosen / name).read_bytes() == CSV and not mount.exists()
    (chosen / name).write_bytes(b"edited")  # a second download keeps the first file
    again = call()["file"]
    assert again != out["file"] and (chosen / name).read_bytes() == b"edited"

    monkeypatch.setattr(server, "_is_docker", lambda: True)  # Docker: written to the mount, reported as the host path
    assert call()["file"] == str(chosen / name) and (mount / name).read_bytes() == CSV

    async def not_ready(batch_id):
        raise ApiError(400, "not generated yet", code="results_not_ready")

    monkeypatch.setattr(fake.batch, "download_link", not_ready)  # no results file yet: not an error, not "retry"
    out = call()
    assert out["status"] == "results_not_ready" and "error" not in out and "retryable" not in out


def test_host_export_path_keeps_the_host_style(monkeypatch):
    from pathlib import Path
    from influencers_club_mcp import server

    monkeypatch.setattr(server, "_is_docker", lambda: True)  # Linux server, host folder in its own style
    monkeypatch.setattr(server, "OUTPUT_DIR", "/exports")
    for host, want in ((r"C:\Users\x\exports", r"C:\Users\x\exports\b.csv"), ("/Users/ana/exports", "/Users/ana/exports/b.csv")):
        monkeypatch.setattr(server, "_get_export_host_dir", lambda h=host: h)
        assert server._host_export_path(Path("/exports") / "b.csv") == want


def test_batch_from_a_full_path_uses_that_file_not_a_same_named_one(monkeypatch, tmp_path):
    from influencers_club_mcp import server

    chosen, old = tmp_path / "chosen", tmp_path / "old"
    for folder, handle in ((chosen, "wrong"), (old, "right"), (tmp_path / "imports", "wrong")):
        folder.mkdir()
        (folder / "list.csv").write_bytes(f"handle\n{handle}\n".encode())
    monkeypatch.setattr(server, "_is_docker", lambda: False)
    monkeypatch.setattr(server, "_get_export_host_dir", lambda: str(chosen))
    monkeypatch.setattr(server, "OUTPUT_DIR", str(old))
    monkeypatch.setattr(server, "IMPORTS_DIR", str(tmp_path / "imports"))
    fake = FakeClient()
    monkeypatch.setattr(server, "client", fake)

    asyncio.run(server.create_batch_enrichment(enrichment_mode="raw", platform="instagram", csv_file_path=str(old / "list.csv")))
    assert fake.calls[0][3]["file"][1] == b"handle\nright\n"


def test_batch_from_a_list_in_the_chat(monkeypatch):
    """No client name and no file: the list is sent under the column its values name."""
    from influencers_club_mcp import server

    fake = FakeClient()
    monkeypatch.setattr(server, "client", fake)
    monkeypatch.setattr(server, "HTTP_MODE", True)

    def create(**kw):
        return json.loads(asyncio.run(server.create_batch_enrichment(**kw)))

    assert create(values=["a@x.com", "b@x.com"])["detected_input_type"] == "email"  # the mode menu
    assert create(values=["@john.doe", "@nike"])["detected_input_type"] == "handle"
    for item in ("nike,adidas", "nike adidas"):
        assert "one handle or email" in create(enrichment_mode="raw", platform="instagram", values=[item])["message"]
    assert fake.calls == []
    create(enrichment_mode="basic", values=[" a@x.com ", "", "b@x.com"])
    create(enrichment_mode="raw", platform="instagram", values=["nike", "adidas"])
    create(enrichment_mode="raw", platform="instagram", values=["a@x.com"])  # wrong mode: the API refuses the email column
    assert [c[3]["file"][1] for c in fake.calls] == [b"email\na@x.com\nb@x.com", b"handle\nnike\nadidas", b"email\na@x.com"]


def test_inline_batch_limit_is_in_the_schema():
    from influencers_club_mcp import server

    tools = {t.name: t for t in asyncio.run(server.mcp.list_tools())}
    assert '"maxItems": 200' in json.dumps(tools["create_batch_enrichment"].inputSchema["properties"]["values"])


def test_hosted_batch_never_reads_a_file_path(monkeypatch, tmp_path):
    from influencers_club_mcp import server

    on_the_server = tmp_path / "list.csv"
    on_the_server.write_bytes(b"handle\nnike\n")
    fake = FakeClient()
    monkeypatch.setattr(server, "client", fake)
    monkeypatch.setattr(server, "HTTP_MODE", True)
    for mode in ("", "raw"):  # the mode menu reads the file too
        out = json.loads(asyncio.run(server.create_batch_enrichment(
            enrichment_mode=mode, platform="instagram", csv_file_path=str(on_the_server))))
        assert "local install" in out["message"] and "detected_input_type" not in out
    assert fake.calls == []


def test_hosted_server_offers_the_batch_tools():
    """The tool list is fixed at import, so hosted mode takes a fresh interpreter."""
    import os
    import subprocess
    import sys

    code = "from influencers_club_mcp import server; print(*(t.name for t in server.mcp._tool_manager.list_tools()))"
    env = {**os.environ, "MCP_TRANSPORT": "http", "MCP_OAUTH_ENABLED": "false", "INFLUENCERS_CLUB_API_KEY": "dummy"}
    names = set(subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, check=True).stdout.split())
    assert {"create_batch_enrichment", "get_batch_status", "resume_batch", "download_batch_results"} <= names
    assert not {"get_upload_url", "wait_for_upload", "list_import_files", "discover_creators_to_file"} & names


def test_status_waits_out_the_api_poll_limit(monkeypatch):
    """Another server instance polled a moment ago: the tool waits and asks again, no error shown."""
    from influencers_club_mcp import server
    from influencers_club_mcp.api_client import ApiError

    fake, naps = FakeClient(), []
    answers = [ApiError(429, "Polling too frequently", retryable=True, code="polling_too_frequent"), {"status": "processing"}]

    async def status(batch_id):
        answer = answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return answer

    async def nap(seconds):
        naps.append(seconds)

    monkeypatch.setattr(server, "client", fake)
    monkeypatch.setattr(fake.batch, "status", status)
    monkeypatch.setattr(server.asyncio, "sleep", nap)
    monkeypatch.setattr(server, "_batch_poll_cache", {})
    out = json.loads(asyncio.run(server.get_batch_status(batch_id="bch_9")))
    assert out["status"] == "processing" and naps == [30]
    assert isinstance(server._batch_poll_cache["bch_9"], float)  # the time of the poll, not its result


def test_setup_export_path_refuses_a_relative_folder(monkeypatch, tmp_path):
    from influencers_club_mcp import server

    monkeypatch.setattr(server, "_is_docker", lambda: False)
    monkeypatch.setattr(server, "CONFIG_FILE", str(tmp_path / ".ic_config.json"))
    out = json.loads(asyncio.run(server.setup_export_path(export_path=r"Desktop\exports")))
    assert out["error"] and "full path" in out["message"] and not (tmp_path / ".ic_config.json").exists()


def test_download_file_streams_and_never_shows_the_link(tmp_path):
    def handler(request):
        return httpx.Response(200 if request.url.params.get("ok") else 403, content=b"a,b\n1,2\n")

    client = InfluencersApiClient()
    client._client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    target = tmp_path / "r.csv"
    asyncio.run(client.download_file("https://s3.test/r.csv?ok=1&Signature=s", target))
    assert target.read_bytes() == b"a,b\n1,2\n"
    target.unlink()
    with pytest.raises(Exception) as err:
        asyncio.run(client.download_file("https://s3.test/r.csv?Signature=secret", target))
    assert "secret" not in str(err.value) and not target.exists()


def test_api_error_keeps_the_error_code():
    resp = httpx.Response(400, json={"error": "x", "error_code": "results_not_ready"}, request=httpx.Request("GET", "http://t"))
    err = InfluencersApiClient()._handle_error(httpx.HTTPStatusError("boom", request=resp.request, response=resp))
    assert (err.status, err.code) == (400, "results_not_ready")
