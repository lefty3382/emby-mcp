# Emby MCP Server

MCP server for complete Emby management — REST API operations, SQLite database access, reporting, and diagnostics.

## Overview

44 tools across 8 categories:
- **Server & System** (4) — server info, active streams, scheduled tasks, logs
- **Users & Sessions** (9) — list/create/update/delete users, sessions, playback history
- **Libraries** (3) — list, stats, scan
- **Items & Search** (7) — movies, series, seasons, episodes, search
- **Playlists & Collections** (5) — list, create, add items, collections
- **Database** (8) — query, schema discovery, path audit, Emby Connect status, safety-gated writes
- **Reporting & Analytics** (6) — library, media type, playback, user activity, integrity, storage reports
- **Diagnostics & Troubleshooting** (4) — log analysis, transcode diagnostics, connectivity, playback troubleshooting

## Deployment

Co-located on VM 106 alongside Emby for localhost API and direct database access.

### Quick Start

1. Copy `.env.example` to `.env` and set your Emby API key
2. Build and start:
   ```bash
   docker compose up -d
   ```
3. Configure Claude Code:
   ```bash
   claude mcp add emby --transport http http://10.0.40.36:8486/mcp --scope user
   ```

## Architecture

Two backends:
- **EmbyClient** — async REST API wrapper (aiohttp) for Emby's HTTP API
- **EmbyDatabase** — async SQLite access (aiosqlite) with 5 safety gates for write operations

### Database Write Safety Gates

1. **Confirm required** — preview mode by default, must pass `confirm=true` to execute
2. **Container check** — verifies Emby container is stopped before any write
3. **WAL verification** — confirms no WAL/SHM files present (clean shutdown)
4. **Auto backup** — copies database to timestamped backup before write
5. **Integrity check** — runs `PRAGMA integrity_check` after write

## License

MIT
