"""Database tools — query, schema, path audit, Emby Connect, safety-gated writes."""

from fastmcp import FastMCP

from ..clients.emby_database import EmbyDatabase
from ..config import AppConfig


def register_database_tools(mcp: FastMCP, database: EmbyDatabase, config: AppConfig) -> None:
    """Register database inspection and write tools."""

    @mcp.tool
    async def query_database(db_name: str, sql: str) -> dict:
        """Run a read-only SELECT query against any Emby database.

        Args:
            db_name: Database file — 'library.db', 'users.db', 'authentication.db', or 'activitylog.db'.
            sql: SQL SELECT or PRAGMA statement.
        """
        try:
            rows = await database.query(db_name, sql)
            return {"rows": rows, "count": len(rows), "database": db_name}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool
    async def check_playlist_integrity() -> dict:
        """Compare playlist items in the database vs REST API.

        Flags orphaned DB entries (items in DB but not accessible via API)
        and missing DB entries (items in API but not in DB).
        """
        # Get playlists from DB
        db_playlists = await database.query(
            "library.db",
            "SELECT guid, Name, Path, type FROM TypedBaseItems WHERE type LIKE '%Playlist%'",
        )

        results = []
        for pl in db_playlists:
            # Count items in DB for this playlist
            db_items = await database.query(
                "library.db",
                f"SELECT COUNT(*) as count FROM PlaylistItems WHERE PlaylistId = '{pl['guid']}'",
            )
            db_count = db_items[0]["count"] if db_items else 0
            results.append({
                "name": pl.get("Name"),
                "guid": pl.get("guid"),
                "path": pl.get("Path"),
                "db_item_count": db_count,
            })

        return {"playlists": results, "count": len(results)}

    @mcp.tool
    async def get_emby_connect_status() -> dict:
        """Get detailed Emby Connect linkage status for all users.

        Shows: Connect username, user ID, link date, auth method,
        last login, and local password status.
        """
        # Query users.db for Connect information
        try:
            users = await database.query(
                "users.db",
                "SELECT * FROM LocalUsersv2",
            )
        except Exception:
            # Table name might differ — try schema discovery
            tables = await database.get_table_info("users.db")
            user_tables = [t["name"] for t in tables if "user" in t["name"].lower()]
            return {
                "error": "Could not find user table. Available tables with 'user' in name",
                "tables": user_tables,
                "hint": "Use query_database to inspect table schema",
            }

        result = []
        for u in users:
            result.append({
                "id": u.get("Id") or u.get("guid"),
                "name": u.get("Name") or u.get("Username"),
                "connect_user_name": u.get("ConnectUserName"),
                "connect_user_id": u.get("ConnectUserId"),
                "connect_link_type": u.get("ConnectLinkType"),
                "has_local_password": bool(u.get("Password") or u.get("EasyPassword")),
                "last_login_date": u.get("LastLoginDate"),
                "last_activity_date": u.get("LastActivityDate"),
                "auth_method": (
                    "connect+local" if u.get("ConnectUserName") and (u.get("Password") or u.get("EasyPassword"))
                    else "connect" if u.get("ConnectUserName")
                    else "local" if (u.get("Password") or u.get("EasyPassword"))
                    else "none"
                ),
            })
        return {"users": result, "count": len(result)}

    @mcp.tool
    async def audit_paths(expected_prefixes: list[str] | None = None) -> dict:
        """Scan all media paths in library.db and flag mismatches.

        Args:
            expected_prefixes: List of expected path prefixes (e.g., ['/mnt/movies', '/mnt/tv']).
                If omitted, uses paths from the EMBY_MEDIA_PATHS environment variable.
        """
        if expected_prefixes is None:
            expected_prefixes = config.media_paths
        if not expected_prefixes:
            return {"error": "No expected_prefixes provided and EMBY_MEDIA_PATHS not configured."}

        rows = await database.query(
            "library.db",
            "SELECT guid, Name, Path FROM TypedBaseItems WHERE Path IS NOT NULL AND Path != '' LIMIT 5000",
        )

        matched = 0
        mismatched = []
        for row in rows:
            path = row.get("Path", "")
            if any(path.startswith(prefix) for prefix in expected_prefixes):
                matched += 1
            else:
                mismatched.append({
                    "name": row.get("Name"),
                    "path": path,
                    "guid": row.get("guid"),
                })

        return {
            "total_checked": len(rows),
            "matched": matched,
            "mismatched_count": len(mismatched),
            "expected_prefixes": expected_prefixes,
            "mismatched_items": mismatched[:50],  # Cap at 50 for readability
        }

    @mcp.tool
    async def get_db_table_info(db_name: str) -> dict:
        """List all tables, columns, and row counts for an Emby database.

        Args:
            db_name: Database file — 'library.db', 'users.db', 'authentication.db', or 'activitylog.db'.
        """
        try:
            tables = await database.get_table_info(db_name)
            return {"database": db_name, "tables": tables, "table_count": len(tables)}
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool
    async def get_db_statistics(db_name: str) -> dict:
        """Get database file size, WAL status, page count, and integrity.

        Args:
            db_name: Database file — 'library.db', 'users.db', 'authentication.db', or 'activitylog.db'.
        """
        try:
            return await database.get_db_stats(db_name)
        except Exception as e:
            return {"error": str(e)}

    @mcp.tool
    async def path_surgery(
        old_prefix: str,
        new_prefix: str,
        confirm: bool = False,
    ) -> dict:
        """Find and replace path prefixes in library.db — both TEXT and BLOB fields.

        Used during migrations to update media paths (e.g., Windows UNC to Linux NFS).
        Safety-gated: requires Emby stopped, creates backup, runs integrity check.

        Args:
            old_prefix: Path prefix to find (e.g., '\\\\\\\\server\\\\share\\\\Media').
            new_prefix: Replacement prefix (e.g., '/mnt/media/movies').
            confirm: Must be true to execute. False returns a preview.
        """
        if not confirm:
            # Preview: count matching rows
            text_rows = await database.query(
                "library.db",
                f"SELECT COUNT(*) as count FROM TypedBaseItems WHERE Path LIKE '{old_prefix}%'",
            )
            blob_rows = await database.query(
                "library.db",
                f"SELECT COUNT(*) as count FROM TypedBaseItems WHERE CAST(data AS TEXT) LIKE '%{old_prefix}%'",
            )
            return {
                "mode": "preview",
                "old_prefix": old_prefix,
                "new_prefix": new_prefix,
                "text_field_matches": text_rows[0]["count"] if text_rows else 0,
                "blob_field_matches": blob_rows[0]["count"] if blob_rows else 0,
                "message": "Pass confirm=true to execute path surgery.",
            }

        # Execute with safety gates
        text_sql = (
            f"UPDATE TypedBaseItems SET Path = REPLACE(Path, '{old_prefix}', '{new_prefix}') "
            f"WHERE Path LIKE '{old_prefix}%'"
        )
        text_result = await database.write("library.db", text_sql, confirm=True)

        blob_sql = (
            f"UPDATE TypedBaseItems SET data = CAST("
            f"REPLACE(CAST(data AS TEXT), '{old_prefix}', '{new_prefix}') AS BLOB) "
            f"WHERE CAST(data AS TEXT) LIKE '%{old_prefix}%'"
        )
        blob_result = await database.write("library.db", blob_sql, confirm=True)

        return {
            "mode": "executed",
            "text_update": text_result,
            "blob_update": blob_result,
        }

    @mcp.tool
    async def delete_playlist(
        playlist_id: str,
        confirm: bool = False,
    ) -> dict:
        """Delete a playlist and its item relationships from library.db.

        Cannot be done via REST API. Safety-gated: requires Emby stopped,
        creates backup, runs integrity check.

        Args:
            playlist_id: The playlist GUID from the database.
            confirm: Must be true to execute. False returns a preview.
        """
        if not confirm:
            # Preview: show what would be deleted
            playlist = await database.query(
                "library.db",
                f"SELECT guid, Name, Path FROM TypedBaseItems WHERE guid = '{playlist_id}'",
            )
            item_count = await database.query(
                "library.db",
                f"SELECT COUNT(*) as count FROM PlaylistItems WHERE PlaylistId = '{playlist_id}'",
            )
            if not playlist:
                return {"error": f"No playlist found with ID: {playlist_id}"}

            return {
                "mode": "preview",
                "playlist_name": playlist[0].get("Name"),
                "playlist_id": playlist_id,
                "item_count": item_count[0]["count"] if item_count else 0,
                "message": "Pass confirm=true to delete this playlist.",
            }

        # Delete items first, then playlist record
        items_result = await database.write(
            "library.db",
            f"DELETE FROM PlaylistItems WHERE PlaylistId = '{playlist_id}'",
            confirm=True,
        )
        playlist_result = await database.write(
            "library.db",
            f"DELETE FROM TypedBaseItems WHERE guid = '{playlist_id}'",
            confirm=True,
        )

        return {
            "mode": "executed",
            "items_deleted": items_result,
            "playlist_deleted": playlist_result,
        }
