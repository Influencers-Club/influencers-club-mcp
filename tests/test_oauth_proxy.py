"""The MCP host's OAuth proxy fills in what some clients leave out.

/authorize and /register forward a client's OAuth messages to the dashboard. A
client that omits the RFC 8707 resource gets a token the dashboard never binds to
this server, which introspection then reports as inactive; one that asks for
`openid` gets a token with no scope, which every API call refuses. The proxy
defaults the resource and maps `openid` to `all`, and forwards everything else
exactly as the client sent it.
"""

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from influencers_club_mcp.server import _authorize_query, _map_openid_scope, _register_body

RESOURCE = "https://mcp.test/mcp"
DASHBOARD = "https://dash.test"
REPO_ROOT = Path(__file__).resolve().parents[1]

# What a client sends to /authorize before resource and scope come into it.
BASE_QUERY = (
    "response_type=code&client_id=c1&redirect_uri=https%3A%2F%2Fclient.test%2Fcb"
    "&state=s1&code_challenge=abc&code_challenge_method=S256"
)


@pytest.mark.parametrize(
    ("scope", "forwarded"),
    [
        ("openid", "all"),
        ("openid profile email", "all"),
        ("all openid", "all"),
        ("all", "all"),
        # No openid: forwarded as sent, even when none of the scopes is supported.
        ("profile email", "profile email"),
        ("", ""),
    ],
)
def test_only_a_request_with_openid_becomes_all(scope, forwarded):
    assert _map_openid_scope(scope) == forwarded


@pytest.mark.parametrize(
    "query",
    [
        f"{BASE_QUERY}&resource=https%3A%2F%2Fmcp.test%2Fmcp&scope=all",
        f"{BASE_QUERY}&resource=https%3A%2F%2Fmcp.test%2Fmcp",
        # Another resource is the client's claim to make; introspection judges it.
        f"{BASE_QUERY}&resource=https%3A%2F%2Fother.test&scope=all",
        # Unsupported scopes without openid are the dashboard's to judge, not rewritten.
        f"{BASE_QUERY}&resource=https%3A%2F%2Fmcp.test%2Fmcp&scope=profile+email",
    ],
    ids=["resource-and-scope", "resource-no-scope", "other-resource", "unsupported-scopes"],
)
def test_a_compliant_authorize_request_is_forwarded_byte_for_byte(query):
    assert _authorize_query(query, RESOURCE) == query


def test_a_missing_resource_defaults_to_this_server():
    forwarded = parse_qs(_authorize_query(f"{BASE_QUERY}&scope=all", RESOURCE))

    assert forwarded["resource"] == [RESOURCE]
    assert {k: v for k, v in forwarded.items() if k != "resource"} == parse_qs(
        f"{BASE_QUERY}&scope=all"
    )


def test_a_blank_resource_counts_as_missing():
    forwarded = parse_qs(
        _authorize_query(f"{BASE_QUERY}&resource=", RESOURCE), keep_blank_values=True
    )

    assert forwarded["resource"] == [RESOURCE]


def test_openid_is_mapped_and_the_clients_resource_kept():
    query = f"{BASE_QUERY}&resource=https%3A%2F%2Fother.test&scope=openid"

    forwarded = parse_qs(_authorize_query(query, RESOURCE))

    assert forwarded["scope"] == ["all"]
    assert forwarded["resource"] == ["https://other.test"]


def test_register_maps_openid_and_keeps_the_rest():
    sent = {"client_name": "Client", "redirect_uris": ["https://client.test/cb"], "scope": "openid"}

    forwarded = json.loads(_register_body(json.dumps(sent).encode()))

    assert forwarded == {**sent, "scope": "all"}


@pytest.mark.parametrize(
    "body",
    [
        json.dumps({"client_name": "Client", "redirect_uris": ["https://client.test/cb"]}).encode(),
        json.dumps({"client_name": "Client", "scope": "all"}).encode(),
        json.dumps({"client_name": "Client", "scope": "profile email"}).encode(),
        json.dumps({"client_name": "Client", "scope": ["openid"]}).encode(),
        b"[]",
        b"not json",
        b"",
    ],
    ids=["no-scope", "all", "unsupported-scopes", "non-string-scope", "not-an-object", "not-json", "empty"],
)
def test_register_forwards_other_bodies_as_sent(body):
    assert _register_body(body) == body


def test_hosted_routes_forward_the_filled_in_request():
    """server.py imported fresh in HTTP mode, the dashboard stubbed.

    The helpers above only matter if the routes use them: /authorize must redirect
    with the defaulted resource and mapped scope, and /register must post the mapped
    body to the dashboard and pass its answer back.
    """
    probe = textwrap.dedent(
        """
        import json

        import httpx
        from starlette.testclient import TestClient

        from influencers_club_mcp import server

        posted = {}

        def dashboard(request):
            posted["url"] = str(request.url)
            posted["body"] = json.loads(request.content)
            return httpx.Response(201, json={"client_id": "c1"})

        real_client = httpx.AsyncClient
        httpx.AsyncClient = lambda **kw: real_client(transport=httpx.MockTransport(dashboard), **kw)

        http = TestClient(server.mcp.streamable_http_app())
        authorize = http.get("/authorize?client_id=c1&scope=openid", follow_redirects=False)
        register = http.post("/register", json={"client_name": "Client", "scope": "openid"})
        print(json.dumps({
            "authorize": [authorize.status_code, authorize.headers["location"]],
            "register": [register.status_code, register.json()],
            "posted": posted,
        }))
        """
    )
    inherited = {
        name: value
        for name, value in os.environ.items()
        if not name.startswith(("MCP_", "OAUTH_", "INFLUENCERS_CLUB_"))
    }
    env = {"MCP_TRANSPORT": "http", "OAUTH_RESOURCE_URL": RESOURCE, "OAUTH_API_BASE": DASHBOARD}

    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=REPO_ROOT,
        env={**inherited, **env},
        capture_output=True,
        text=True,
        errors="replace",
    )

    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout.strip().splitlines()[-1])

    status, location = seen["authorize"]
    assert status == 302
    target = urlsplit(location)
    assert f"{target.scheme}://{target.netloc}{target.path}" == f"{DASHBOARD}/public/v1/oauth/authorize/"
    assert parse_qs(target.query) == {"client_id": ["c1"], "scope": ["all"], "resource": [RESOURCE]}

    assert seen["register"] == [201, {"client_id": "c1"}]
    assert seen["posted"] == {
        "url": f"{DASHBOARD}/public/v1/oauth/register/",
        "body": {"client_name": "Client", "scope": "all"},
    }
