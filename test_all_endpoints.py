"""Test every endpoint in the MCP server against the live API."""
import asyncio
import os
import json

if not os.environ.get("INFLUENCERS_CLUB_API_KEY"):
    raise RuntimeError(
        "Set INFLUENCERS_CLUB_API_KEY environment variable before running tests.\n"
        "  Windows:  set INFLUENCERS_CLUB_API_KEY=Bearer your_token_here\n"
        "  Mac/Linux: export INFLUENCERS_CLUB_API_KEY='Bearer your_token_here'"
    )

from influencers_club_mcp.server import (
    check_credits,
    discover_creators,
    find_similar_creators,
    get_languages,
    get_locations,
    get_youtube_topics,
    get_twitch_games,
    enrich_by_email_basic,
    enrich_by_email_advanced,
    enrich_by_handle,
    enrich_by_handle_raw,
    create_batch_enrichment,
    get_batch_status,
    get_batch_results,
    resume_batch,
    get_post_details,
)

results = []
BATCH_ID = "bch_97912db6fec544b9aafc4ab8ef057e8b"


async def test(name, coro, costs_credits=False):
    try:
        r = await coro
        d = None
        try:
            d = json.loads(r)
        except Exception:
            pass

        if d and isinstance(d, dict) and "status_code" in d:
            code = d["status_code"]
            err = d.get("error", "")
            if isinstance(err, dict):
                err = err.get("error", err.get("detail", err.get("message", str(err))))
            results.append((name, code, str(err)[:60], costs_credits))
        elif d and isinstance(d, dict) and "error" in d and "current_status" in d:
            results.append((name, 400, d.get("message", d.get("error", ""))[:60], costs_credits))
        else:
            snippet = r[:60].replace("\n", " ")
            results.append((name, 200, snippet, costs_credits))
    except Exception as e:
        results.append((name, "EXC", str(e)[:60], costs_credits))


async def main():
    # ── 1. Account (FREE) ──
    await test("check_credits", check_credits())

    # ── 2-5. Reference Data (FREE) ──
    await test("get_languages", get_languages())
    await test("get_locations", get_locations(platform="instagram"))
    await test("get_youtube_topics", get_youtube_topics())
    await test("get_twitch_games", get_twitch_games())

    # ── 6-8. Batch mgmt with real ID (FREE) ──
    await test("get_batch_status", get_batch_status(batch_id=BATCH_ID))
    await test("get_batch_results", get_batch_results(batch_id=BATCH_ID))
    await test("resume_batch", resume_batch(batch_id=BATCH_ID))

    # ── 9-10. Discovery (0.01 each) ──
    await test("discover_creators", discover_creators(platform="instagram", limit=1), True)
    await test("find_similar_creators", find_similar_creators(
        platform="instagram", filter_key="username", filter_value="cristiano", limit=1), True)

    # ── 11-12. Email enrichment (test with fake email - endpoint check only) ──
    await test("enrich_by_email_basic", enrich_by_email_basic(email="test@nonexistent-xyz.com"), True)
    await test("enrich_by_email_advanced", enrich_by_email_advanced(email="test@nonexistent-xyz.com"), True)

    # ── 13-14. Handle enrichment (costs credits) ──
    await test("enrich_by_handle", enrich_by_handle(
        handle="cristiano", platform="instagram",
        include_lookalikes=False, include_audience_data=False), True)
    await test("enrich_by_handle_raw", enrich_by_handle_raw(
        handle="cristiano", platform="instagram"), True)

    # ── 15. Batch create (costs credits) ──
    await test("create_batch_enrichment", create_batch_enrichment(
        csv_content="handle\ncristiano", enrichment_mode="full", platform="instagram"), True)

    # ── 16. Post details (test with sample ID) ──
    await test("get_post_details", get_post_details(
        platform="instagram", post_id="CxLnGJuoZkr"), True)

    # ── PRINT TABLE ──
    print()
    print("=" * 115)
    print(f"{'#':<3} {'Tool':<28} {'HTTP':<6} {'$':<6} {'Verdict':<14} {'Detail'}")
    print("-" * 115)
    for i, (name, code, snippet, costs) in enumerate(results, 1):
        cost_str = "PAID" if costs else "FREE"
        if code == 200:
            verdict = "WORKING"
        elif code == 400:
            verdict = "ENDPOINT OK"
        elif code == 404:
            verdict = "NOT FOUND"
        elif code == 409:
            verdict = "ENDPOINT OK"
        else:
            verdict = f"ERROR ({code})"
        print(f"{i:<3} {name:<28} {str(code):<6} {cost_str:<6} {verdict:<14} {snippet}")
    print("=" * 115)

    working = sum(1 for _, c, _, _ in results if c in (200, 400, 409))
    dead = sum(1 for _, c, _, _ in results if c not in (200, 400, 409))
    print(f"\nEndpoints LIVE (200/400/409): {working} / {len(results)}")
    print(f"Endpoints DEAD (404/error):   {dead} / {len(results)}")


asyncio.run(main())
