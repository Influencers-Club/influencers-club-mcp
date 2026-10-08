"""The MCP host's OAuth proxy fills in what some clients leave out.

/authorize and /register forward a client's OAuth messages to the dashboard. A
client that omits the RFC 8707 resource gets a token the dashboard never binds to
this server, which introspection then reports as inactive; one that asks for
`openid` gets a token with no scope, which every API call refuses. The proxy
defaults the resource and maps `openid` to `all`, and forwards every other
parameter with the value the client sent.
"""

import json
import logging
import os
import subprocess
import sys
import textwrap
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest

from influencers_club_mcp.oauth_proxy import authorize_params, map_openid_scope

RESOURCE = "https://mcp.test/mcp"
DASHBOARD = "https://dash.test"
REPO_ROOT = Path(__file__).resolve().parents[1]

# What a client sends to /authorize before resource and scope come into it.
BASE = {
    "response_type": "code",
    "client_id": "c1",
    "redirect_uri": "https://client.test/cb",
    "state": "s1",
    "code_challenge": "abc",
    "code_challenge_method": "S256",
}


@pytest.mark.parametrize(
    ("scope", "forwarded"),
    [
        ("openid", "all"),
        ("openid profile email", "all"),
        ("all openid", "all"),
        ("all", "all"),
        # No openid: forwarded as sent, even when none of the scopes is supported.
        ("profile email", "profile email"),
    ],
)
def test_only_a_scope_with_openid_becomes_all(scope, forwarded):
    sent = {"client_name": "Client", "scope": scope}

    assert map_openid_scope(sent, "/register") == {"client_name": "Client", "scope": forwarded}


@pytest.mark.parametrize(
    "sent",
    [{"client_name": "Client"}, {"client_name": "Client", "scope": ["openid"]}],
    ids=["no-scope", "non-string-scope"],
)
def test_params_without_a_scope_string_are_forwarded_as_sent(sent):
    assert map_openid_scope(sent, "/register") == sent


@pytest.mark.parametrize(
    "extra",
    [
        {"resource": RESOURCE, "scope": "all"},
        {"resource": RESOURCE},
        # Another resource is the client's claim to make; introspection judges it.
        {"resource": "https://other.test", "scope": "all"},
        # Unsupported scopes without openid are the dashboard's to judge, not rewritten.
        {"resource": RESOURCE, "scope": "profile email"},
    ],
    ids=["resource-and-scope", "resource-no-scope", "other-resource", "unsupported-scopes"],
)
def test_a_compliant_authorize_request_is_forwarded_as_sent(extra):
    assert authorize_params({**BASE, **extra}, RESOURCE) == {**BASE, **extra}


@pytest.mark.parametrize("sent", [{}, {"resource": ""}], ids=["missing", "blank"])
def test_a_missing_resource_defaults_to_this_server(sent):
    assert authorize_params({**BASE, **sent}, RESOURCE) == {**BASE, "resource": RESOURCE}


def test_openid_is_mapped_and_the_clients_resource_kept():
    sent = {**BASE, "resource": "https://other.test", "scope": "openid"}

    assert authorize_params(sent, RESOURCE) == {**sent, "scope": "all"}


def test_each_fallback_is_logged_where_it_applies(caplog):
    caplog.set_level(logging.INFO, logger="influencers_club_mcp.oauth_proxy")

    authorize_params({**BASE, "resource": RESOURCE, "scope": "all"}, RESOURCE)
    assert caplog.messages == []

    authorize_params({**BASE, "scope": "openid"}, RESOURCE)
    assert caplog.messages == [
        "oauth-proxy /authorize: mapped scope openid to all",
        "oauth-proxy /authorize: defaulted resource for client_id=c1",
    ]


def test_hosted_routes_forward_the_filled_in_request():
    """server.py imported fresh in HTTP mode, the dashboard stubbed.

    The helpers above only matter if the routes use them: /authorize must redirect
    with the defaulted resource and mapped scope, /register must post the mapped
    client as JSON and refuse a body that isn't a JSON object, and /token must post
    the client's form with every value intact.
    """
    probe = textwrap.dedent(
        """
        import json

        import httpx
        from starlette.testclient import TestClient

        from influencers_club_mcp import server

        posted = []

        def dashboard(request):
            posted.append([str(request.url), request.headers["content-type"], request.content.decode()])
            return httpx.Response(201, json={"client_id": "c1"})

        real_client = httpx.AsyncClient
        httpx.AsyncClient = lambda **kw: real_client(transport=httpx.MockTransport(dashboard), **kw)

        http = TestClient(server.mcp.streamable_http_app())
        authorize = http.get("/authorize?client_id=c1&scope=openid", follow_redirects=False)
        register = http.post("/register", json={"client_name": "Client", "scope": "openid"})
        malformed = http.post("/register", content=b"not json")
        token = http.post(
            "/token",
            content=b"grant_type=authorization_code&code=a%2Bb%2F%3D&redirect_uri=https%3A%2F%2Fclient.test%2Fcb",
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        print(json.dumps({
            "authorize": [authorize.status_code, authorize.headers["location"]],
            "register": [register.status_code, register.json()],
            "malformed": [malformed.status_code, malformed.json()["error"]],
            "token": token.status_code,
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
        timeout=60,
    )

    assert result.returncode == 0, result.stderr
    seen = json.loads(result.stdout.strip().splitlines()[-1])

    status, location = seen["authorize"]
    assert status == 302
    target = urlsplit(location)
    assert f"{target.scheme}://{target.netloc}{target.path}" == f"{DASHBOARD}/public/v1/oauth/authorize/"
    assert parse_qs(target.query) == {"client_id": ["c1"], "scope": ["all"], "resource": [RESOURCE]}

    assert seen["register"] == [201, {"client_id": "c1"}]
    assert seen["malformed"] == [400, "invalid_client_metadata"]
    assert seen["token"] == 201

    # The malformed registration never reaches the dashboard.
    (register_url, register_type, register_body), (token_url, token_type, token_body) = seen["posted"]
    assert register_url == f"{DASHBOARD}/public/v1/oauth/register/"
    assert register_type == "application/json"
    assert json.loads(register_body) == {"client_name": "Client", "scope": "all"}
    assert token_url == f"{DASHBOARD}/public/v1/oauth/token/"
    assert token_type == "application/x-www-form-urlencoded"
    assert parse_qs(token_body) == {
        "grant_type": ["authorization_code"],
        "code": ["a+b/="],
        "redirect_uri": ["https://client.test/cb"],
    }
