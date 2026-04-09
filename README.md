# Influencers Club MCP Server

> **Beta** — This project is under active development. It works and can be tested, but expect changes before the stable release.

MCP server for the [Influencers Club API](https://docs.influencers.club/) — creator enrichment, discovery, audience analysis, content data, batch operations, and account management.

## Prerequisites

- Python 3.10+ or [Docker Desktop](https://www.docker.com/products/docker-desktop/)
- An [Influencers Club API key](https://docs.influencers.club/#authentication)

## Quick Start (pip)

```bash
git clone https://github.com/Influencers-Club/influencers-club-mcp.git
cd influencers-club-mcp
pip install -e .
```

Then add to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "influencers-club": {
      "command": "influencers-club-mcp",
      "env": {
        "INFLUENCERS_CLUB_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

Restart Claude Desktop — the server will appear as "influencers-club". That's it.

> **Where do files go?** By default, exported CSVs and uploads are saved to `exports/` and `imports/` inside the cloned repo folder. No extra configuration needed.
>
> To use a custom location, add these env vars:
>
> ```json
> "EXPORT_HOST_DIR": "/your/custom/exports",
> "IMPORT_HOST_DIR": "/your/custom/imports",
> "OUTPUT_DIR": "/your/custom/exports",
> "IMPORTS_DIR": "/your/custom/imports"
> ```

## Other Clients

### Claude Code

Add to your project's `.mcp.json` or global `~/.claude/settings.json`:

```json
{
  "mcpServers": {
    "influencers-club": {
      "command": "influencers-club-mcp",
      "env": {
        "INFLUENCERS_CLUB_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

### VS Code / Cursor

Add to `.vscode/mcp.json` in your project:

```json
{
  "servers": {
    "influencers-club": {
      "command": "influencers-club-mcp",
      "env": {
        "INFLUENCERS_CLUB_API_KEY": "your_api_key_here"
      }
    }
  }
}
```

## Docker (Advanced)

Use Docker if you want filesystem isolation or prefer containerized deployments.

```bash
git clone https://github.com/Influencers-Club/influencers-club-mcp.git
cd influencers-club-mcp
docker build -t influencers-club-mcp .
```

Add to your Claude Desktop `claude_desktop_config.json`:

```json
{
  "mcpServers": {
    "influencers-club": {
      "command": "docker",
      "args": [
        "run", "-i", "--rm",
        "-p", "127.0.0.1:8090:8090",
        "-e", "INFLUENCERS_CLUB_API_KEY=your_api_key_here",
        "-e", "UPLOAD_PORT=8090",
        "-e", "UPLOAD_BIND=0.0.0.0",
        "-v", "/path/to/exports:/exports",
        "-v", "/path/to/imports:/imports",
        "-e", "EXPORT_HOST_DIR=/path/to/exports",
        "-e", "IMPORT_HOST_DIR=/path/to/imports",
        "influencers-club-mcp"
      ]
    }
  }
}
```

> **Note:** Replace `/path/to/exports` and `/path/to/imports` with actual paths on your machine. The path appears 4 times — update all of them.
>
> **Examples by OS:**
> - **macOS/Linux:** `/Users/john/influencers-club-mcp/exports`
> - **Windows:** `C:\\Users\\John\\Desktop\\influencers-club-mcp\\exports` (use double backslashes)

After configuring, restart your client. The server will appear as "influencers-club".

## Available Tools (29)

### Creator Discovery

| Tool | Description | Cost |
|---|---|---|
| `discover_creators` | AI semantic search with filters (followers, engagement, location, etc.) | 0.01/creator |
| `discover_creators_to_file` | Multi-page discovery with CSV export to disk | 0.01/creator |
| `find_similar_creators` | Find creators similar to a seed creator | 0.01/creator |
| `audience_overlap` | Compare audience overlap between 2-10 creators (auto-visualized) | 1 credit |

### Enrichment

| Tool | Description | Cost |
|---|---|---|
| `enrich_by_handle` | Full enriched profile: email, demographics, audience, income, brand deals | 1 credit |
| `enrich_by_handle_raw` | Basic profile data: bio, followers, verification status | 0.03 credits |
| `enrich_by_email` | Find creator profiles from an email | 0.05 credits |
| `connected_socials` | Discover all linked social accounts for a creator | 0.5 credits |

### Content Data

| Tool | Description | Cost |
|---|---|---|
| `get_creator_posts` | Fetch recent posts with engagement metrics (IG, TikTok, YouTube) | 0.15 credits |
| `get_post_details` | Deep content analysis (comments, transcript, audio) | 0.03 credits |

### Batch Enrichment

| Tool | Description | Cost |
|---|---|---|
| `create_batch_enrichment` | Upload CSV of up to 10,000 handles/emails for bulk processing | varies |
| `get_batch_status` | Check batch job progress (auto-polls every 35s) | free |
| `download_batch_results` | Download completed batch results as CSV | free |
| `resume_batch` | Resume a paused batch after adding credits | free |

### File Management

| Tool | Description | Cost |
|---|---|---|
| `get_upload_url` | Get the browser upload page URL for batch CSV files | free |
| `wait_for_upload` | Auto-detect when a file has been uploaded | free |
| `list_import_files` | List uploaded CSV files ready for enrichment | free |
| `list_export_files` | List exported result files | free |
| `setup_export_path` | Configure where exported files are saved | free |

### Discovery Reference Data

| Tool | Description | Cost |
|---|---|---|
| `get_languages` | Available languages for filtering | free |
| `get_locations` | Available locations per platform | free |
| `get_brands` | Available brand identifiers | free |
| `get_youtube_topics` | Available YouTube topics | free |
| `get_games` | Available Twitch games | free |
| `get_audience_brand_categories` | Audience brand categories | free |
| `get_audience_brand_names` | Audience brand names | free |
| `get_audience_interests` | Audience interest categories | free |
| `get_audience_locations` | Audience geographic locations | free |

### Account

| Tool | Description | Cost |
|---|---|---|
| `check_credits` | Check account credits balance | free |

## Usage Examples

**Find fitness influencers on Instagram:**
> "Find 5 Instagram creators with 50k-500k followers who post about fitness and have an engagement rate above 3%."

**Enrich a creator profile by handle:**
> "Get me the full profile for @cristiano on Instagram, including audience demographics."

**Batch enrich a CSV of emails:**
> "I have a CSV of 3,000 emails to batch enrich." — Claude will open the upload page for you.

**Find similar creators for campaign scaling:**
> "I like the creator @MrBeast on YouTube. Find 10 similar creators with at least 100k followers."

**Compare audience overlap:**
> "Compare the audience overlap between @nike, @adidas, and @puma on Instagram." — Claude will generate a Venn diagram.

**Get a creator's recent posts:**
> "Show me the latest posts from @garyvee on TikTok with engagement metrics."

**Find all connected social accounts:**
> "What other social media accounts does @cristiano have linked to their Instagram?"

**Check your remaining API credits:**
> "How many credits do I have left?"

## Batch Enrichment Modes

| Mode | Input | Cost | Requires Platform |
|------|-------|------|-------------------|
| `basic` | emails | 0.05/record | No |
| `raw` | handles | 0.03/record | Yes |
| `full` | handles | 1/record | Yes |

For large files (100+ entries), Claude opens a browser upload page at `http://localhost:8090`. Drag-and-drop your CSV — Claude auto-detects the upload and starts processing. For smaller batches (under 100), Claude enriches them in parallel automatically.

The upload page accepts multi-column CSVs and automatically extracts the correct column.

## Supported Platforms

| Capability | Platforms |
|---|---|
| Enrichment | Instagram, TikTok, YouTube, OnlyFans, X/Twitter, Twitch, LinkedIn (raw mode only) |
| Discovery | Instagram, TikTok, YouTube, OnlyFans, X/Twitter, Twitch |
| Content Data | Instagram, TikTok, YouTube |
| Audience Overlap | Instagram, TikTok, YouTube |

## Environment Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `INFLUENCERS_CLUB_API_KEY` | Yes | — | Your Influencers Club API key |
| `UPLOAD_PORT` | No | 8090 | Port for the browser upload page |
| `UPLOAD_BIND` | No | 127.0.0.1 | Bind address. Set to `0.0.0.0` inside Docker. |
| `UPLOAD_HOST` | No | localhost | Hostname for the upload URL. Set to your IP if Docker runs remotely. |
| `EXPORT_HOST_DIR` | No | — | Host path for exported files |
| `IMPORT_HOST_DIR` | No | — | Host path for uploaded files |
| `MAX_CALLS_PER_MINUTE` | No | 300 | Client-side rate limit |

## Privacy Policy

This MCP server acts as a pass-through to the [Influencers Club API](https://docs.influencers.club/). It does not collect, store, or log any user data, conversation data, or API responses. All data flows directly between Claude and the Influencers Club API using your personal API key. For the Influencers Club data and privacy practices, refer to the [Influencers Club Privacy Policy](https://influencers.club/privacy-policy).

## Support

- **Email:** shaklev@influencers.club
- **GitHub Issues:** [github.com/Influencers-Club/influencers-club-mcp/issues](https://github.com/Influencers-Club/influencers-club-mcp/issues)

## License

MIT
