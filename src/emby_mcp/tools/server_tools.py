"""Server & System tools — server info, streams, tasks, logs."""

import os
from datetime import datetime

from fastmcp import FastMCP

from ..clients.emby_client import EmbyClient
from ..config import AppConfig


def register_server_tools(
    mcp: FastMCP, client: EmbyClient, config: AppConfig
) -> None:
    """Register server and system monitoring tools."""

    @mcp.tool
    async def get_server_info() -> dict:
        """Get Emby server information including version, OS, uptime, and Premiere status."""
        try:
            info = await client.get("/emby/System/Info")
            return {
                "server_name": info.get("ServerName"),
                "version": info.get("Version"),
                "operating_system": info.get("OperatingSystem"),
                "server_id": info.get("Id"),
                "local_address": info.get("LocalAddress"),
                "wan_address": info.get("WanAddress"),
                "has_premiere": info.get("SupportsAutoRunAtStartup"),
                "can_self_restart": info.get("CanSelfRestart"),
                "program_data_path": info.get("ProgramDataPath"),
                "items_by_name_path": info.get("ItemsByNamePath"),
                "log_path": info.get("LogPath"),
                "cache_path": info.get("CachePath"),
            }
        except Exception as e:
            return {"error": str(e), "status": "unreachable"}

    @mcp.tool
    async def get_active_streams() -> dict:
        """Get currently active playback streams with user, media, and transcode details."""
        sessions = await client.get("/emby/Sessions")
        active = []
        for s in sessions:
            if s.get("NowPlayingItem"):
                item = s["NowPlayingItem"]
                stream = {
                    "user": s.get("UserName"),
                    "device": s.get("DeviceName"),
                    "client": s.get("Client"),
                    "item_name": item.get("Name"),
                    "item_type": item.get("Type"),
                    "series_name": item.get("SeriesName"),
                    "play_state": s.get("PlayState", {}),
                }
                if s.get("TranscodingInfo"):
                    tc = s["TranscodingInfo"]
                    stream["transcode"] = {
                        "is_transcoding": True,
                        "video_codec": tc.get("VideoCodec"),
                        "audio_codec": tc.get("AudioCodec"),
                        "container": tc.get("Container"),
                        "width": tc.get("Width"),
                        "height": tc.get("Height"),
                        "hardware_acceleration": tc.get(
                            "IsVideoDirect", False
                        ) is False,
                        "completion_percentage": tc.get("CompletionPercentage"),
                    }
                else:
                    stream["transcode"] = {"is_transcoding": False, "direct_play": True}
                active.append(stream)
        return {"active_streams": active, "count": len(active)}

    @mcp.tool
    async def get_scheduled_tasks() -> dict:
        """List all scheduled tasks with their status, last run time, and triggers."""
        tasks = await client.get("/emby/ScheduledTasks")
        result = []
        for t in tasks:
            result.append({
                "name": t.get("Name"),
                "state": t.get("State"),
                "category": t.get("Category"),
                "description": t.get("Description"),
                "last_execution_result": t.get("LastExecutionResult", {}),
                "triggers": t.get("Triggers", []),
            })
        return {"tasks": result, "count": len(result)}

    @mcp.tool
    async def get_server_logs(
        severity: str = "all",
        limit: int = 100,
        search: str | None = None,
    ) -> dict:
        """Read and filter Emby server log files.

        Args:
            severity: Filter by severity — 'all', 'error', 'warn', 'info', 'debug'.
            limit: Maximum lines to return (default: 100).
            search: Optional text search filter within log lines.
        """
        log_dir = config.log_path
        if not os.path.isdir(log_dir):
            return {"error": f"Log directory not found: {log_dir}"}

        # Emby server logs: embyserver.txt (active) + embyserver-<id>.txt (rotated)
        log_files = sorted(
            [
                f for f in os.listdir(log_dir)
                if f.startswith("embyserver") and f.endswith(".txt")
            ],
            key=lambda f: os.path.getmtime(os.path.join(log_dir, f)),
            reverse=True,
        )
        if not log_files:
            return {"error": "No log files found"}

        # Read up to 2 most recent log files to catch activity across rotations
        lines = []
        severity_upper = severity.upper()
        files_checked = []

        for log_name in log_files[:2]:
            log_file = os.path.join(log_dir, log_name)
            files_checked.append(log_name)
            with open(log_file, "r", errors="replace") as f:
                for line in f:
                    if severity != "all":
                        if severity_upper not in line.upper():
                            continue
                    if search and search.lower() not in line.lower():
                        continue
                    lines.append(line.rstrip())

        # Return last N lines (most recent)
        lines = lines[-limit:]

        return {
            "log_files_checked": files_checked,
            "total_matching_lines": len(lines),
            "severity_filter": severity,
            "search_filter": search,
            "lines": lines,
        }
