# Emby MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) (MCP) server for complete Emby media server management. Provides 44 tools across 8 categories for AI assistants to monitor, manage, and troubleshoot Emby installations.

Built with [FastMCP](https://gofastmcp.com/) 3.x and designed to run co-located with Emby for localhost API access and direct database inspection.

## Features

### Server & System (4 tools)
- **get_server_info** — Server version, OS, paths, Premiere status
- **get_active_streams** — Currently playing media with transcode details
- **get_scheduled_tasks** — All scheduled tasks with status, last run, and triggers
- **get_server_logs** — Read and filter Emby server logs by severity and search term

### Users & Sessions (9 tools)
- **list_users** — All users with policy, access, and activity info
- **get_user_details** — Detailed profile for a specific user
- **create_user** / **delete_user** — User lifecycle management
- **update_user** — Modify user settings and policies
- **reset_password** — Reset a user's password
- **get_active_sessions** — All connected devices and clients
- **get_playback_history** — Per-user playback history
- **set_library_access** — Control which libraries a user can see

### Libraries (3 tools)
- **list_libraries** — All virtual folders with paths and collection types
- **get_library_stats** — Item counts and size per library
- **scan_library** — Trigger a library scan (full or by library ID)

### Items & Search (7 tools)
- **get_movies** — Browse movies with sorting and filtering
- **get_series** / **get_seasons** / **get_episodes** — TV show hierarchy browsing
- **get_item_details** — Full metadata for any item (media info, paths, streams)
- **get_recently_added** — Latest additions across libraries
- **search_items** — Full-text search across all media types

### Playlists & Collections (5 tools)
- **list_playlists** — All playlists with item counts
- **create_playlist** — Create new playlists
- **get_playlist_items** — List items in a playlist
- **add_playlist_items** — Add items to an existing playlist
- **list_collections** — Browse movie/TV collections

### Database (8 tools)
- **query_database** — Run read-only SQL queries against any Emby database
- **get_db_table_info** — Schema discovery (tables, columns, row counts)
- **get_db_statistics** — Database file size, WAL status, integrity
- **get_emby_connect_status** — Emby Connect linkage details for all users
- **check_playlist_integrity** — Cross-reference DB vs API playlist data
- **audit_paths** — Scan media paths and flag mismatches against expected prefixes
- **path_surgery** — Find/replace path prefixes in library.db (safety-gated)
- **delete_playlist** — Remove playlist from database (safety-gated)

### Reporting & Analytics (6 tools)
- **library_report** — Per-library item counts and locations
- **media_type_report** — Cross-library stats by media type
- **playback_report** — Most watched items and play counts
- **user_activity_report** — Per-user engagement and access status
- **media_integrity_report** — Compare DB items against files on disk
- **storage_report** — Storage usage by media mount and database sizes

### Diagnostics & Troubleshooting (4 tools)
- **analyze_logs** — Parse logs for error patterns with counts and time windows
- **transcode_diagnostics** — Active transcode sessions with GPU/CPU details
- **connectivity_check** — Verify API, database, mounts, GPU, and container health
- **troubleshoot_playback** — Diagnose playback issues by correlating sessions and logs

## Architecture

Two async backends:

- **EmbyClient** — async REST API wrapper (aiohttp) with lazy session management
- **EmbyDatabase** — async SQLite access (aiosqlite) for direct database queries

### Database Write Safety Gates

All database write operations (path_surgery, delete_playlist) enforce 5 safety gates:

1. **Confirm required** — preview mode by default, must pass `confirm=true` to execute
2. **Container check** — verifies Emby container is stopped before any write
3. **WAL verification** — confirms no WAL/SHM files present (clean shutdown)
4. **Auto backup** — copies database to timestamped backup before write
5. **Integrity check** — runs `PRAGMA integrity_check` after write

## Deployment

Designed to run as a Docker container alongside Emby on the same host. This enables:
- Localhost API access (fast, no network latency)
- Direct filesystem access to Emby's programdata (databases, logs)
- Docker socket access to check Emby container state (for write safety gates)
- Read-only access to media library mounts (for integrity checks)

### Prerequisites

- Docker and Docker Compose
- An Emby API key (Dashboard > Advanced > API Keys)
- Emby programdata directory accessible on the host

### Quick Start

1. Clone the repository:
   ```bash
   git clone https://github.com/lefty3382/emby-mcp.git
   cd emby-mcp
   ```

2. Copy `.env.example` to `.env` and configure:
   ```bash
   cp .env.example .env
   ```

   Required settings:
   ```env
   EMBY_API_KEY=your-api-key-here
   EMBY_CONFIG_HOST_PATH=/path/to/emby/programdata
   ```

   Optional settings:
   ```env
   EMBY_HOST=emby                    # Emby hostname (use Docker service name if on same network)
   EMBY_PORT=8096                    # Emby HTTP port
   EMBY_MEDIA_PATHS=/mnt/movies,/mnt/tv   # Comma-separated media mount paths (inside container)
   MCP_PORT=8486                     # MCP server port
   ```

3. Add media library volume mounts to `docker-compose.yaml`:
   ```yaml
   volumes:
     - /path/to/movies:/mnt/movies:ro
     - /path/to/tv:/mnt/tv:ro
   ```

4. Build and start:
   ```bash
   docker compose up -d
   ```

5. Configure your MCP client:
   ```bash
   # Claude Code
   claude mcp add emby --transport http http://<host>:8486/mcp --scope user
   ```

### Running on the Same Docker Network as Emby

If Emby runs in Docker on the same host, add `emby-mcp` to the same Docker Compose file or Docker network so it can reach Emby via Docker DNS (`emby`):

```yaml
services:
  emby:
    image: emby/embyserver:latest
    container_name: emby
    # ... your Emby config ...

  emby-mcp:
    build: .
    container_name: emby-mcp
    environment:
      - EMBY_HOST=emby          # Docker DNS name
      - EMBY_API_KEY=${EMBY_API_KEY}
      - EMBY_CONFIG_PATH=/emby-config
      - EMBY_MEDIA_PATHS=/mnt/movies,/mnt/tv
      - MCP_PORT=8486
    volumes:
      - /path/to/emby/programdata:/emby-config
      - /var/run/docker.sock:/var/run/docker.sock:ro
      - /path/to/movies:/mnt/movies:ro
      - /path/to/tv:/mnt/tv:ro
    ports:
      - "8486:8486"
    restart: unless-stopped
    depends_on:
      - emby
```

## Configuration

| Environment Variable | Required | Default | Description |
|---------------------|----------|---------|-------------|
| `EMBY_API_KEY` | Yes | — | Emby API key for REST API authentication |
| `EMBY_HOST` | No | `emby` | Emby server hostname or IP |
| `EMBY_PORT` | No | `8096` | Emby server HTTP port |
| `EMBY_CONFIG_PATH` | No | `/emby-config` | Path to Emby programdata inside the container |
| `EMBY_CONFIG_HOST_PATH` | Yes* | — | Host path to Emby programdata (used by docker-compose) |
| `EMBY_MEDIA_PATHS` | No | — | Comma-separated media mount paths (e.g., `/mnt/movies,/mnt/tv`) |
| `MCP_PORT` | No | `8486` | Port for the MCP server |

\* Required when using the provided `docker-compose.yaml`.

## Technology

- **Python 3.12** with async/await throughout
- **FastMCP 3.1.0** — MCP server framework with Streamable HTTP transport (stateless mode)
- **aiohttp** — async HTTP client for Emby REST API
- **aiosqlite** — async SQLite access for direct database queries

## License

MIT
