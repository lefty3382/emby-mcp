# Changelog

All notable changes to this project will be documented in this file.

## [1.2.0] - 2026-04-20

### Fixed
- **transcode_diagnostics**: Removed the `nvidia-smi` probe — the MCP container doesn't ship `nvidia-smi` and, more importantly, runs in a separate container from Emby, so a binary presence check on the MCP side was never a valid signal for Emby's GPU state. Replaced `gpu_available`/`gpu_info` with a `hardware_acceleration_config` object sourced from Emby's own `/System/Configuration/encoding` endpoint (reports `enabled`, `backends_configured`, and enabled NVENC/CUDA/QSV/VAAPI codec IDs). The per-transcode `hardware_acceleration_type` field already surfaced live state and remains the authoritative live signal.
- **connectivity_check**: Removed the `nvidia-smi` GPU check for the same reason; added a `hardware_encoding` check that queries Emby's encoding config and reports `enabled` + `has_hw_encoder`.

### Changed
- **Docstring clarity**: `transcode_diagnostics` now explicitly documents that the top-level field is configured intent (not live GPU health), and directs callers to the per-transcode `hardware_acceleration_type` as the live signal.

### Context
- The `nvidia-smi`-based probe produced identical `gpu_available: false` output whether Emby was hardware-transcoding normally or silently falling back to software after a driver hang (confirmed during a 2026-04-12 NVIDIA Xid 140 incident on VM 106 — see `docs/issues/transcode-diagnostics-gpu-false-negative.md`). The new probe reports real configuration; live hang detection remains the responsibility of journal/Xid monitoring outside the MCP.

## [1.1.0] - 2026-03-08

### Fixed
- **get_server_logs**: Fixed file extension filter — was looking for `.log` files but Emby writes `.txt` logs (`embyserver.txt`, `embyserver-<id>.txt`). This caused the tool to always return "No log files found".
- **get_server_logs**: Now reads up to 2 most recent log files (active + last rotated) instead of only the single most recent, matching `analyze_logs` behavior and catching activity across log rotations.
- **Stateless HTTP transport**: Added `stateless_http=True` to FastMCP server startup. Without this, sessions expired between tool calls after container restarts, causing "Session not found" errors.

### Changed
- **Media paths are now configurable**: Removed hardcoded media mount paths from `storage_report`, `connectivity_check`, and `audit_paths`. Paths are now configured via the `EMBY_MEDIA_PATHS` environment variable (comma-separated) or passed as tool parameters.
- **config.py**: Added `media_paths` field populated from `EMBY_MEDIA_PATHS` env var.
- **docker-compose.yaml**: Genericized volume mounts — uses `EMBY_CONFIG_HOST_PATH` env var instead of hardcoded paths. Media library mounts shown as commented examples.
- **.env.example**: Added `EMBY_CONFIG_HOST_PATH` and `EMBY_MEDIA_PATHS` variables with documentation.
- **README.md**: Comprehensive rewrite — full tool catalog with descriptions, deployment guide, configuration reference, architecture overview, and Docker Compose examples.

### Security
- Removed hardcoded IP addresses, usernames, and infrastructure-specific paths from source code, docker-compose, README, and docstrings. The repository is now safe for public hosting without exposing deployment details.

## [1.0.0] - 2026-03-06

### Added
- Initial release with 44 tools across 8 categories.
- **Server & System** (4): server info, active streams, scheduled tasks, server logs.
- **Users & Sessions** (9): list/create/update/delete users, sessions, playback history, library access.
- **Libraries** (3): list, stats, scan.
- **Items & Search** (7): movies, series, seasons, episodes, item details, recently added, search.
- **Playlists & Collections** (5): list/create playlists, get/add items, list collections.
- **Database** (8): SQL query, schema discovery, DB stats, Emby Connect status, playlist integrity, path audit, path surgery (safety-gated), playlist delete (safety-gated).
- **Reporting & Analytics** (6): library, media type, playback, user activity, media integrity, storage reports.
- **Diagnostics & Troubleshooting** (4): log analysis, transcode diagnostics, connectivity check, playback troubleshooting.
- EmbyClient async REST API wrapper with lazy session management.
- EmbyDatabase async SQLite access with 5 safety gates for write operations.
- Docker deployment with FastMCP 3.x Streamable HTTP transport.
