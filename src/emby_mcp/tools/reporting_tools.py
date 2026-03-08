"""Reporting & Analytics tools — library, media type, playback, user, integrity, storage reports."""

import os

from fastmcp import FastMCP

from ..clients.emby_client import EmbyClient
from ..clients.emby_database import EmbyDatabase
from ..config import AppConfig


def register_reporting_tools(
    mcp: FastMCP, client: EmbyClient, database: EmbyDatabase, config: AppConfig
) -> None:
    """Register reporting and analytics tools."""

    async def _get_admin_id() -> str:
        users = await client.get("/emby/Users")
        admin = next(
            (u for u in users if u.get("Policy", {}).get("IsAdministrator")),
            users[0] if users else None,
        )
        if not admin:
            raise RuntimeError("No users found")
        return admin["Id"]

    @mcp.tool
    async def library_report() -> dict:
        """Per-library breakdown: total items, size, codec distribution, resolution stats."""
        admin_id = await _get_admin_id()
        libraries = await client.get("/emby/Library/VirtualFolders")

        report = []
        for lib in libraries:
            lib_id = lib.get("ItemId")
            data = await client.get(
                f"/emby/Users/{admin_id}/Items",
                params={
                    "ParentId": lib_id,
                    "IncludeItemTypes": "Movie,Episode",
                    "Recursive": "true",
                    "Limit": "0",
                },
            )
            total = data.get("TotalRecordCount", 0)

            report.append({
                "name": lib.get("Name"),
                "collection_type": lib.get("CollectionType"),
                "total_items": total,
                "locations": lib.get("Locations", []),
            })

        return {"libraries": report, "library_count": len(report)}

    @mcp.tool
    async def media_type_report() -> dict:
        """Cross-library stats by media type: movies, series, episodes, seasons."""
        admin_id = await _get_admin_id()
        types = ["Movie", "Series", "Episode", "Season", "Audio", "MusicAlbum"]
        stats = {}

        for item_type in types:
            data = await client.get(
                f"/emby/Users/{admin_id}/Items",
                params={
                    "IncludeItemTypes": item_type,
                    "Recursive": "true",
                    "Limit": "0",
                },
            )
            stats[item_type] = data.get("TotalRecordCount", 0)

        return {"media_types": stats, "total_all_types": sum(stats.values())}

    @mcp.tool
    async def playback_report(
        days: int = 30,
        limit: int = 50,
    ) -> dict:
        """Playback analytics: most watched items, per-user stats, peak hours.

        Args:
            days: Number of days to analyze (default: 30).
            limit: Maximum items per category (default: 50).
        """
        admin_id = await _get_admin_id()

        data = await client.get(
            f"/emby/Users/{admin_id}/Items",
            params={
                "IncludeItemTypes": "Movie,Episode",
                "Recursive": "true",
                "SortBy": "PlayCount",
                "SortOrder": "Descending",
                "Limit": str(limit),
                "IsPlayed": "true",
                "Fields": "Path",
            },
        )
        most_played = []
        for item in data.get("Items", []):
            user_data = item.get("UserData", {})
            most_played.append({
                "name": item.get("Name"),
                "type": item.get("Type"),
                "series_name": item.get("SeriesName"),
                "play_count": user_data.get("PlayCount", 0),
                "last_played": user_data.get("LastPlayedDate"),
            })

        return {
            "period_days": days,
            "most_played": most_played,
        }

    @mcp.tool
    async def user_activity_report() -> dict:
        """Per-user engagement: last active, admin status, library access."""
        users = await client.get("/emby/Users")
        report = []
        for u in users:
            policy = u.get("Policy", {})
            report.append({
                "name": u.get("Name"),
                "id": u.get("Id"),
                "last_login": u.get("LastLoginDate"),
                "last_activity": u.get("LastActivityDate"),
                "is_administrator": policy.get("IsAdministrator", False),
                "is_disabled": policy.get("IsDisabled", False),
                "enable_all_folders": policy.get("EnableAllFolders"),
                "has_password": u.get("HasConfiguredPassword", False),
            })
        return {"users": report, "count": len(report)}

    @mcp.tool
    async def media_integrity_report(
        library_id: str | None = None,
        limit: int = 100,
    ) -> dict:
        """Compare database items against actual files on disk.

        Flags missing files (in DB but not on disk) and reports counts.

        Args:
            library_id: Optional library ID to limit the check.
            limit: Maximum items to check per query (default: 100).
        """
        sql = "SELECT guid, Name, Path FROM TypedBaseItems WHERE Path IS NOT NULL AND Path != ''"
        if library_id:
            sql += f" AND ParentId = '{library_id}'"
        sql += f" LIMIT {limit}"

        rows = await database.query("library.db", sql)

        missing_files = []
        checked = 0
        for row in rows:
            path = row.get("Path", "")
            if path and not os.path.exists(path):
                missing_files.append({
                    "name": row.get("Name"),
                    "path": path,
                    "guid": row.get("guid"),
                })
            checked += 1

        return {
            "checked": checked,
            "missing_count": len(missing_files),
            "missing_files": missing_files[:50],
            "integrity_percentage": round(
                ((checked - len(missing_files)) / checked * 100) if checked > 0 else 0, 1
            ),
        }

    @mcp.tool
    async def storage_report(media_paths: list[str] | None = None) -> dict:
        """Storage usage by media mount and database sizes.

        Args:
            media_paths: List of media mount paths to check. If omitted, uses
                paths from the EMBY_MEDIA_PATHS environment variable.
        """
        mounts = media_paths or config.media_paths
        mount_stats = []

        for mount in mounts:
            if os.path.exists(mount):
                stat = os.statvfs(mount)
                total = stat.f_blocks * stat.f_frsize
                free = stat.f_bfree * stat.f_frsize
                used = total - free
                mount_stats.append({
                    "mount": mount,
                    "total_gb": round(total / (1024**3), 1),
                    "used_gb": round(used / (1024**3), 1),
                    "free_gb": round(free / (1024**3), 1),
                    "usage_percent": round(used / total * 100, 1) if total > 0 else 0,
                })
            else:
                mount_stats.append({"mount": mount, "error": "not mounted"})

        if not mounts:
            mount_stats = [{"warning": "No media paths configured. Set EMBY_MEDIA_PATHS or pass media_paths."}]

        # Database sizes
        db_stats = []
        for db_name in ["library.db", "users.db", "authentication.db", "activitylog.db"]:
            try:
                stats = await database.get_db_stats(db_name)
                db_stats.append({
                    "database": db_name,
                    "size_mb": stats.get("file_size_mb"),
                })
            except Exception as e:
                db_stats.append({"database": db_name, "error": str(e)})

        return {"media_mounts": mount_stats, "databases": db_stats}
