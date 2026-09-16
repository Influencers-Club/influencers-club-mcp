"""The introspection (admission) and token-exchange caches: expiry, bounds, eviction."""

import asyncio
import time

import httpx
import pytest
from cachetools import Cache

from influencers_club_mcp import auth
from influencers_club_mcp.api_client import ApiError, InfluencersApiClient
from influencers_club_mcp.auth import ICTokenVerifier

DASHBOARD = "https://dashboard.test"
RESOURCE = "https://mcp.test/mcp"
_RealAsyncClient = httpx.AsyncClient


class Clock:
    """A manually advanced stand-in for time.time()."""

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


@pytest.fixture
def clock(monkeypatch) -> Clock:
    """Freeze time.time() before any cache is built; tests advance it explicitly."""
    frozen = Clock()
    monkeypatch.setattr(time, "time", frozen)
    return frozen


def stored(cache: Cache) -> int:
    """Entries physically held. ``len()`` on a timed cache purges lapsed ones first."""
    return Cache.__len__(cache)


def probe_returning(*answers: bool):
    """An exchange probe that returns ``answers`` in order, then keeps the last one."""
    remaining = list(answers)

    async def probe(_token: str) -> bool:
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    return probe


@pytest.fixture
def introspection(clock, monkeypatch):
    """Answer introspection from a stub that counts calls. Tests may change ``exp``."""
    state = {"calls": 0, "exp": int(clock.now) + 3600}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        return httpx.Response(
            200, json={"active": True, "aud": RESOURCE, "sub": "user", "exp": state["exp"]}
        )

    monkeypatch.setattr(
        httpx,
        "AsyncClient",
        lambda **kw: _RealAsyncClient(transport=httpx.MockTransport(handler), **kw),
    )
    return state


@pytest.fixture
def exchange(clock, monkeypatch):
    """An API client whose token exchange hits a counting stub."""
    monkeypatch.setenv("OAUTH_API_BASE", DASHBOARD)
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "client")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "secret")
    state = {"calls": 0, "expires_in": 3600, "reject": False}

    def handler(request: httpx.Request) -> httpx.Response:
        state["calls"] += 1
        if state["reject"]:
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(
            200, json={"access_token": f"dash-{state['calls']}", "expires_in": state["expires_in"]}
        )

    client = InfluencersApiClient()
    client._client = _RealAsyncClient(base_url=DASHBOARD, transport=httpx.MockTransport(handler))
    return client, state


def make_verifier(cache_ttl: float = 60.0) -> ICTokenVerifier:
    return ICTokenVerifier(DASHBOARD, "client", "secret", RESOURCE, [], cache_ttl=cache_ttl)


def test_admission_is_reused_until_cache_ttl(introspection, clock):
    verifier = make_verifier()

    async def scenario():
        await verifier.verify_token("tok")
        await verifier.verify_token("tok")
        assert introspection["calls"] == 1  # second request served from the cache
        clock.advance(61)
        await verifier.verify_token("tok")
        assert introspection["calls"] == 2  # lapsed after cache_ttl, so re-introspected

    asyncio.run(scenario())


def test_admission_never_outlives_the_token(introspection, clock):
    introspection["exp"] = int(clock.now) + 10
    verifier = make_verifier(cache_ttl=60)

    async def scenario():
        await verifier.verify_token("tok")
        clock.advance(11)
        await verifier.verify_token("tok")

    asyncio.run(scenario())
    assert introspection["calls"] == 2


def test_tokens_nobody_presents_again_are_purged(introspection, clock):
    verifier = make_verifier()

    async def scenario():
        for i in range(100):
            await verifier.verify_token(f"old-{i}")
        clock.advance(61)
        assert stored(verifier._cache) == 100  # lapsed, but nothing has dropped them yet
        await verifier.verify_token("new")

    asyncio.run(scenario())
    assert stored(verifier._cache) == 1  # storing a live admission dropped the lapsed ones


def test_admission_cache_is_bounded(introspection, monkeypatch):
    monkeypatch.setattr(auth, "_CACHE_MAXSIZE", 3)
    verifier = make_verifier()

    async def scenario():
        for i in range(5):
            await verifier.verify_token(f"tok-{i}")

    asyncio.run(scenario())
    assert stored(verifier._cache) == 3


def test_invalidate_drops_a_live_admission(introspection, monkeypatch):
    verifier = make_verifier()
    monkeypatch.setattr(auth, "_ACTIVE_VERIFIER", verifier)

    async def scenario():
        await verifier.verify_token("tok")
        assert auth.invalidate_cached_token("tok") is True
        assert auth.invalidate_cached_token("tok") is False
        await verifier.verify_token("tok")

    asyncio.run(scenario())
    assert introspection["calls"] == 2  # re-introspected after the eviction


def test_cached_admission_is_rejected_once_not_exchangeable(introspection):
    verifier = make_verifier()
    verifier.set_exchange_probe(probe_returning(True, False, True))

    async def scenario():
        assert await verifier.verify_token("tok") is not None  # admitted and cached
        assert await verifier.verify_token("tok") is None  # dashboard dropped it since
        assert await verifier.verify_token("tok") is not None  # re-checked, not cached

    asyncio.run(scenario())
    assert introspection["calls"] == 2


def test_fresh_admission_is_rejected_when_not_exchangeable(introspection):
    verifier = make_verifier()
    verifier.set_exchange_probe(probe_returning(False))

    async def scenario():
        assert await verifier.verify_token("tok") is None
        assert await verifier.verify_token("tok") is None

    asyncio.run(scenario())
    assert introspection["calls"] == 2  # a rejected token is never cached


def test_exchange_is_reused_until_shortly_before_expiry(exchange, clock):
    client, state = exchange

    async def scenario():
        first = await client._exchange_token("user-tok")
        again = await client._exchange_token("user-tok")
        clock.advance(3600 - 30 + 1)  # past the 30s re-exchange margin
        renewed = await client._exchange_token("user-tok")
        return first, again, renewed

    assert asyncio.run(scenario()) == ("dash-1", "dash-1", "dash-2")
    assert state["calls"] == 2


def test_short_lived_exchange_is_not_cached(exchange):
    client, state = exchange
    state["expires_in"] = 20  # inside the 30s margin, so never reused

    async def scenario():
        await client._exchange_token("user-tok")
        await client._exchange_token("user-tok")

    asyncio.run(scenario())
    assert state["calls"] == 2


def test_lapsed_exchanges_are_purged(exchange, clock):
    client, _state = exchange

    async def scenario():
        for i in range(100):
            await client._exchange_token(f"old-{i}")
        clock.advance(3600)
        assert stored(client._exchange_cache) == 100  # lapsed, not yet dropped
        await client._exchange_token("new")

    asyncio.run(scenario())
    assert stored(client._exchange_cache) == 1


def test_invalid_grant_clears_the_admission_too(exchange, introspection, monkeypatch):
    client, state = exchange
    verifier = make_verifier()
    monkeypatch.setattr(auth, "_ACTIVE_VERIFIER", verifier)

    async def scenario():
        await verifier.verify_token("user-tok")  # admitted and cached
        state["reject"] = True  # the dashboard has since deactivated the token
        with pytest.raises(ApiError) as err:
            await client._exchange_token("user-tok")
        return err.value.status

    assert asyncio.run(scenario()) == 401
    assert verifier.invalidate("user-tok") is False  # the admission was already dropped
