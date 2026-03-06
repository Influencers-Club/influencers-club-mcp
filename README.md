# Influencers Club MCP Server

> **Beta** — This project is under active development. It works and can be tested, but expect changes before the stable release.

MCP server for the [Influencers Club API](https://docs.influencers.club/) — creator enrichment, discovery, audience analysis, content data, batch operations, and account management.

## Prerequisites

- Python 3.10+
- An [Influencers Club API key](https://docs.influencers.club/#authentication)

## Installation

### pip (recommended)

```bash
pip install .
```

### From source

```bash
git clone https://github.com/Influencers-Club/influencers-club-mcp.git
cd influencers-club-mcp
pip install -e .
```

### Docker

```bash
docker build -t influencers-club-mcp .
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
        "-e", "INFLUENCERS_CLUB_API_KEY=your_api_key_here",
        "influencers-club-mcp"
      ]
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

After configuring, restart your client. The server will appear as "influencers-club".

## Available Tools (24)

### Creator Discovery

| Tool | Description | Cost |
|---|---|---|
| `discover_creators` | Search creators with filters (followers, engagement, location, etc.) | 0.01/creator |
| `find_similar_creators` | Find creators similar to a seed creator | 0.01/creator |
| `audience_overlap` | Compare audience overlap between 2-10 creators | 1 credit |

### Enrichment

| Tool | Description | Cost |
|---|---|---|
| `enrich_by_email_basic` | Basic creator lookup by email | 0.1 credits |
| `enrich_by_email_advanced` | Advanced multi-platform lookup by email | 2 credits |
| `enrich_by_handle` | Full enriched profile with lookalikes & audience | 1 credit |
| `enrich_by_handle_raw` | Raw scraper data by handle + platform | 0.03 credits |
| `connected_socials` | Discover verified linked social accounts | 0.5 credits |

### Content Data

| Tool | Description | Cost |
|---|---|---|
| `get_creator_posts` | Fetch recent posts with engagement metrics | 0.03 credits |
| `get_post_details` | Deep content analysis (comments, transcript, audio) | 0.03 credits |

### Batch Enrichment

| Tool | Description | Cost |
|---|---|---|
| `create_batch_enrichment` | Upload CSV for batch processing | varies |
| `get_batch_status` | Check batch job progress | free |
| `get_batch_results` | Download completed batch (CSV or JSON) | free |
| `resume_batch` | Resume a paused batch | free |

### Discovery Reference Data

| Tool | Description | Cost |
|---|---|---|
| `get_languages` | Available languages for filtering | free |
| `get_locations` | Available locations per platform | free |
| `get_brands` | Available brand identifiers | free |
| `get_youtube_topics` | Available YouTube topics | free |
| `get_twitch_games` | Available Twitch games | free |
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

**Find similar creators for campaign scaling:**

> "I like the creator @MrBeast on YouTube. Find 10 similar creators with at least 100k followers."

**Compare audience overlap:**

> "Compare the audience overlap between @nike, @adidas, and @puma on Instagram."

**Get a creator's recent posts:**

> "Show me the latest posts from @garyvee on TikTok with engagement metrics."

**Find all connected social accounts:**

> "What other social media accounts does @cristiano have linked to their Instagram?"

**Check your remaining API credits:**

> "How many credits do I have left?"

## Supported Platforms

| Capability | Platforms |
|---|---|
| Enrichment | Instagram, TikTok, YouTube, OnlyFans, X/Twitter, Twitch, Facebook, Pinterest, Discord, Snapchat, LinkedIn |
| Discovery | Instagram, TikTok, YouTube, OnlyFans, X/Twitter, Twitch |
| Content Data | Instagram, TikTok, YouTube |
| Audience Overlap | Instagram, TikTok, YouTube |

## Privacy Policy

This MCP server acts as a pass-through to the [Influencers Club API](https://docs.influencers.club/). It does not collect, store, or log any user data, conversation data, or API responses. All data flows directly between Claude and the Influencers Club API using your personal API key. For the Influencers Club data and privacy practices, refer to the [Influencers Club Privacy Policy](https://influencers.club/privacy-policy).

## Support

- **Email:** shaklev@influencers.club
- **GitHub Issues:** [github.com/Influencers-Club/influencers-club-mcp/issues](https://github.com/Influencers-Club/influencers-club-mcp/issues)

## License

MIT
