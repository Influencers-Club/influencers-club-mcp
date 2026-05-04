# Influencers Club → Claude Official Connector

**Goal:** Get the Influencers Club MCP server listed in Anthropic's official Connector Directory inside Claude (claude.ai + Claude Desktop), the same place users currently install Notion, Gmail, Figma, HubSpot, Atlassian Rovo, and others.

**Status:** Phase 1 in progress. Not yet submitted.
**Jira:** AAH-97
**Branch:** `connector-prep` (local, not pushed)
**Last updated:** 2026-04-30

---

## Why this matters

Today, IC's MCP works as a `pip install` / Docker package — a power-user distribution that requires manual config in Claude Desktop. The official directory is one-click install with OAuth login, surfaced to every Claude user who browses connectors.

This is a top-of-funnel and brand bet, not just a technical project: the audience reaching us through Anthropic's directory is broader (mainstream marketers, founders, agencies) than our current API customer base.

---

## Owners

| Person                 | Role                    | Lane                                                                |
| ---------------------- | ----------------------- | ------------------------------------------------------------------- |
| **Gjorgji Petrovski**  | Coordinator + repo work | PMs the cross-team effort, owns the MCP repo, files the submission  |
| **Nikola Krstev**      | Backend / dashboard     | Owns OAuth, hosting, presigned URL endpoints, observability         |
| **Alessandro Colombo** | Marketing               | Owns branding, copy, public documentation, partnerships positioning |

---

## Phases

| Phase                  | What                                                                                   | Status                       |
| ---------------------- | -------------------------------------------------------------------------------------- | ---------------------------- | ------- |
| **0. Repo prep**       | HTTP transport, per-request auth, privacy policy, tool gating                          | (on `connector-prep` branch) | ✅ Done |
| **1. Cross-team prep** | OAuth + hosting (Nikola), marketing assets (Alessandro), spec + coordination (Gjorgji) | 🟡 In progress               |
| **2. Submission**      | Hosted MCP live, end-to-end tested, submission form filed                              | ⚪ Not started               |
| **3. Review**          | Respond to Anthropic feedback, iterate, get approved                                   | ⚪ Not started               |

---

## Phase 0 — Repo prep ✅ Done

