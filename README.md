# Influencers Club MCP Server

> **Beta** — This project is under active development. It works and can be tested, but expect changes before the stable release.

MCP server for the [Influencers Club API](https://docs.influencers.club/) — creator enrichment, discovery, audience analysis, content data, batch operations, and account management.

## Prerequisites

- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running
- An [Influencers Club API key](https://docs.influencers.club/#authentication)

## Installation

### Docker (recommended)

```bash
git clone https://github.com/Influencers-Club/influencers-club-mcp.git
cd influencers-club-mcp
docker build -t influencers-club-mcp .
```

### pip

```bash
pip install influencers-club-mcp
```

### From source

```bash
git clone https://github.com/Influencers-Club/influencers-club-mcp.git
cd influencers-club-mcp
pip install -e .
```

## Configuration

### Claude Desktop

Add to your `claude_desktop_config.json`:

**Using pip install:**

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

**Using Docker:**

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
        "-v", "/path/to/influencers-club-mcp/exports:/exports",
        "-v", "/path/to/influencers-club-mcp/imports:/imports",
        "-e", "EXPORT_HOST_DIR=/path/to/influencers-club-mcp/exports",
        "-e", "IMPORT_HOST_DIR=/path/to/influencers-club-mcp/imports",
        "influencers-club-mcp"
      ]
    }
  }
}
```

> **Note:** Replace `/path/to/influencers-club-mcp` with the actual path where you cloned the repo. The path appears 4 times — update all of them.
>
> **Examples by OS:**
> - **macOS/Linux:** `/Users/john/influencers-club-mcp`
> - **Windows:** `C:\\Users\\John\\Desktop\\influencers-club-mcp` (use double backslashes)

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

After configuring, restart your client. The server will appear as "influencers-club".

## Available Tools (28)

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

For large files (20+ entries), Claude opens a browser upload page at `http://localhost:8090`. Drag-and-drop your CSV — Claude auto-detects the upload and starts processing.

The upload page accepts multi-column CSVs and automatically extracts the correct column.

## Supported Platforms

| Capability | Platforms |
|---|---|
| Enrichment | Instagram, TikTok, YouTube, OnlyFans, X/Twitter, Twitch, Facebook, Pinterest, Discord, Snapchat, LinkedIn |
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
