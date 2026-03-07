"""Diagnostic & Troubleshooting tools — logs, transcode, connectivity, playback."""

import asyncio
import os
import re
from collections import Counter

from fastmcp import FastMCP

from ..clients.emby_client import EmbyClient
from ..clients.emby_database import EmbyDatabase
from ..config import AppConfig


def register_diagnostic_tools(
    mcp: FastMCP,
    client: EmbyClient,
    database: EmbyDatabase,
    config: AppConfig,
) -> None:
    """Register diagnostic and troubleshooting tools."""

    @mcp.tool
    async def analyze_logs(
        severity: str = "error",
        hours: int = 24,
        limit: int = 200,
    ) -> dict:
        """Parse and analyze Emby server logs for errors and patterns.

        Args:
            severity: Minimum severity — 'error', 'warn', 'info', 'debug' (default: 'error').
            hours: How many hours back to analyze (default: 24).
            limit: Maximum lines to return (default: 200).
        """
        log_dir = config.log_path
        if not os.path.isdir(log_dir):
            return {"error": f"Log directory not found: {log_dir}"}

        log_files = sorted(
            [f for f in os.listdir(log_dir) if f.endswith(".log")],
            key=lambda f: os.path.getmtime(os.path.join(log_dir, f)),
            reverse=True,
        )
        if not log_files:
            return {"error": "No log files found"}

        severity_levels = {
            "debug": ["DEBUG", "INFO", "WARN", "ERROR", "FATAL"],
            "info": ["INFO", "WARN", "ERROR", "FATAL"],
            "warn": ["WARN", "ERROR", "FATAL"],
            "error": ["ERROR", "FATAL"],
        }
        allowed = severity_levels.get(severity.lower(), ["ERROR", "FATAL"])

        matching_lines = []
        error_patterns = Counter()

        for log_file in log_files[:3]:  # Check up to 3 most recent log files
            path = os.path.join(log_dir, log_file)
            with open(path, "r", errors="replace") as f:
                for line in f:
                    if any(level in line for level in allowed):
                        matching_lines.append(line.rstrip())
                        # Extract error pattern (first meaningful phrase after severity)
                        match = re.search(r"(?:ERROR|WARN|FATAL)\s*[:\-]?\s*(.{10,60})", line)
                        if match:
                            error_patterns[match.group(1).strip()] += 1

        # Return most recent lines
        matching_lines = matching_lines[-limit:]
        top_patterns = error_patterns.most_common(10)

        return {
            "log_files_checked": log_files[:3],
            "severity_filter": severity,
            "total_matching": len(matching_lines),
            "top_error_patterns": [
                {"pattern": p, "count": c} for p, c in top_patterns
            ],
            "lines": matching_lines,
        }

    @mcp.tool
    async def transcode_diagnostics() -> dict:
        """Active and recent transcode sessions with GPU/CPU details and performance."""
        sessions = await client.get("/emby/Sessions")

        active_transcodes = []
        for s in sessions:
            tc = s.get("TranscodingInfo")
            if tc:
                active_transcodes.append({
                    "user": s.get("UserName"),
                    "device": s.get("DeviceName"),
                    "item": s.get("NowPlayingItem", {}).get("Name"),
                    "video_codec_from": tc.get("VideoCodec"),
                    "audio_codec_from": tc.get("AudioCodec"),
                    "container": tc.get("Container"),
                    "width": tc.get("Width"),
                    "height": tc.get("Height"),
                    "is_video_direct": tc.get("IsVideoDirect"),
                    "is_audio_direct": tc.get("IsAudioDirect"),
                    "bitrate": tc.get("Bitrate"),
                    "completion_pct": tc.get("CompletionPercentage"),
                    "framerate": tc.get("Framerate"),
                    "hardware_acceleration_type": tc.get("HardwareAccelerationType"),
                })

        # Check GPU availability
        gpu_available = False
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi", "--query-gpu=name,utilization.gpu",
                "--format=csv,noheader",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                gpu_available = True
                gpu_info = stdout.decode().strip()
            else:
                gpu_info = "nvidia-smi failed"
        except FileNotFoundError:
            gpu_info = "nvidia-smi not found in container"

        return {
            "active_transcodes": active_transcodes,
            "transcode_count": len(active_transcodes),
            "gpu_available": gpu_available,
            "gpu_info": gpu_info,
        }

    @mcp.tool
    async def connectivity_check() -> dict:
        """Verify Emby server health: API, database, NFS mounts, GPU, container."""
        checks = {}

        # API check
        try:
            info = await client.get("/emby/System/Info")
            checks["api"] = {
                "status": "ok",
                "version": info.get("Version"),
                "server_name": info.get("ServerName"),
            }
        except Exception as e:
            checks["api"] = {"status": "error", "message": str(e)}

        # Database check
        for db_name in ["library.db", "users.db"]:
            try:
                stats = await database.get_db_stats(db_name)
                checks[db_name] = {
                    "status": "ok",
                    "size_mb": stats.get("file_size_mb"),
                    "integrity": stats.get("integrity"),
                }
            except Exception as e:
                checks[db_name] = {"status": "error", "message": str(e)}

        # NFS mount check
        for mount in ["/mnt/tank/film", "/mnt/dozer/film"]:
            if os.path.exists(mount) and os.path.ismount(mount):
                try:
                    entries = os.listdir(mount)
                    checks[mount] = {
                        "status": "ok",
                        "mounted": True,
                        "entries": len(entries),
                    }
                except Exception as e:
                    checks[mount] = {"status": "error", "message": str(e)}
            else:
                checks[mount] = {"status": "error", "mounted": False}

        # GPU check
        try:
            proc = await asyncio.create_subprocess_exec(
                "nvidia-smi", "--query-gpu=name", "--format=csv,noheader",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            if proc.returncode == 0:
                checks["gpu"] = {
                    "status": "ok",
                    "name": stdout.decode().strip(),
                }
            else:
                checks["gpu"] = {"status": "unavailable"}
        except FileNotFoundError:
            checks["gpu"] = {"status": "unavailable", "message": "nvidia-smi not in container"}

        # Container status
        try:
            proc = await asyncio.create_subprocess_exec(
                "docker", "ps", "--filter", "name=emby",
                "--format", "{{.Names}} {{.State}} {{.Status}}",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await proc.communicate()
            output = stdout.decode().strip()
            checks["emby_container"] = {
                "status": "ok" if "running" in output else "stopped",
                "detail": output or "not found",
            }
        except Exception as e:
            checks["emby_container"] = {"status": "error", "message": str(e)}

        # Overall status
        all_ok = all(
            c.get("status") == "ok" for c in checks.values()
            if isinstance(c, dict)
        )
        return {"overall": "healthy" if all_ok else "issues_detected", "checks": checks}

    @mcp.tool
    async def troubleshoot_playback(
        user_id: str | None = None,
        item_id: str | None = None,
    ) -> dict:
        """Diagnose playback issues for a user or item by correlating sessions and logs.

        Args:
            user_id: Optional user ID to filter by.
            item_id: Optional item ID to check.
        """
        result = {}

        # Get active sessions for context
        sessions = await client.get("/emby/Sessions")
        relevant_sessions = []
        for s in sessions:
            if user_id and s.get("UserId") != user_id:
                continue
            relevant_sessions.append({
                "user": s.get("UserName"),
                "device": s.get("DeviceName"),
                "client": s.get("Client"),
                "now_playing": s.get("NowPlayingItem", {}).get("Name"),
                "transcode_info": s.get("TranscodingInfo"),
                "play_state": s.get("PlayState"),
            })
        result["sessions"] = relevant_sessions

        # Get item info if specified
        if item_id:
            try:
                users = await client.get("/emby/Users")
                admin = next(
                    (u for u in users if u.get("Policy", {}).get("IsAdministrator")),
                    users[0],
                )
                item = await client.get(
                    f"/emby/Users/{admin['Id']}/Items/{item_id}",
                    params={"Fields": "Path,MediaSources"},
                )
                sources = item.get("MediaSources", [])
                result["item"] = {
                    "name": item.get("Name"),
                    "path": item.get("Path"),
                    "file_exists": os.path.exists(item.get("Path", "")),
                }
                if sources:
                    src = sources[0]
                    result["item"]["container"] = src.get("Container")
                    result["item"]["size_bytes"] = src.get("Size")
                    for stream in src.get("MediaStreams", []):
                        if stream.get("Type") == "Video":
                            result["item"]["video_codec"] = stream.get("Codec")
                            result["item"]["resolution"] = (
                                f"{stream.get('Width')}x{stream.get('Height')}"
                            )
                            break
            except Exception as e:
                result["item"] = {"error": str(e)}

        # Check recent error logs for playback issues
        log_dir = config.log_path
        if os.path.isdir(log_dir):
            log_files = sorted(
                [f for f in os.listdir(log_dir) if f.endswith(".log")],
                key=lambda f: os.path.getmtime(os.path.join(log_dir, f)),
                reverse=True,
            )
            playback_errors = []
            if log_files:
                path = os.path.join(log_dir, log_files[0])
                search_terms = ["playback", "transcode", "stream", "ffmpeg"]
                if user_id:
                    search_terms.append(user_id)
                with open(path, "r", errors="replace") as f:
                    for line in f:
                        if "ERROR" in line or "WARN" in line:
                            if any(term.lower() in line.lower() for term in search_terms):
                                playback_errors.append(line.rstrip())
                result["recent_playback_errors"] = playback_errors[-20:]

        return result