Already merged into `connector-prep` branch (awaiting Gjorgji's review/push):

- [x] HTTP transport mode toggled by `MCP_TRANSPORT` env var
- [x] Origin/host validation (DNS rebinding protection) wired to env vars
- [x] `api_client` refactored to resolve bearer token per-request (forward-compatible with OAuth)
- [x] 6 local-only tools gated to stdio mode (`get_upload_url`, `wait_for_upload`, `list_import_files`, `list_export_files`, `setup_export_path`, `discover_creators_to_file`)
- [x] Privacy policy in README expanded to cover Anthropic's 6 required fields
- [x] Tool annotations confirmed on all 29 tools (title + readOnlyHint + destructiveHint + openWorldHint)

---

## Phase 1 — Cross-team prep 🟡

### Gjorgji Petrovski

**Coordination (this week):**

- [ ] Review the `connector-prep` branch diff and decide commit/push timing
- [ ] Brief Nikola: hand him the **Hosting & OAuth Spec** (see below) and set a delivery deadline
- [ ] Brief Alessandro: share this doc, get a delivery date for his deliverables
- [ ] Brief Legal _separately_: privacy policy update has the longest lead time — don't let Alessandro be the only person nagging legal
- [ ] File initial Anthropic inquiry at https://clau.de/mcp-directory-submission (placeholders OK — start the queue clock)
- [ ] Email `mcp-review@anthropic.com` to ask actual review timeline so we plan against a real date

**Decisions only Gjorgji can make / escalate:**

- [ ] Pick the named "partnerships contact" person for the submission form (himself, CEO, or Alessandro?)
- [ ] Get CEO/leadership awareness — connector listing affects positioning and pricing
- [ ] Decide free-trial strategy for new Claude users (they'll click Connect without ever paying — what credits do they get?)
- [ ] Commit to a GA date for the submission form
- [ ] Approve any contractor budget Alessandro requests (video, design)

**Repo work he can either do himself or hand back to Claude Code:**

- [ ] Set up the Anthropic reviewer test account on the dashboard (permanent, allocated credits, tagged `anthropic-reviewer@`)
- [ ] Optional: add MCP `prompts` (starter prompts users see when they connect) — biggest UX upgrade
- [ ] Optional: tool description polish for non-technical users
- [ ] Optional: pin `mcp` package version, add tests, set up CI, publish to PyPI

**Weekly cadence:**

- [ ] 15-min weekly sync with Nikola + Alessandro until submission

---

### Nikola Krstev — Hosting & OAuth Spec

The MCP repo's HTTP mode is ready (env vars wire it up). What's needed on the dashboard side:

**OAuth 2.1 endpoints on `dashboard.influencers.club`:**

- [ ] `/oauth/authorize` — redirects user to login if needed, shows consent screen, returns auth code
- [ ] `/oauth/token` — exchanges auth code for access + refresh tokens
- [ ] `/oauth/revoke` — invalidates a token (called when user clicks "Disconnect" in Claude)
- [ ] **OAuth Discovery** — `/.well-known/oauth-authorization-server` and `/.well-known/oauth-protected-resource`. Required by MCP spec so Claude can find auth endpoints automatically.
- [ ] **Dynamic Client Registration** (`/oauth/register`) OR pre-registered Claude `client_id` — pick one
- [ ] Decision: **JWT vs opaque tokens** (JWT = simpler for MCP server to validate; opaque = more revocable, requires introspection endpoint)
- [ ] Decision: **scope design** — e.g. `discovery:read`, `enrichment:write`, `batch:write` (so users see what they're granting on the consent screen)
- [ ] **Resource Indicators (RFC 8707)** — tokens scoped to `mcp.influencers.club` so they can't be reused against the public API
- [ ] **Refresh token policy** — short access + long refresh, or long access?
- [ ] **Consent UI** — page user sees ("Claude wants to access your IC account, X credits available")
- [ ] **"Connected apps" UI** — where users can see + revoke Claude's access from the dashboard

**Hosting `mcp.influencers.club`:**

- [ ] Decide infra: same as `api-dashboard.influencers.club`, or separate?
- [ ] Deploy the MCP server in HTTP mode with env vars: `MCP_TRANSPORT=http`, `ALLOWED_ORIGINS=https://claude.ai,https://claude.com`, `ALLOWED_HOSTS=mcp.influencers.club`
- [ ] Wire FastMCP `auth` config to validate tokens against the dashboard's JWKS or introspection endpoint
- [ ] HTTPS / TLS cert
- [ ] Health check endpoints (`/healthz`, `/readyz`)
- [ ] Structured JSON logging with request IDs + user IDs
- [ ] Per-user rate limiting (current 300/min is global → breaks at scale)
- [ ] Sentry or equivalent error tracking
- [ ] Deployment strategy that doesn't kill active sessions mid-tool-call

**Presigned URL endpoints (replaces the localhost upload flow):**

- [ ] `POST /api/uploads/presign` — returns a presigned S3 PUT URL for batch CSV uploads (10k handles can be MB-scale)
- [ ] `GET /api/exports` — returns list of presigned S3 GET URLs for the user's exported CSVs
- [ ] Webhook from S3 → dashboard registering uploaded files against user account

**Once Nikola has these in place, Claude Code reactivates the 3 currently-gated tools that need real replacements:** `get_upload_url`, `list_export_files`, `discover_creators_to_file`.

---

### Alessandro Colombo — Marketing for Submission

The Anthropic submission form requires all of these. **Items 1–7 + 11–12 are ~1 week of focused work; item 8 is ~1 week; item 9 is the wildcard (legal queue).**

- [ ] **1. Logo** — SVG, transparent background, light + dark variants
- [ ] **2. Favicon** — 32×32 PNG, recognizable at 16×16
- [ ] **3. Tagline** (~10 words) — e.g. _"AI-powered creator discovery and enrichment, inside Claude"_
- [ ] **4. Short description** (30–50 words) — for the directory card
- [ ] **5. Long description** (150–300 words) — for the connector detail page
- [ ] **6. 3–5 use cases** as concrete user scenarios — e.g. _"Find 50 fitness influencers on Instagram with 100k+ followers and 3%+ engagement, then enrich their emails."_
- [ ] **7. Category selection** — likely "Marketing & Sales" or "Data & Analytics"
- [ ] **8. Public documentation** — one blog post **or** help-center article about the Claude integration. Anthropic's docs explicitly require this to exist _before_ submission. Suggested: _"Introducing Influencers Club for Claude."_
- [ ] **9. Privacy policy update** — `influencers.club/privacy-policy` must explicitly cover MCP/Claude usage with all 6 fields (collection / usage / storage / third-parties / retention / contact). **Missing fields = immediate rejection.** Needs legal review.
- [ ] **10. 3–5 screenshots** of Claude using IC tools (PNG, 1000px+ wide, cropped to the response) — waits for hosted version to be testable
- [ ] **11. Support channel info** — confirmed support email/channel for Claude users
- [ ] **12. Anthropic co-branding compliance** — read Anthropic's brand guidelines for partner usage of "Claude" / "Built for Claude" / etc.

**Out of scope until approval lands:** launch announcement, demo video, landing page, cross-promotion, PR, customer email blast, sales enablement, pricing changes, community building. All of that is Phase 4+.

---

## Phase 2 — Submission ⚪

When Phase 1 is done:

- [ ] Hosted MCP at `mcp.influencers.club` is live and authenticated against the dashboard
- [ ] End-to-end test: connect from Claude.ai → consent → run several tools → verify usage shows up on dashboard
- [ ] All 12 marketing assets in hand
- [ ] Reviewer test account provisioned with credits + setup docs
- [ ] **Gjorgji files the official submission form** at https://clau.de/mcp-directory-submission

---

## Phase 3 — Review ⚪

- [ ] Triage Anthropic's review feedback as it arrives
- [ ] Fix flagged issues, re-submit
- [ ] On approval: directory listing goes live → kick off Phase 4 (launch — not in this doc)

---

## Critical path

```
[Nikola: OAuth + Hosting + Presigned URLs]  ──┐
                                              ├── [E2E test] → [Submit] → [Review] → APPROVED
[Alessandro: Marketing items 1–12 (legal!)] ──┘
```

The two tracks run in parallel. **Nikola's track is the longer-pole** in most realistic timelines. Alessandro's only blocker is legal turnaround on the privacy policy.

---

## Timeline (best estimate)

| Week         | Milestone                                                                                                                    |
| ------------ | ---------------------------------------------------------------------------------------------------------------------------- |
| **W0 (now)** | Briefs delivered to Nikola + Alessandro + Legal. Initial inquiry filed with Anthropic.                                       |
| **W1–W3**    | Nikola builds OAuth + hosting. Alessandro produces items 1–7, 11–12. Legal reviews privacy policy. Blog post drafted.        |
| **W4**       | Hosted MCP deployed. Screenshots taken. End-to-end test.                                                                     |
| **W5**       | Submission filed.                                                                                                            |
| **W6–W8+**   | Anthropic review. Iterate. **Approval timeline depends entirely on Anthropic's queue — could be 1 week, could be 2 months.** |

Marketing's 1–2 week worst case + Nikola's 3-week worst case = **realistic submission readiness in ~4 weeks** if nothing slips.

---

## Risks / unknowns

| Risk                                                        | Mitigation                                                                                                                        |
| ----------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| **Anthropic review queue is long**                          | File initial inquiry early (W0), email `mcp-review@anthropic.com` for timeline visibility                                         |
| **Privacy policy update stuck in legal**                    | Gjorgji escalates separately, doesn't depend on Alessandro pushing                                                                |
| **Free-trial decision blocks new-user flow**                | Gjorgji forces a leadership decision in W1 — can't be left for W4                                                                 |
| **OAuth design rabbit holes**                               | Nikola asked to ship the _minimum viable_ spec (JWT + scopes + discovery + DCR) and defer revocation UI / scope refinement        |
| **Anthropic's Acceptable Use Policy on PII**                | Read [Anthropic AUP](https://www.anthropic.com/legal/aup) before submission — creator emails/demographics are sensitive territory |
| **Existing `influencers.club/privacy-policy` predates MCP** | Already flagged to Alessandro as item 9                                                                                           |

---

## References

- Anthropic submission form: https://clau.de/mcp-directory-submission
- Anthropic submission docs: https://claude.com/docs/connectors/building/submission
- Pre-submission checklist: https://claude.com/docs/connectors/building/review-criteria
- Escalation contact: mcp-review@anthropic.com
- Public repo: https://github.com/Influencers-Club/influencers-club-mcp
- Jira ticket: AAH-97
